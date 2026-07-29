"""Reglas de negocio de pedidos (Order) y checkout con Wompi."""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.order import Order, OrderItem, OrderStatus
from app.repositories import cart_repository, product_repository

logger = logging.getLogger("olivosport.orders")

# Estados finales que puede reportar Wompi para una transacción. Wompi
# también puede mandar eventos con status intermedios (ej. "PENDING") que
# simplemente ignoramos hasta que llegue el estado final.
_WOMPI_TERMINAL_STATUSES = {"APPROVED", "DECLINED", "VOIDED", "ERROR"}

# Transiciones de LOGÍSTICA que puede disparar la dueña desde el panel
# admin. OJO: DELIVERED NO está acá a propósito — a ese estado solo se
# llega por confirm_delivery() (el cliente) o auto_confirm_stale_deliveries()
# (a los 5 días sin respuesta), nunca porque el admin lo ponga directo.
_DELIVERY_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.APPROVED: {OrderStatus.IN_TRANSIT},
    OrderStatus.IN_TRANSIT: {OrderStatus.AWAITING_CONFIRMATION},
}

# Si el cliente no confirma la entrega en este plazo, se autoconfirma —
# para que un pedido no quede esperando para siempre solo porque el
# cliente no volvió a entrar a la página.
DELIVERY_AUTO_CONFIRM_DAYS = 5

# Después de este tiempo sin respuesta de Wompi, asumimos que el usuario
# abandonó el pago y liberamos el pedido (no bloquea stock ni el producto).
PENDING_ORDER_TTL_HOURS = 2


class EmptyCartError(Exception):
    pass


class InsufficientStockError(Exception):
    pass


class OrderNotFoundError(Exception):
    pass


class InvalidStatusTransitionError(Exception):
    pass


class WompiNotConfiguredError(Exception):
    pass


def expire_stale_orders(db: Session) -> int:
    """Marca como EXPIRED los pedidos PENDING más viejos que el TTL.

    Se llama de forma "perezosa" (al listar o crear pedidos) en vez de
    necesitar un cron aparte: para el volumen de una tienda chica/mediana
    alcanza y sobra, y es una línea menos de infraestructura que mantener.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=PENDING_ORDER_TTL_HOURS)
    updated = (
        db.query(Order)
        .filter(Order.status == OrderStatus.PENDING, Order.created_at < cutoff)
        .update({"status": OrderStatus.EXPIRED}, synchronize_session=False)
    )
    if updated:
        db.commit()
    return updated


def auto_confirm_stale_deliveries(db: Session) -> int:
    """Si pasaron DELIVERY_AUTO_CONFIRM_DAYS días desde que la dueña
    marcó un pedido como entregado (AWAITING_CONFIRMATION) y el cliente
    nunca confirmó, se marca DELIVERED de todos modos. Se llama de forma
    perezosa (igual que expire_stale_orders), no hace falta un cron aparte."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=DELIVERY_AUTO_CONFIRM_DAYS)
    updated = (
        db.query(Order)
        .filter(
            Order.status == OrderStatus.AWAITING_CONFIRMATION,
            Order.delivered_at < cutoff,
        )
        .update(
            {
                "status": OrderStatus.DELIVERED,
                "delivery_confirmed_at": datetime.now(timezone.utc),
            },
            synchronize_session=False,
        )
    )
    if updated:
        db.commit()
    return updated


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


def _cart_matches_order(order: Order, cart_items: list) -> bool:
    order_map = {item.product_id: item.quantity for item in order.items}
    cart_map = {item.product_id: item.quantity for item in cart_items}
    return order_map == cart_map


def create_order_from_cart(db: Session, *, user_id: int) -> Order:
    """Congela el carrito actual del usuario en un pedido nuevo, en estado
    PENDING. Valida stock, pero NO lo descuenta todavía (eso se hace recién
    cuando Wompi confirma el pago, vía webhook).

    Idempotente: si el usuario ya tiene un pedido PENDING con exactamente
    el mismo contenido (mismo producto/cantidad), se reusa ese en vez de
    crear uno nuevo — evita duplicados por doble clic o por un reintento
    de red del botón de pagar.
    """
    expire_stale_orders(db)

    cart_items = cart_repository.list_by_user(db, user_id)
    if not cart_items:
        raise EmptyCartError("El carrito está vacío.")

    existing_pending = (
        db.query(Order)
        .filter(Order.user_id == user_id, Order.status == OrderStatus.PENDING)
        .order_by(Order.created_at.desc())
        .first()
    )
    if existing_pending is not None and _cart_matches_order(existing_pending, cart_items):
        return existing_pending

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

    # TEMPORAL — para comparar contra lo que el widget realmente le manda
    # a Wompi (ver Network tab del navegador). Quitar una vez resuelto.
    # (nivel WARNING a propósito: por ahora nada configura logging.basicConfig,
    # así que INFO no se ve en la consola de Render — esto sí sale seguro)
    logger.warning(
        "DEBUG checkout order_id=%s reference=%r amount_in_cents=%r currency=%r signature=%s",
        order.id, order.reference, amount_in_cents, currency, signature,
    )

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
    expire_stale_orders(db)
    auto_confirm_stale_deliveries(db)
    return (
        db.query(Order)
        .filter(Order.user_id == user_id)
        .order_by(Order.created_at.desc())
        .all()
    )


