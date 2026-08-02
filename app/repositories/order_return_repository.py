"""Acceso a datos de las devoluciones. Sin reglas de negocio: el plazo de
retracto, quién puede aprobar y cuánto se reembolsa lo decide
return_service."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.order import Order
from app.models.order_return import (
    ACTIVE_RETURN_STATUSES,
    OrderReturn,
    OrderReturnItem,
    ReturnStatus,
)


def get_by_id(db: Session, return_id: int) -> OrderReturn | None:
    return db.query(OrderReturn).filter(OrderReturn.id == return_id).first()


def get_by_id_for_update(db: Session, return_id: int) -> OrderReturn | None:
    """Bloquea la fila mientras se resuelve la devolución: sin esto, dos
    clics seguidos en "reembolsar" podrían devolver la plata dos veces."""
    return (
        db.query(OrderReturn).filter(OrderReturn.id == return_id).with_for_update().first()
    )


def list_by_order(db: Session, order_id: int) -> list[OrderReturn]:
    return (
        db.query(OrderReturn)
        .filter(OrderReturn.order_id == order_id)
        .order_by(OrderReturn.created_at.desc())
        .all()
    )


def list_by_user(db: Session, user_id: int) -> list[OrderReturn]:
    return (
        db.query(OrderReturn)
        .join(Order, OrderReturn.order_id == Order.id)
        .filter(Order.user_id == user_id)
        .order_by(OrderReturn.created_at.desc())
        .all()
    )


def list_all(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    status: ReturnStatus | None = None,
) -> list[OrderReturn]:
    query = db.query(OrderReturn)
    if status is not None:
        query = query.filter(OrderReturn.status == status)
    return query.order_by(OrderReturn.created_at.desc()).offset(skip).limit(limit).all()


def returned_quantities(db: Session, order_id: int) -> dict[int, int]:
    """Cuántas unidades de cada ítem del pedido ya están comprometidas en
    devoluciones vivas. Las rechazadas y canceladas no cuentan: esas
    unidades quedan libres para pedirlas de nuevo."""
    filas = (
        db.query(
            OrderReturnItem.order_item_id,
            func.sum(OrderReturnItem.quantity).label("cantidad"),
        )
        .join(OrderReturn, OrderReturnItem.return_id == OrderReturn.id)
        .filter(
            OrderReturn.order_id == order_id,
            OrderReturn.status.in_(ACTIVE_RETURN_STATUSES),
        )
        .group_by(OrderReturnItem.order_item_id)
        .all()
    )
    return {order_item_id: int(cantidad) for order_item_id, cantidad in filas}


def create(
    db: Session,
    *,
    order_id: int,
    reason: str | None,
    refund_amount,
    items: list[tuple[int, int]],
) -> OrderReturn:
    devolucion = OrderReturn(
        order_id=order_id,
        status=ReturnStatus.REQUESTED,
        reason=reason,
        refund_amount=refund_amount,
        items=[
            OrderReturnItem(order_item_id=order_item_id, quantity=cantidad)
            for order_item_id, cantidad in items
        ],
    )
    db.add(devolucion)
    db.commit()
    db.refresh(devolucion)
    return devolucion
