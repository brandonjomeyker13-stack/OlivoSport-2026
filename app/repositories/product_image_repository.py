"""Acceso a datos de las imágenes de un producto. Sin reglas de negocio:
el tope de 4 y el orden de la galería los decide product_service."""

from sqlalchemy.orm import Session

from app.models.product_image import ProductImage


def list_by_product(db: Session, product_id: int) -> list[ProductImage]:
    return (
        db.query(ProductImage)
        .filter(ProductImage.product_id == product_id)
        .order_by(ProductImage.position)
        .all()
    )


def get_by_id(db: Session, image_id: int) -> ProductImage | None:
    return db.query(ProductImage).filter(ProductImage.id == image_id).first()


def add(
    db: Session,
    *,
    product_id: int,
    image_url: str,
    storage_path: str | None,
    position: int,
) -> ProductImage:
    image = ProductImage(
        product_id=product_id,
        image_url=image_url,
        storage_path=storage_path,
        position=position,
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    return image


def delete(db: Session, image: ProductImage) -> None:
    db.delete(image)
    db.commit()


def renumber(db: Session, product_id: int) -> None:
    """Deja las posiciones en 0, 1, 2... sin huecos.

    Hace falta después de borrar: si quedaban las posiciones 0 y 2 y se
    sube una imagen nueva, sin renumerar se calcularía la posición 2 otra
    vez y chocaría con la constraint de (product_id, position).
    """
    imagenes = list_by_product(db, product_id)

    # El desplazamiento a negativos es para no chocar contra la constraint
    # en el camino: pasar la posición 2 a la 1 mientras la 1 todavía
    # existe rompería la unicidad a mitad del renumerado.
    for offset, image in enumerate(imagenes):
        image.position = -(offset + 1)
    db.flush()

    for offset, image in enumerate(imagenes):
        image.position = offset
    db.commit()
