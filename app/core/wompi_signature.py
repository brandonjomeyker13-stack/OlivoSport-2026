"""Verificación de la firma de eventos (webhooks) de Wompi.

Referencia oficial: https://docs.wompi.co/docs/colombia/eventos/

El checksum se calcula concatenando, EN ORDEN:
  1) los valores de los campos listados en signature.properties
     (son rutas tipo "transaction.id" que apuntan dentro de `data`)
  2) el campo `timestamp` del evento
  3) el WOMPI_EVENTS_SECRET (nunca el WOMPI_INTEGRITY_SECRET, son distintos)
...y pasando esa cadena por SHA256. Wompi manda el resultado en
signature.checksum (y también en el header X-Event-Checksum).
"""

import hashlib
import hmac
from typing import Any


def _get_nested(data: dict, dotted_path: str) -> Any:
    value: Any = data
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def verify_event_signature(payload: dict, events_secret: str) -> bool:
    """True si el checksum del payload es válido para nuestro secreto.

    Cualquier campo faltante o mal formado se trata como firma inválida
    (fail-closed), nunca se asume válido por default.
    """
    signature = payload.get("signature") or {}
    properties = signature.get("properties") or []
    checksum = signature.get("checksum")
    timestamp = payload.get("timestamp")
    data = payload.get("data") or {}

    if not properties or not checksum or timestamp is None:
        return False

    concatenated = ""
    for prop in properties:
        value = _get_nested(data, prop)
        if value is None:
            return False
        concatenated += str(value)

    concatenated += f"{timestamp}{events_secret}"

    computed = hashlib.sha256(concatenated.encode("utf-8")).hexdigest()

    # Comparación en tiempo constante: evita timing attacks para adivinar
    # el checksum byte a byte.
    return hmac.compare_digest(computed.upper(), str(checksum).upper())