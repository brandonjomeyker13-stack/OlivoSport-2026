"""Refresh tokens para sesiones. Guardamos el HASH (sha256), nunca el
token en texto plano — si alguien lee la base de datos no puede usarlos
directamente (igual que con las contraseñas).
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash = Column(String(64), unique=True, index=True, nullable=False)

    # Rotación: cuando se usa este token para pedir uno nuevo, queda
    # revocado y apunta a cuál lo reemplazó. Si alguien intenta reusar un
    # token ya rotado, es la señal clásica de que fue robado.
    replaced_by_id = Column(Integer, ForeignKey("refresh_tokens.id"), nullable=True)

    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")