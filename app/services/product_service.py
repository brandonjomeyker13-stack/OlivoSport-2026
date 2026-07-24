"""Reglas de negocio de Product."""

from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.product import Product
from app.repositories import product_repository


class ProductNotFoundError(Exception):
    pass


class InsufficientStockError(Exception):
    pass


class ProductHasOrdersError(Exception):
    pass


def create_product(
    db: Session, *, name: str, color: str, size: str, price: Decimal, stock: int
) -> Product:
    return product_repository.create(
        db, name=name, color=color, size=size, price=price, stock=stock
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
) -> Product:
    product = get_product_or_raise(db, product_id)
    return product_repository.update(
        db, product, name=name, color=color, size=size, price=price, stock=stock
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


def set_product_image(db: Session, product_id: int, image_url: str) -> Product:
    product = get_product_or_raise(db, product_id)
    return product_repository.update(db, product, image_url=image_url)


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