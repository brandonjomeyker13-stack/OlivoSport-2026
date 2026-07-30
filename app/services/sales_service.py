"""Reglas de negocio de reportes de ventas. Todo se calcula al vuelo
(SUM/GROUP BY) sobre orders/order_items — sin tabla de agregados
aparte, para no duplicar el dato real que ya vive en los pedidos."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.repositories import sales_repository

_VALID_GRANULARITIES = {"day", "week", "month"}


class InvalidGranularityError(Exception):
    pass


def get_total_sales(db: Session) -> dict:
    return sales_repository.get_total_sales(db)


def get_sales_by_period(
    db: Session,
    granularity: str,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[dict]:
    if granularity not in _VALID_GRANULARITIES:
        raise InvalidGranularityError(
            f"granularity debe ser uno de {_VALID_GRANULARITIES}, llegó '{granularity}'."
        )

    # Sin rango explícito: últimos 30 días. Evita escanear todo el
    # historial de pedidos por accidente en una tienda con años de datos.
    if date_to is None:
        date_to = datetime.now(timezone.utc)
    if date_from is None:
        date_from = date_to - timedelta(days=30)

    return sales_repository.get_sales_by_period(
        db, granularity, date_from=date_from, date_to=date_to
    )