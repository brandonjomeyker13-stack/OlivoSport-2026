"""
Qué orígenes (dominios del frontend) pueden hablarle a esta API.

Vive acá y no en `main_app.py` porque la lista la usan dos cosas: el
middleware de CORS y el chequeo de Origin de los endpoints que se
autentican con la cookie del refresh token (`require_trusted_origin`).
"""

import re
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8080",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]

# El subdominio de preview de Lovable cambia por proyecto/sesión.
ALLOWED_ORIGIN_REGEX = r"https://.*\.(lovable\.app|lovableproject\.com)"

_ORIGIN_PATTERN = re.compile(ALLOWED_ORIGIN_REGEX)


def is_trusted_origin(origin: str) -> bool:
    return origin in ALLOWED_ORIGINS or _ORIGIN_PATTERN.fullmatch(origin) is not None


def require_trusted_origin(request: Request) -> None:
    """Rechaza el request si viene de una página que no es nuestra.

    Es protección CSRF. La cookie del refresh token sale con
    `SameSite=None` (obligatorio: el frontend está en otro dominio), así
    que el navegador la manda también cuando la petición la dispara
    CUALQUIER sitio — una página maliciosa podía hacerle POST a
    /auth/logout o /auth/refresh al visitante y sacarlo de su sesión.

    El navegador siempre manda `Origin` en un POST cross-site y no se
    puede falsificar desde JavaScript. Si no viene `Origin`, la petición
    no la originó una página web (curl, la app móvil), y ahí no hay CSRF
    que valga: esos clientes no tienen la cookie del usuario a menos que
    se las den.
    """
    origin = request.headers.get("origin")
    if origin is None or is_trusted_origin(origin):
        return

    # Same-origin: la petición sale de una página servida por esta misma
    # API (el /docs de Swagger, por ejemplo). Se compara solo el host
    # porque detrás del proxy la app ve http:// aunque afuera sea https.
    if urlsplit(origin).netloc == request.headers.get("host"):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Origen no permitido.",
    )
