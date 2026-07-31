"""
Limiter compartido (slowapi) para proteger endpoints sensibles de fuerza
bruta, principalmente login y registro.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import settings


def client_ip(request: Request) -> str:
    """IP real del cliente, contando los proxies de confianza que haya
    delante.

    Detrás de un proxy (Render, Cloudflare) `request.client.host` es la IP
    del proxy, o sea que TODOS los usuarios caen en el mismo balde y el
    límite global de 100/minuto se agota entre todos.

    La solución no es confiar en `X-Forwarded-For` a ciegas: ese header lo
    puede escribir el atacante y se saltaría el límite mandando una IP
    distinta en cada intento. Lo que sí es confiable es lo que AGREGA cada
    proxy nuestro al final de la cadena, así que se cuentan saltos desde
    la derecha: con TRUSTED_PROXY_HOPS=1 se toma la última IP, que es la
    que escribió nuestro propio proxy y el cliente no controla.
    """
    hops = settings.TRUSTED_PROXY_HOPS
    if hops > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            ips = [ip.strip() for ip in forwarded.split(",") if ip.strip()]
            if len(ips) >= hops:
                return ips[-hops]

    return get_remote_address(request)


# default_limits aplica a TODOS los endpoints que no tengan su propio
# @limiter.limit(...) — antes /products, /cart, /checkout no tenían
# ningún límite y se podían scrapear/bombardear sin restricción.
#
# storage_uri: en memoria, cada instancia lleva su propia cuenta, así que
# con N instancias el límite real es N veces el configurado. Apuntando
# RATE_LIMIT_STORAGE_URI a un Redis, todas comparten el contador.
limiter = Limiter(
    key_func=client_ip,
    default_limits=["100/minute"],
    storage_uri=settings.RATE_LIMIT_STORAGE_URI,
)
