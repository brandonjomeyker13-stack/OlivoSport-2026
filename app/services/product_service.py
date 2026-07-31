"""Reglas de negocio de Product."""

from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.product_image import ProductImage
from app.repositories import (
    category_repository,
    product_image_repository,
    product_repository,
)

# Tope de imágenes por producto. Ninguna es obligatoria: un producto
# puede quedarse en 0 y se sigue mostrando (el frontend pone su
# placeholder). El límite existe para que la galería no crezca sin
# control y la ficha siga cargando rápido en celular.
MAX_PRODUCT_IMAGES = 4


class ProductNotFoundError(Exception):
    pass


class TooManyProductImagesError(Exception):
    pass


class ProductImageNotFoundError(Exception):
    pass


class InsufficientStockError(Exception):
    pass


class ProductHasOrdersError(Exception):
    pass


class CategoryNotFoundError(Exception):
    pass


def create_product(
    db: Session,
    *,
    name: str,
    color: str,
    size: str,
    price: Decimal,
    stock: int,
    category_id: int,
    cost: Decimal | None = None,
) -> Product:
    if category_repository.get_by_id(db, category_id) is None:
        raise CategoryNotFoundError(f"Categoría {category_id} no encontrada.")
    return product_repository.create(
        db,
        name=name,
        color=color,
        size=size,
        price=price,
        stock=stock,
        category_id=category_id,
        cost=cost,
    )


def list_products(
    db: Session, *, skip: int, limit: int, category_id: int | None
) -> list[Product]:
    return product_repository.list_all(
        db, skip=skip, limit=limit, category_id=category_id
    )


def get_product_or_raise(db: Session, product_id: int) -> Product:
    product = product_repository.get_by_id(db, product_id)
    if product is None:
        raise ProductNotFoundError(f"Producto {product_id} no encontrado.")
    return product


def update_product(
    db: Session,
    product_id: int,
    *,
    name: str | None = None,
    color: str | None = None,
    size: str | None = None,
    price: Decimal | None = None,
    stock: int | None = None,
    category_id: int | None = None,
    cost: Decimal | None = None,
) -> Product:
    product = get_product_or_raise(db, product_id)
    if category_id is not None and category_repository.get_by_id(db, category_id) is None:
        raise CategoryNotFoundError(f"Categoría {category_id} no encontrada.")
    return product_repository.update(
        db,
        product,
        name=name,
        color=color,
        size=size,
        price=price,
        stock=stock,
        category_id=category_id,
        cost=cost,
    )


def delete_product(db: Session, product_id: int) -> None:
    from app.repositories import cart_repository
    from app.services import order_service

    product = get_product_or_raise(db, product_id)
    cart_repository.delete_by_product(db, product_id)

    # Limpia referencias en pedidos que NO son ventas reales (abandonados,
    # rechazados, expirados). Los pedidos APPROVED se dejan intactos.
    order_service.expire_stale_orders(db)
    order_service.clear_non_approved_references(db, product_id)

    try:
        product_repository.delete(db, product)
    except IntegrityError as exc:
        db.rollback()
        raise ProductHasOrdersError (
            f"'{product.name}' tiene ventas confirmadas y no se puede eliminar. "
            "Marcalo como agotado/inactivo (in_stock=false) en su lugar."
        ) from exc


def add_product_images(
    db: Session, product_id: int, images: list[tuple[str, str | None]]
) -> Product:
    """Agrega imágenes al final de la galería. `images` es una lista de
    (url, ruta en el bucket).

    Se bloquea la fila del producto (`FOR UPDATE`) mientras se cuenta y se
    inserta: sin eso, dos subidas simultáneas leen "hay 3" al mismo
    tiempo y el producto termina con 5 imágenes.
    """
    product = product_repository.get_by_id_for_update(db, product_id)
    if product is None:
        raise ProductNotFoundError(f"Producto {product_id} no encontrado.")

    actuales = product_image_repository.list_by_product(db, product_id)
    disponibles = MAX_PRODUCT_IMAGES - len(actuales)
    if len(images) > disponibles:
        raise TooManyProductImagesError(
            f"'{product.name}' ya tiene {len(actuales)} de {MAX_PRODUCT_IMAGES} "
            f"imágenes: solo caben {disponibles} más."
        )

    siguiente = len(actuales)
    for offset, (image_url, storage_path) in enumerate(images):
        product_image_repository.add(
            db,
            product_id=product_id,
            image_url=image_url,
            storage_path=storage_path,
            position=siguiente + offset,
        )

    db.refresh(product)
    return product


def delete_product_image(db: Session, product_id: int, image_id: int) -> ProductImage:
    """Quita una imagen de la galería y devuelve la fila borrada, para que
    la capa de API sepa qué archivo eliminar del bucket."""
    image = product_image_repository.get_by_id(db, image_id)
    if image is None or image.product_id != product_id:
        raise ProductImageNotFoundError(
            f"El producto {product_id} no tiene una imagen {image_id}."
        )

    product_image_repository.delete(db, image)
    # Las que quedan se corren para tapar el hueco: la siguiente pasa a
    # ser la principal y la próxima subida encuentra su lugar libre.
    product_image_repository.renumber(db, product_id)
    return image


def replace_product_images(
    db: Session, product_id: int, images: list[tuple[str, str | None]]
) -> tuple[Product, list[ProductImage]]:
    """Deja la galería con exactamente estas imágenes. Devuelve también
    las que se quitaron, para poder borrar sus archivos del bucket."""
    if len(images) > MAX_PRODUCT_IMAGES:
        raise TooManyProductImagesError(
            f"Un producto no puede tener más de {MAX_PRODUCT_IMAGES} imágenes."
        )

    anteriores = product_image_repository.list_by_product(db, product_id)
    for image in anteriores:
        product_image_repository.delete(db, image)

    return add_product_images(db, product_id, images), anteriores


def reserve_stock(db: Session, product_id: int, quantity: int) -> Product:
    """Descuenta stock al agregar al carrito o confirmar una compra.

    Centralizar esta regla aquí evita que dos rutas distintas de la API
    descuenten stock de forma inconsistente.
    """
    product = get_product_or_raise(db, product_id)
    if product.stock < quantity:
        raise InsufficientStockError(
            f"Stock insuficiente para '{product.name}'. Disponible: {product.stock}."
        )
    return product_repository.update_stock(db, product, product.stock - quantity)