def list_all_orders(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    status: OrderStatus | None = None,
) -> list[Order]:
    expire_stale_orders(db)
    auto_confirm_stale_deliveries(db)
    query = db.query(Order)
    if status is not None:
        query = query.filter(Order.status == status)
    return query.order_by(Order.created_at.desc()).offset(skip).limit(limit).all()


def update_delivery_status(db: Session, order_id: int, new_status: OrderStatus) -> Order:
    """Usado por la dueña desde el panel admin para marcar
    APPROVED -> IN_TRANSIT -> AWAITING_CONFIRMATION. Nunca permite saltos,
    y nunca permite poner DELIVERED directo (eso lo confirma el cliente,
    o se autoconfirma a los 5 días)."""
    order = get_order_or_raise(db, order_id)
    allowed = _DELIVERY_TRANSITIONS.get(order.status, set())
    if new_status not in allowed:
        raise InvalidStatusTransitionError(
            f"No se puede pasar de {order.status.value} a {new_status.value}."
        )
    order.status = new_status
    if new_status == OrderStatus.AWAITING_CONFIRMATION:
        order.delivered_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(order)
    return order


def confirm_delivery(db: Session, order_id: int, user_id: int) -> Order:
    """El CLIENTE confirma que ya recibió su pedido. Solo el dueño del
    pedido puede hacerlo, y solo si está en AWAITING_CONFIRMATION."""
    order = get_order_or_raise(db, order_id, user_id=user_id)
    if order.status != OrderStatus.AWAITING_CONFIRMATION:
        raise InvalidStatusTransitionError(
            "Este pedido no está esperando tu confirmación de entrega."
        )
    order.status = OrderStatus.DELIVERED
    order.delivery_confirmed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(order)
    return order


def process_wompi_transaction(
    db: Session,
    *,
    reference: str,
    wompi_status: str,
    wompi_transaction_id: str,
) -> Order | None:
    """Procesa un evento `transaction.updated` YA VERIFICADO (firma
    correcta) que llega del webhook de Wompi.

    Es idempotente: si Wompi reintenta el mismo evento, no vuelve a
    descontar stock ni a pisar un estado de logística ya avanzado.
    Devuelve None si no existe ningún pedido con esa referencia.
    """
    order = db.query(Order).filter(Order.reference == reference).first()
    if order is None:
        return None

    if wompi_status not in _WOMPI_TERMINAL_STATUSES:
        # Estados intermedios (ej. "PENDING" del lado de Wompi): no hay
        # nada que hacer todavía, esperamos el evento final.
        return order

    new_status = OrderStatus(wompi_status)

    if order.status != OrderStatus.PENDING:
        # El pedido ya salió de PENDING (mismo evento reprocesado, o ya
        # avanzó en logística). No lo tocamos: evita reprocesar un pago
        # ya contabilizado o pisar un estado de entrega más avanzado.
        if order.wompi_transaction_id != wompi_transaction_id:
            logger.warning(
                "Evento de Wompi para pedido %s (status=%s) llegó cuando "
                "el pedido ya estaba en %s. Se ignora.",
                order.id, wompi_status, order.status.value,
            )
        return order

    if new_status == OrderStatus.APPROVED:
        # Recién ACÁ se descuenta stock real, dentro de la misma
        # transacción que confirma el pedido, bloqueando cada producto
        # (SELECT ... FOR UPDATE) para que dos pagos simultáneos no lean
        # el mismo stock viejo.
        for item in order.items:
            product = product_repository.get_by_id_for_update(db, item.product_id)
            if product is None:
                logger.error(
                    "Pedido %s: producto %s ya no existe al confirmar el pago.",
                    order.id, item.product_id,
                )
                continue
            if product.stock < item.quantity:
                # El dinero YA fue cobrado por Wompi — no se puede
                # "des-cobrar" desde acá. Se deja en 0 y queda para
                # revisión manual (backorder) en vez de fallar el
                # webhook y perder la confirmación del pago.
                logger.error(
                    "SOBREVENTA en pedido %s: producto %s tenía stock %s, "
                    "se necesitaban %s. Revisar manualmente.",
                    order.id, product.id, product.stock, item.quantity,
                )
            product_repository.apply_stock_delta(db, product, -item.quantity)

        # Ya se confirmó el pago: esos productos ya no tienen sentido
        # seguir apareciendo en el carrito del cliente (queda incómodo
        # ver algo que ya compró como si todavía estuviera "por comprar").
        product_ids = [item.product_id for item in order.items]
        cart_repository.delete_for_user_and_products(db, order.user_id, product_ids)

    order.status = new_status
    order.wompi_transaction_id = wompi_transaction_id
    db.commit()
    db.refresh(order)
    return order


def clear_non_approved_references(db: Session, product_id: int) -> None:
    """Borra las referencias a este producto en pedidos que NO son ventas
    reales (todo menos APPROVED). Se usa antes de eliminar un producto:
    los pedidos APPROVED se dejan intactos a propósito, son historial de
    ventas y no se tocan nunca."""
    non_approved_order_ids = [
        row[0]
        for row in db.query(Order.id).filter(Order.status != OrderStatus.APPROVED).all()
    ]
    if not non_approved_order_ids:
        return
    db.query(OrderItem).filter(
        OrderItem.product_id == product_id,
        OrderItem.order_id.in_(non_approved_order_ids),
    ).delete(synchronize_session=False)
    db.commit()