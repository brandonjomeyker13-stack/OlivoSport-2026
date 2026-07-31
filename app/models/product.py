from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, func
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
    cost = Column(Numeric(10, 2), nullable=True)

    # Obligatoria: todo producto debe pertenecer a una categoría (la crea
    # el admin desde /categories) — no se puede crear un producto sin una.
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False, index=True)
    category = relationship("Category", back_populates="products")

    # Hasta 4 imágenes, todas opcionales (ver app/models/product_image.py).
    # order_by en la relación para que siempre lleguen en el orden de la
    # galería y no en el que devuelva la base.
    images = relationship(
        "ProductImage",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductImage.position",
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Nota: NO se pone cascade delete-orphan aquí. Si un producto tiene
    # carritos activos y lo borran, es mejor impedirlo (o marcarlo inactivo)
    # que borrar en cascada los items del carrito de otros usuarios.
    cart_items = relationship("CartItem", back_populates="product")

    @property
    def image_url(self) -> str | None:
        """La imagen principal, o None si el producto no tiene ninguna.

        Antes esto era una columna. Se dejó como propiedad para que el
        frontend que ya consume `image_url` siga funcionando igual, sin
        tener que guardar dos veces la misma URL (columna + galería) y
        arriesgarse a que queden desincronizadas.
        """
        return self.images[0].image_url if self.images else None