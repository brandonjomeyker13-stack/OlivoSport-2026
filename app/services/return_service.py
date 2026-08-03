"""Reglas del derecho de retracto (Ley 1480 de 2011, art. 47).

Qué dice la ley, en corto:

- El cliente puede retractarse dentro de los **5 días hábiles** siguientes
  a la entrega, en ventas no presenciales como esta.
- **No tiene que dar explicaciones.** Por eso el motivo es opcional y por
  eso rechazar una devolución dentro del plazo debería ser excepcional
  (producto usado, o de los que la ley excluye por salubridad).
- El comerciante tiene **30 días calendario** desde el retracto para
  devolverle la plata. Ese vencimiento se expone en `refund_due_at` para
  que la dueña vea cuáles se le están venciendo.

Y lo que la ley NO cubre acá: el producto que llegó defectuoso es
*garantía legal*, no retracto — plazos y flujo distintos.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.order import (
    RETRACTO_DIAS_HABILES,
    RETURNABLE_ORDER_STATUSES,
    Order,
    OrderItem,
)
from app.models.order_return import OrderReturn, ReturnStatus
from app.repositories import order_return_repository, product_repository

logger = logging.getLogger("olivosport.returns")


class ReturnNotFoundError(Exception):
    pass


class OrderNotReturnableError(Exception):
    """El pedido no admite devolución: no se entregó todavía, o ya se
    venció el plazo de retracto."""


class InvalidReturnItemsError(Exception):
    """Los ítems pedidos no sirven: no son de este pedido, la cantidad no
    tiene sentido, o ya se devolvieron."""


class InvalidReturnTransitionError(Exception):
    """La devolución no está en un estado desde el que se pueda hacer eso
    (ej. reembolsar algo que todavía no llegó de vuelta)."""


def _get_order_for_return(db: Session, order_id: int, user_id: int | None) -> Order:
    order = db.query(Order).filter(Order.id == order_id).with_for_update().first()
    if order is None or (user_id is not None and order.user_id != user_id):
        raise ReturnNotFoundError(f"Pedido {order_id} no encontrado.")
    return order


def request_return(
    db: Session,
    *,
    order_id: int,
    user_id: int,
    items: list[tuple[int, int]],
    reason: str | None = None,
) -> OrderReturn:
    """El CLIENTE se retracta de parte (o todo) de un pedido entregado.

    `items` es una lista de (order_item_id, cantidad): permite devolver 1
    de las 3 camisetas que compró, no solo el pedido completo.

    El stock NO vuelve acá: vuelve cuando la mercancía llegue de verdad
    (mark_received). Sumarlo antes sería vender algo que todavía está en
    la casa del cliente.
    """
    order = _get_order_for_return(db, order_id, user_id)

    if order.status not in RETURNABLE_ORDER_STATUSES or order.delivered_at is None:
        raise OrderNotReturnableError(
            "Solo se pueden devolver pedidos que ya fueron entregados."
        )

    vence = order.return_deadline
    if vence is not None and datetime.now(timezone.utc) > vence:
        raise OrderNotReturnableError(
            f"El plazo de retracto de {RETRACTO_DIAS_HABILES} días hábiles "
            f"venció el {vence.date().isoformat()}."
        )

    if not items:
        raise InvalidReturnItemsError("Hay que indicar qué se quiere devolver.")

    items_del_pedido: dict[int, OrderItem] = {item.id: item for item in order.items}
    ya_devueltas = order_return_repository.returned_quantities(db, order_id)

    pedidos: dict[int, int] = {}
    for order_item_id, cantidad in items:
        if cantidad <= 0:
            raise InvalidReturnItemsError("La cantidad a devolver debe ser mayor a cero.")
        if order_item_id in pedidos:
            raise InvalidReturnItemsError(
                f"El ítem {order_item_id} viene repetido: suma las unidades en uno solo."
            )

        item = items_del_pedido.get(order_item_id)
        if item is None:
            raise InvalidReturnItemsError(
                f"El ítem {order_item_id} no pertenece al pedido {order_id}."
            )

        disponible = item.quantity - ya_devueltas.get(order_item_id, 0)
        if cantidad > disponible:
            raise InvalidReturnItemsError(
                f"De '{item.product_name}' solo quedan {disponible} unidades por "
                f"devolver (pediste {cantidad})."
            )
        pedidos[order_item_id] = cantidad

    monto = sum(
        (items_del_pedido[item_id].unit_price * cantidad for item_id, cantidad in pedidos.items()),
        Decimal("0"),
    )

    return order_return_repository.create(
        db,
        order_id=order_id,
        reason=reason,
        refund_amount=monto,
        items=list(pedidos.items()),
    )


def get_return_or_raise(
    db: Session, return_id: int, *, user_id: int | None = None
) -> OrderReturn:
    devolucion = order_return_repository.get_by_id(db, return_id)
    if devolucion is None or (
        user_id is not None and devolucion.order.user_id != user_id
    ):
        raise ReturnNotFoundError(f"Devolución {return_id} no encontrada.")
    return devolucion


def _get_para_cambiar_estado(
    db: Session,
    return_id: int,
    *,
    user_id: int | None = None,
    desde: set[ReturnStatus],
    accion: str,
) -> OrderReturn:
    devolucion = order_return_repository.get_by_id_for_update(db, return_id)
    if devolucion is None or (
        user_id is not None and devolucion.order.user_id != user_id
    ):
        raise ReturnNotFoundError(f"Devolución {return_id} no encontrada.")
    if devolucion.status not in desde:
        raise InvalidReturnTransitionError(
            f"No se puede {accion} una devolución en estado {devolucion.status.value}."
        )
    return devolucion


def cancel_return(db: Session, return_id: int, user_id: int) -> OrderReturn:
    """El cliente se echa para atrás, mientras la dueña no haya respondido
    todavía. Las unidades quedan libres para volver a pedirlas (si el
    plazo de retracto sigue vigente)."""
    devolucion = _get_para_cambiar_estado(
        db,
        return_id,
        user_id=user_id,
        desde={ReturnStatus.REQUESTED},
        accion="cancelar",
    )
    devolucion.status = ReturnStatus.CANCELLED
    devolucion.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(devolucion)
    return devolucion


def approve_return(db: Session, return_id: int, *, note: str | None = None) -> OrderReturn:
    devolucion = _get_para_cambiar_estado(
        db, return_id, desde={ReturnStatus.REQUESTED}, accion="aprobar"
    )
    devolucion.status = ReturnStatus.APPROVED
    devolucion.admin_note = note
    devolucion.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(devolucion)
    return devolucion


def reject_return(db: Session, return_id: int, *, note: str) -> OrderReturn:
    """Rechazar exige motivo escrito: dentro del plazo el retracto es un
    derecho, así que si se niega, el cliente tiene que poder leer por qué
    (y esa nota es la defensa de la tienda si reclama a la SIC)."""
    if not note or not note.strip():
        raise InvalidReturnTransitionError(
            "Para rechazar una devolución hay que explicarle al cliente por qué."
        )
    devolucion = _get_para_cambiar_estado(
        db, return_id, desde={ReturnStatus.REQUESTED}, accion="rechazar"
    )
    devolucion.status = ReturnStatus.REJECTED
    devolucion.admin_note = note.strip()
    devolucion.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(devolucion)
    return devolucion


def mark_received(db: Session, return_id: int, *, restock: bool = True) -> OrderReturn:
    """La mercancía volvió. Si vino en condiciones de venderse otra vez
    (`restock`), recién ahí las unidades vuelven al inventario."""
    devolucion = _get_para_cambiar_estado(
        db, return_id, desde={ReturnStatus.APPROVED}, accion="marcar como recibida"
    )

    if restock:
        for item in devolucion.items:
            producto_id = item.order_item.product_id
            product = product_repository.get_by_id_for_update(db, producto_id)
            if product is None:
                # El producto se borró del catálogo después de la venta:
                # no hay dónde devolver el stock, pero la plata sí se le
                # devuelve igual al cliente.
                logger.warning(
                    "Devolución %s: el producto %s ya no existe, no se repone stock.",
                    devolucion.id, producto_id,
                )
                continue
            product_repository.apply_stock_delta(db, product, item.quantity)
        devolucion.restocked = True

    devolucion.status = ReturnStatus.RECEIVED
    devolucion.received_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(devolucion)
    return devolucion


def mark_refunded(
    db: Session, return_id: int, *, refund_reference: str | None = None
) -> OrderReturn:
    """Se le devolvió la plata al cliente. Acá termina la devolución.

    El reembolso en sí se hace por fuera (Wompi o transferencia): esto
    solo lo registra, con su comprobante. A partir de este estado, los
    ítems devueltos dejan de contar como venta en los reportes.
    """
    devolucion = _get_para_cambiar_estado(
        db, return_id, desde={ReturnStatus.RECEIVED}, accion="reembolsar"
    )
    devolucion.status = ReturnStatus.REFUNDED
    devolucion.refund_reference = refund_reference
    devolucion.refunded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(devolucion)
    return devolucion


def list_my_returns(db: Session, user_id: int) -> list[OrderReturn]:
    return order_return_repository.list_by_user(db, user_id)


def list_all_returns(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    status: ReturnStatus | None = None,
) -> list[OrderReturn]:
    return order_return_repository.list_all(db, skip=skip, limit=limit, status=status)
