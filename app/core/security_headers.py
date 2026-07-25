"""Middleware que agrega encabezados de seguridad HTTP a toda respuesta.

FastAPI/Starlette no los pone por defecto. Cierran varias clases de
ataque comunes: clickjacking (X-Frame-Options), MIME sniffing
(X-Content-Type-Options), y fuerza el uso de HTTPS (HSTS).
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Esta es una API pura (sin HTML propio), así que el CSP más
        # seguro es simplemente no permitir cargar nada.
        response.headers["Content-Security-Policy"] = "default-src 'none'"
        # HSTS: le dice al navegador que SIEMPRE use HTTPS con este
        # dominio, incluso si alguien escribe http:// a mano.
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains"
        )
        return response