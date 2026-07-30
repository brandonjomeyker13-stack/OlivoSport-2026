"""Acceso a datos para reportes de ventas. Solo SELECT/agregaciones, sin
reglas de negocio. La regla de qué cuenta como "venta" vive en
order_service.SALE_ORDER_STATUSES — se importa de ahí para no duplicarla."""

from datetime import datetime

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.order import Order, OrderItem
from app.services.order_service import SALE_ORDER_STATUSES


def _base_query(db: Session):
    return (
        db.query(
            func.sum(OrderItem.unit_price * OrderItem.quantity).label("revenue"),
            func.sum(func.coalesce(OrderItem.unit_cost, 0) * OrderItem.quantity).label("cost"),
            func.sum(OrderItem.quantity).label("items_sold"),
            func.sum(
                case((OrderItem.unit_cost.is_(None), OrderItem.quantity), else_=0)
            ).label("items_without_cost"),
            func.count(func.distinct(Order.id)).label("orders_count"),
        )
        .join(Order, OrderItem.order_id == Order.id)
        .filter(Order.status.in_(SALE_ORDER_STATUSES))
    )


def _row_to_summary(row) -> dict:
    revenue = float(row.revenue or 0)
    cost = float(row.cost or 0)
    return {
        "revenue": revenue,
        "cost": cost,
        "profit": revenue - cost,
        "items_sold": int(row.items_sold or 0),
        "items_without_cost": int(row.items_without_cost or 0),
        "orders_count": int(row.orders_count or 0),
    }


def get_total_sales(db: Session) -> dict:
    """Ventas de TODO el historial, sin filtro de fecha."""
    row = _base_query(db).one()
    return _row_to_summary(row)


def get_sales_by_period(
    db: Session, granularity: str, *, date_from: datetime, date_to: datetime
) -> list[dict]:
    """granularity: 'day' | 'week' | 'month'. Usa date_trunc de Postgres
    (Supabase corre sobre Postgres, así que esto asume ese motor)."""
    period_col = func.date_trunc(granularity, Order.created_at).label("period")
    rows = (
        db.query(
            period_col,
            func.sum(OrderItem.unit_price * OrderItem.quantity).label("revenue"),
            func.sum(func.coalesce(OrderItem.unit_cost, 0) * OrderItem.quantity).label("cost"),
            func.sum(OrderItem.quantity).label("items_sold"),
            func.sum(
                case((OrderItem.unit_cost.is_(None), OrderItem.quantity), else_=0)
            ).label("items_without_cost"),
            func.count(func.distinct(Order.id)).label("orders_count"),
        )
        .join(Order, OrderItem.order_id == Order.id)
        .filter(
            Order.status.in_(SALE_ORDER_STATUSES),
            Order.created_at >= date_from,
            Order.created_at < date_to,
        )
        .group_by(period_col)
        .order_by(period_col)
        .all()
    )
    return [
        {
            "period": row.period,
            "revenue": float(row.revenue or 0),
            "cost": float(row.cost or 0),
            "profit": float((row.revenue or 0) - (row.cost or 0)),
            "items_sold": int(row.items_sold or 0),
            "items_without_cost": int(row.items_without_cost or 0),
            "orders_count": int(row.orders_count or 0),
        }
        for row in rows
    ]