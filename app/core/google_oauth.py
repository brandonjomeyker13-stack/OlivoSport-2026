"""Verificación de id_tokens de Google Sign-In.

El único flujo seguro es: el frontend obtiene un id_token de Google y lo
manda acá; NUNCA confiamos en un email que venga "suelto" del frontend
sin pasar por esta verificación — si no, cualquiera podría loguearse
como cualquier email con solo mandarlo en el body de la request.
"""

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.core.config import settings


class InvalidGoogleTokenError(Exception):
    pass


def verify_google_id_token(token: str) -> dict:
    """Devuelve los claims verificados (email, sub, name, ...) o lanza
    InvalidGoogleTokenError. `sub` es el ID estable de la cuenta de
    Google — úsalo como identificador, nunca el email solo."""
    if not settings.GOOGLE_CLIENT_ID:
        raise InvalidGoogleTokenError("Google OAuth no está configurado en el servidor.")

    try:
        claims = google_id_token.verify_oauth2_token(
            token, google_requests.Request(), settings.GOOGLE_CLIENT_ID
        )
    except ValueError as exc:
        raise InvalidGoogleTokenError("Token de Google inválido o expirado.") from exc

    if not claims.get("email_verified", False):
        raise InvalidGoogleTokenError(
            "El email de esta cuenta de Google no está verificado."
        )

    return claims