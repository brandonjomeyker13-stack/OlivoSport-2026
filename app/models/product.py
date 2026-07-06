from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    color = Column(String(50), nullable=False)
    size = Column(String(20), nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    stock = Column(Integer, nullable=False, default=0)
    in_stock = Column(Boolean, default=True, nullable=False)

    # URL pública del archivo en Supabase Storage (bucket "product-images").
    # El archivo en sí NO vive en esta base de datos, solo el link.
    image_url = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Nota: NO se pone cascade delete-orphan aquí. Si un producto tiene
    # carritos activos y lo borran, es mejor impedirlo (o marcarlo inactivo)
    # que borrar en cascada los items del carrito de otros usuarios.
    cart_items = relationship("CartItem", back_populates="product")