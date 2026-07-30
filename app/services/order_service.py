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
    """Marca como EXPIRED los pedidos PENDING más viejos que el TTL, y
    libera el stock que tenían reservado (ver create_order_from_cart).

    Se llama de forma "perezosa" (al listar o crear pedidos) en vez de
    necesitar un cron aparte: para el volumen de una tienda chica/mediana
    alcanza y sobra, y es una línea menos de infraestructura que mantener.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=PENDING_ORDER_TTL_HOURS)
    stale_orders = (
        db.query(Order)
        .filter(Order.status == OrderStatus.PENDING, Order.created_at < cutoff)
        .all()
    )
    for order in stale_orders:
        for item in order.items:
            product = product_repository.get_by_id_for_update(db, item.product_id)
            if product is not None:
                product_repository.apply_stock_delta(db, product, item.quantity)
        order.status = OrderStatus.EXPIRED
    if stale_orders:
        db.commit()
    return len(stale_orders)


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
    PENDING, y RESERVA el stock ahí mismo (bloqueando cada fila de
    producto con SELECT ... FOR UPDATE). Así, si dos personas quieren lo
    último que queda al mismo tiempo, la segunda se entera de una vez que
    no hay stock — nunca llega a pagar por algo que ya no existe.

    Esa reserva se libera sola si el pedido se cancela, expira, o Wompi
    reporta el pago como rechazado/con error (ver cancel_order,
    expire_stale_orders y process_wompi_transaction).

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

    # Primera pasada: bloquear y VALIDAR todo antes de tocar nada. Si
    # algo no alcanza, no queda ninguna reserva a medias.
    locked_products = []
    for item in cart_items:
        product = product_repository.get_by_id_for_update(db, item.product_id)
        if product is None or item.quantity > product.stock:
            name = product.name if product else f"#{item.product_id}"
            raise InsufficientStockError(
                f"No hay stock suficiente de '{name}' para completar el pedido."
            )
        locked_products.append((product, item.quantity))

    # Segunda pasada: ya validado todo, recién ahora se reserva de verdad.
    order_items = []
    total = 0
    for product, quantity in locked_products:
        order_items.append(
            OrderItem(
                product_id=product.id,
                product_name=product.name,
                unit_price=product.price,
                unit_cost=product.cost,
                quantity=quantity,
            )
        )
        total += float(product.price) * quantity
        product_repository.apply_stock_delta(db, product, -quantity)

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


def _get_order_for_update(db: Session, order_id: int, *, user_id: int | None = None) -> Order:
    """Igual que get_order_or_raise, pero bloqueando la fila del pedido
    (SELECT ... FOR UPDATE). Se usa cuando dos cosas podrían intentar
    cambiar el estado del mismo pedido casi al mismo tiempo (ej. el
    cliente cancelando justo cuando el webhook de Wompi lo está
    aprobando) — así solo una de las dos gana, nunca las dos a medias."""
    order = db.query(Order).filter(Order.id == order_id).with_for_update().first()
    if order is None or (user_id is not None and order.user_id != user_id):
        raise OrderNotFoundError(f"Pedido {order_id} no encontrado.")
    return order


def cancel_order(db: Session, order_id: int, user_id: int) -> Order:
    """El CLIENTE cancela su propio pedido, mientras siga PENDING (antes
    de pagar) — libera el stock que se había reservado al crearlo.

    No se puede cancelar:
    - un pedido de otra persona (se valida el dueño)
    - un pedido que ya no está PENDING (ya se pagó, se rechazó, expiró,
      o ya se había cancelado — cancelar dos veces no debe devolver
      stock dos veces)
    """
    order = _get_order_for_update(db, order_id, user_id=user_id)

    if order.status != OrderStatus.PENDING:
        raise InvalidStatusTransitionError(
            "Este pedido ya no se puede cancelar (ya fue pagado, rechazado, "
            "expiró, o ya estaba cancelado)."
        )

    for item in order.items:
        product = product_repository.get_by_id_for_update(db, item.product_id)
        if product is not None:
            product_repository.apply_stock_delta(db, product, item.quantity)

    order.status = OrderStatus.CANCELLED
    db.commit()
    db.refresh(order)
    return order


# Estados desde los que un pedido existente todavía se puede pagar.
_RETRYABLE_STATUSES = {OrderStatus.PENDING, OrderStatus.DECLINED, OrderStatus.ERROR}


def get_checkout_payload_for_order(db: Session, order_id: int, user_id: int) -> dict:
    """Para el botón "Pagar" en un pedido YA creado (no pasa por el
    carrito). Genera una referencia NUEVA cada vez — Wompi no deja
    reusar una referencia ya usada, ni siquiera de un intento fallido.

    - PENDING: el stock ya está reservado, solo se arma un nuevo intento
      de pago con referencia nueva.
    - DECLINED/ERROR: el pago anterior falló, y en ese momento ya se
      había liberado el stock (ver process_wompi_transaction). Acá se
      vuelve a reservar (con bloqueo de fila) antes de dejarlo pagar de
      nuevo. Si ya no alcanza, se avisa en vez de dejarlo pagar por algo
      que no existe.
    - Cualquier otro estado (EXPIRED, CANCELLED, APPROVED en adelante):
      no se puede "revivir" — hay que armar un pedido nuevo desde el carrito.
    """
    order = _get_order_for_update(db, order_id, user_id=user_id)

    if order.status not in _RETRYABLE_STATUSES:
        raise InvalidStatusTransitionError(
            "Este pedido ya no se puede pagar. Si todavía quieres estos "
            "productos, arma un pedido nuevo desde el carrito."
        )

    if order.status in (OrderStatus.DECLINED, OrderStatus.ERROR):
        locked_products = []
        for item in order.items:
            product = product_repository.get_by_id_for_update(db, item.product_id)
            if product is None or item.quantity > product.stock:
                name = product.name if product else f"#{item.product_id}"
                raise InsufficientStockError(
                    f"Ya no hay stock suficiente de '{name}' para reintentar este pedido."
                )
            locked_products.append((product, item.quantity))
        for product, quantity in locked_products:
            product_repository.apply_stock_delta(db, product, -quantity)
        order.status = OrderStatus.PENDING

    order.reference = _generate_reference(order.id)
    db.commit()
    db.refresh(order)

    return build_checkout_payload(order)
    return order


# Agrupación semántica para separar "en curso" de "finalizados" en el
# historial del cliente (GET /orders/?stage=active|completed).
ACTIVE_ORDER_STATUSES = {
    OrderStatus.PENDING,
    OrderStatus.APPROVED,
    OrderStatus.IN_TRANSIT,
    OrderStatus.AWAITING_CONFIRMATION,
}
COMPLETED_ORDER_STATUSES = {
    OrderStatus.DELIVERED,
    OrderStatus.CANCELLED,
    OrderStatus.EXPIRED,
    OrderStatus.DECLINED,
    OrderStatus.VOIDED,
    OrderStatus.ERROR,
}
SALE_ORDER_STATUSES = {
    OrderStatus.APPROVED,
    OrderStatus.IN_TRANSIT,
    OrderStatus.AWAITING_CONFIRMATION,
    OrderStatus.DELIVERED,
}

def list_my_orders(db: Session, user_id: int, stage: str | None = None) -> list[Order]:
    expire_stale_orders(db)
    auto_confirm_stale_deliveries(db)
    query = db.query(Order).filter(Order.user_id == user_id)
    if stage == "active":
        query = query.filter(Order.status.in_(ACTIVE_ORDER_STATUSES))
    elif stage == "completed":
        query = query.filter(Order.status.in_(COMPLETED_ORDER_STATUSES))
    return query.order_by(Order.created_at.desc()).all()


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
    order = db.query(Order).filter(Order.reference == reference).with_for_update().first()
    if order is None:
        return None

    if wompi_status not in _WOMPI_TERMINAL_STATUSES:
        # Estados intermedios (ej. "PENDING" del lado de Wompi): no hay
        # nada que hacer todavía, esperamos el evento final.
        return order

    new_status = OrderStatus(wompi_status)

    if order.status != OrderStatus.PENDING:
        # El pedido ya salió de PENDING (mismo evento reprocesado, ya
        # avanzó en logística, o el cliente lo canceló y esto llegó
        # tarde). No lo tocamos: evita reprocesar un pago ya contabilizado
        # o pisar un estado más avanzado. Como el bloqueo de fila de
        # arriba (with_for_update) espera a que termine cualquier otra
        # transacción que esté tocando este mismo pedido (ej. una
        # cancelación en curso), este chequeo ya ve el estado más
        # reciente posible.
        if order.wompi_transaction_id != wompi_transaction_id:
            logger.warning(
                "Evento de Wompi para pedido %s (status=%s) llegó cuando "
                "el pedido ya estaba en %s. Se ignora.",
                order.id, wompi_status, order.status.value,
            )
        return order

    if new_status == OrderStatus.APPROVED:
        # El stock de este pedido YA se reservó al crearlo (PENDING, ver
        # create_order_from_cart) — acá NO se vuelve a descontar. Solo
        # queda limpiar el carrito, ya que esos productos ya no tienen
        # sentido seguir apareciendo ahí como "por comprar".
        product_ids = [item.product_id for item in order.items]
        cart_repository.delete_for_user_and_products(db, order.user_id, product_ids)
    else:
        # DECLINED / VOIDED / ERROR: el pago no se completó, así que se
        # libera la reserva de stock que se había hecho al crear el pedido.
        for item in order.items:
            product = product_repository.get_by_id_for_update(db, item.product_id)
            if product is None:
                logger.error(
                    "Pedido %s: producto %s ya no existe al liberar su reserva.",
                    order.id, item.product_id,
                )
                continue
            product_repository.apply_stock_delta(db, product, item.quantity)

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