"""Acceso a datos para refresh tokens. Nunca maneja el token en texto
plano más allá de calcular su hash."""

import hashlib
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.refresh_token import RefreshToken


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create(db: Session, *, user_id: int, raw_token: str, expires_at: datetime) -> RefreshToken:
    row = RefreshToken(
        user_id=user_id, token_hash=hash_token(raw_token), expires_at=expires_at
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_by_raw_token(db: Session, raw_token: str) -> RefreshToken | None:
    """Incluye tokens revocados/expirados a propósito: la capa de
    servicio necesita distinguir "no existe" de "existe pero ya fue
    usado/expiró" para poder detectar reuso (posible robo)."""
    return (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == hash_token(raw_token))
        .first()
    )


def mark_replaced(db: Session, row: RefreshToken, new_row: RefreshToken) -> None:
    row.revoked_at = datetime.now(timezone.utc)
    row.replaced_by_id = new_row.id
    db.commit()


def revoke(db: Session, row: RefreshToken) -> None:
    row.revoked_at = datetime.now(timezone.utc)
    db.commit()


def revoke_all_for_user(db: Session, user_id: int) -> None:
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
    ).update({"revoked_at": datetime.now(timezone.utc)})
    db.commit()