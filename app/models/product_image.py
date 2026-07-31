"""Imágenes de un producto: hasta 4, todas opcionales.

Van en su propia tabla y no en 4 columnas (`image_url_1`, `image_url_2`,
...) porque con columnas fijas hay que tocar la base cada vez que cambie
el máximo, y borrar la segunda de tres imágenes obliga a ir corriendo las
demás a mano. Acá una fila es una imagen: no hay huecos que rellenar y el
tope de 4 es una regla de negocio (product_service.MAX_PRODUCT_IMAGES),
no una restricción del esquema.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class ProductImage(Base):
    __tablename__ = "product_images"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(
        Integer,
        # Si se borra el producto, se van sus imágenes: solas no
        # significan nada.
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # URL pública del archivo en Supabase Storage (bucket "product-images").
    # El archivo en sí NO vive en esta base de datos, solo el link.
    image_url = Column(String(500), nullable=False)

    # Ruta del archivo dentro del bucket. Se guarda aparte de la URL
    # pública porque es lo que hay que mandarle a Supabase para borrarlo:
    # sin esto, cada imagen reemplazada quedaría ocupando espacio para
    # siempre.
    storage_path = Column(String(500), nullable=True)

    # Orden en que se muestran en la galería. La 0 es la principal (la
    # que sale en el listado del catálogo).
    position = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    product = relationship("Product", back_populates="images")

    __table_args__ = (
        # Dos imágenes del mismo producto no pueden pelear por el mismo
        # lugar en la galería.
        UniqueConstraint("product_id", "position", name="uq_product_images_product_position"),
    )
