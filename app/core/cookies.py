"""Configuración de la cookie httpOnly del refresh token.

Lovable sirve el frontend en un dominio distinto al backend (cross-site),
así que en producción la cookie NECESITA `SameSite=None` + `Secure=True`
para que el navegador la mande. En local (`ENVIRONMENT=local`), como
normalmente se prueba por http://localhost, se usa `SameSite=Lax` y
`Secure=False` porque los navegadores descartan cookies `Secure` sobre
http plano.
"""

from app.core.config import settings


def refresh_cookie_kwargs(*, max_age_seconds: int | None) -> dict:
    is_local = settings.ENVIRONMENT == "local"
    return dict(
        key=settings.REFRESH_TOKEN_COOKIE_NAME,
        httponly=True,
        secure=not is_local,
        samesite="lax" if is_local else "none",
        max_age=max_age_seconds,
        # Solo se manda en las rutas de auth: reduce exposición si algún
        # día hay un XSS en otra parte del sitio.
        path="/api/v1/auth",
    )