from sqlalchemy import Boolean, Column, DateTime, Integer, String, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)

    # Útil para "desactivar" un usuario sin borrarlo (soft-disable)
    is_active = Column(Boolean, default=True, nullable=False)

    # Rol simple: por ahora solo admin/no-admin. Si en el futuro necesitas
    # más roles (ej. "vendedor"), esto se convierte en una tabla Role aparte.
    is_admin = Column(Boolean, default=False, nullable=False)

    # Ley 1581/2012 (Habeas Data, Colombia): exige consentimiento explícito
    # y verificable para el tratamiento de datos personales. Guardamos el
    # hecho de que aceptó y CUÁNDO, como evidencia.
    accepted_terms = Column(Boolean, default=False, nullable=False)
    accepted_terms_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    cart_items = relationship(
        "CartItem", back_populates="user", cascade="all, delete-orphan"
    )