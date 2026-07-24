"""Webhook público de Wompi.

IMPORTANTE: este endpoint NO lleva JWT (Wompi no tiene tu token, ni debe
tenerlo). La seguridad acá es 100% la firma HMAC/SHA256 verificada en
`verify_event_signature` — si esa verificación falla, el evento se
rechaza sin excepción, sin importar qué diga el payload.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.wompi_signature import verify_event_signature
from app.db.session import get_db
from app.services import order_service

logger = logging.getLogger("olivosport.webhooks")

router = APIRouter()


@router.post("/wompi", status_code=status.HTTP_200_OK)
async def wompi_event(request: Request, db: Session = Depends(get_db)):
    if not settings.WOMPI_EVENTS_SECRET:
        # Sin secreto configurado no hay forma de verificar la firma:
        # mejor rechazar todo que confiar en un payload sin validar.
        logger.error("WOMPI_EVENTS_SECRET no configurado; evento rechazado.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook no configurado del lado del servidor.",
        )

    payload = await request.json()

    if not verify_event_signature(payload, settings.WOMPI_EVENTS_SECRET):
        logger.warning("Firma inválida en un evento de Wompi. Payload ignorado.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Firma inválida."
        )

    if payload.get("event") != "transaction.updated":
        # Otros tipos de evento (ej. nequi_token.updated) no aplican al
        # flujo de pedidos. Respondemos 200 para que Wompi no reintente.
        return {"received": True}

    transaction = (payload.get("data") or {}).get("transaction") or {}
    reference = transaction.get("reference")
    wompi_status = transaction.get("status")
    wompi_transaction_id = transaction.get("id")

    if not reference or not wompi_status or not wompi_transaction_id:
        logger.warning("Evento de Wompi con datos incompletos: %s", payload)
        return {"received": True}

    order = order_service.process_wompi_transaction(
        db,
        reference=reference,
        wompi_status=wompi_status,
        wompi_transaction_id=wompi_transaction_id,
    )

    if order is None:
        logger.error(
            "Webhook de Wompi: no existe ningún pedido con reference=%s", reference
        )

    # SIEMPRE 200: si devolvemos otra cosa, Wompi reintenta el mismo
    # evento hasta 3 veces en 24h pensando que hubo un error nuestro.
    return {"received": True}