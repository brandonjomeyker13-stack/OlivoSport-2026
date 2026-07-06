"""Acceso a datos de CartItem. Solo queries, sin reglas de negocio."""

from sqlalchemy.orm import Session

from app.models.cart import CartItem


def get_by_id(db: Session, cart_item_id: int) -> CartItem | None:
    return db.query(CartItem).filter(CartItem.id == cart_item_id).first()


def get_by_user_and_product(
    db: Session, user_id: int, product_id: int
) -> CartItem | None:
    return (
        db.query(CartItem)
        .filter(CartItem.user_id == user_id, CartItem.product_id == product_id)
        .first()
    )


def list_by_user(db: Session, user_id: int) -> list[CartItem]:
    return db.query(CartItem).filter(CartItem.user_id == user_id).all()


def create(db: Session, *, user_id: int, product_id: int, quantity: int) -> CartItem:
    item = CartItem(user_id=user_id, product_id=product_id, quantity=quantity)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_quantity(db: Session, item: CartItem, quantity: int) -> CartItem:
    item.quantity = quantity
    db.commit()
    db.refresh(item)
    return item


def delete(db: Session, item: CartItem) -> None:
    db.delete(item)
    db.commit()