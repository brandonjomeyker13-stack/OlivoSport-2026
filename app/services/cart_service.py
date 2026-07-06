"""Reglas de negocio del carrito."""

from sqlalchemy.orm import Session

from app.models.cart import CartItem
from app.repositories import cart_repository, product_repository
from app.services.product_service import ProductNotFoundError


def add_to_cart(db: Session, *, user_id: int, product_id: int, quantity: int) -> CartItem:
    product = product_repository.get_by_id(db, product_id)
    if product is None:
        raise ProductNotFoundError(f"Producto {product_id} no encontrado.")

    existing = cart_repository.get_by_user_and_product(db, user_id, product_id)
    if existing is not None:
        return cart_repository.update_quantity(db, existing, existing.quantity + quantity)

    return cart_repository.create(
        db, user_id=user_id, product_id=product_id, quantity=quantity
    )


def get_cart(db: Session, user_id: int) -> list[CartItem]:
    return cart_repository.list_by_user(db, user_id)


def remove_from_cart(db: Session, *, user_id: int, cart_item_id: int) -> None:
    item = cart_repository.get_by_id(db, cart_item_id)
    if item is None or item.user_id != user_id:
        # No revelamos si el item existe pero es de otro usuario: mismo error.
        raise ValueError("Item de carrito no encontrado.")
    cart_repository.delete(db, item)