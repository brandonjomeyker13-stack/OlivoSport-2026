from datetime import datetime

from pydantic import BaseModel


class SalesSummary(BaseModel):
    """Ingresos/costo/ganancia calculados SOLO sobre pedidos que ya se
    cobraron de verdad (ver models.order.SALE_ORDER_STATUSES).

    items_without_cost > 0 significa que algunos productos vendidos no
    tenían `cost` cargado en ese momento — la ganancia mostrada está
    subestimando el costo real (asume 0 para esos ítems).

    Todo va NETO de devoluciones ya reembolsadas: `revenue` es la plata
    que quedó en la tienda, y `returned_items`/`refunded_amount` muestran
    aparte cuánto se devolvió."""

    revenue: float
    cost: float
    profit: float
    items_sold: int
    items_without_cost: int
    orders_count: int
    returned_items: int = 0
    refunded_amount: float = 0


class SalesPeriod(SalesSummary):
    period: datetime