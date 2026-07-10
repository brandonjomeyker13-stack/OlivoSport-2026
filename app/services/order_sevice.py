"""Reglas de negocio de pedidos (Order) y checkout con Wompi."""

import hashlib
import secrets

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.order import Order, OrderItem, OrderStatus
from app.repositories import cart_repository, product_repository


class EmptyCartError(Exception):
    pass


class InsufficientStockError(Exception):
    pass


class OrderNotFoundError(Exception):
    pass


class WompiNotConfiguredError(Exception):
    pass


def _generate_reference(order_id: int) -> str:
    # Wompi no permite reusar una referencia jamás, ni siquiera para el
    # mismo pedido en un segundo intento de pago. El sufijo aleatorio
    # evita choques si el usuario reintenta pagar el mismo pedido.
    return f"olivosport-{order_id}-{secrets.token_hex(4)}"


def _sign(reference: str, amount_in_cents: int, currency: str) -> str:
    if not settings.WOMPI_INTEGRITY_SECRET:
        raise WompiNotConfiguredError("Falta configurar WOMPI_INTEGRITY_SECRET.")
    raw = f"{reference}{amount_in_cents}{currency}{settings.WOMPI_INTEGRITY_SECRET}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_order_from_cart(db: Session, *, user_id: int) -> Order:
    """Congela el carrito actual del usuario en un pedido nuevo, en estado
    PENDING. Valida stock, pero NO lo descuenta todavía (eso se hace recién
    cuando Wompi confirma el pago, vía webhook)."""
    cart_items = cart_repository.list_by_user(db, user_id)
    if not cart_items:
        raise EmptyCartError("El carrito está vacío.")

    order_items = []
    total = 0
    for item in cart_items:
        product = product_repository.get_by_id(db, item.product_id)
        if product is None or item.quantity > product.stock:
            name = product.name if product else f"#{item.product_id}"
            raise InsufficientStockError(
                f"No hay stock suficiente de '{name}' para completar el pedido."
            )
        order_items.append(
            OrderItem(
                product_id=product.id,
                product_name=product.name,
                unit_price=product.price,
                quantity=item.quantity,
            )
        )
        total += float(product.price) * item.quantity

    order = Order(
        user_id=user_id,
        reference="",  # se completa abajo, una vez que ya existe el id
        status=OrderStatus.PENDING,
        total_amount=total,
        items=order_items,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    order.reference = _generate_reference(order.id)
    db.commit()
    db.refresh(order)
    return order


def build_checkout_payload(order: Order) -> dict:
    if not settings.WOMPI_PUBLIC_KEY:
        raise WompiNotConfiguredError("Falta configurar WOMPI_PUBLIC_KEY.")

    amount_in_cents = int(round(float(order.total_amount) * 100))
    currency = settings.WOMPI_CURRENCY
    signature = _sign(order.reference, amount_in_cents, currency)

    return {
        "order_id": order.id,
        "public_key": settings.WOMPI_PUBLIC_KEY,
        "currency": currency,
        "amount_in_cents": amount_in_cents,
        "reference": order.reference,
        "signature": signature,
    }


def get_order_or_raise(db: Session, order_id: int, *, user_id: int | None = None) -> Order:
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None or (user_id is not None and order.user_id != user_id):
        raise OrderNotFoundError(f"Pedido {order_id} no encontrado.")
    return order


def list_my_orders(db: Session, user_id: int) -> list[Order]:
    return (
        db.query(Order)
        .filter(Order.user_id == user_id)
        .order_by(Order.created_at.desc())
        .all()
    )


def list_all_orders(db: Session, skip: int = 0, limit: int = 100) -> list[Order]:
    return (
        db.query(Order)
        .order_by(Order.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )