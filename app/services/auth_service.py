"""Emisión y rotación de tokens de sesión (access + refresh)."""

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token
from app.repositories import refresh_token_repository


class InvalidRefreshTokenError(Exception):
    pass


def _new_raw_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def issue_tokens(db: Session, *, user_id: int) -> tuple[str, str, int]:
    """Login: emite un access token nuevo y un refresh token nuevo (sin
    relación con ningún token anterior). Devuelve
    (access_token, raw_refresh_token, refresh_max_age_seconds)."""
    access_token = create_access_token(subject=str(user_id))
    raw_refresh = _new_raw_refresh_token()
    max_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=max_age)
    refresh_token_repository.create(
        db, user_id=user_id, raw_token=raw_refresh, expires_at=expires_at
    )
    return access_token, raw_refresh, max_age


def rotate_refresh_token(db: Session, raw_refresh_token: str) -> tuple[str, str, int]:
    """POST /auth/refresh: valida el refresh token de la cookie, lo
    revoca y emite uno nuevo (rotación). Devuelve
    (access_token, nuevo_raw_refresh_token, refresh_max_age_seconds).

    Si el token ya estaba revocado (alguien reusa uno viejo ya rotado),
    se interpreta como robo: se revocan TODOS los refresh tokens del
    usuario, forzando re-login en todos los dispositivos.
    """
    existing = refresh_token_repository.get_by_raw_token(db, raw_refresh_token)
    if existing is None:
        raise InvalidRefreshTokenError("Refresh token desconocido.")

    if existing.revoked_at is not None:
        refresh_token_repository.revoke_all_for_user(db, existing.user_id)
        raise InvalidRefreshTokenError(
            "Refresh token ya usado. Se cerraron todas las sesiones por seguridad."
        )

    if existing.expires_at < datetime.now(timezone.utc):
        raise InvalidRefreshTokenError("Refresh token expirado.")

    access_token = create_access_token(subject=str(existing.user_id))
    raw_refresh = _new_raw_refresh_token()
    max_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=max_age)
    new_row = refresh_token_repository.create(
        db, user_id=existing.user_id, raw_token=raw_refresh, expires_at=expires_at
    )
    refresh_token_repository.mark_replaced(db, existing, new_row)

    return access_token, raw_refresh, max_age


def revoke_refresh_token(db: Session, raw_refresh_token: str) -> None:
    """POST /auth/logout: revoca el refresh token si existe. No lanza
    error si ya no existe/está revocado — el logout debe ser idempotente."""
    existing = refresh_token_repository.get_by_raw_token(db, raw_refresh_token)
    if existing is not None and existing.revoked_at is None:
        refresh_token_repository.revoke(db, existing)