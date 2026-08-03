from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.order_return import ReturnStatus


class ReturnItemCreate(BaseModel):
    """Qué ítem del pedido se devuelve y cuántas unidades de ese ítem.
    `order_item_id` es el `id` que viene en `items[]` del pedido, no el id
    del producto: un mismo producto puede estar en dos pedidos distintos."""

    order_item_id: int
    quantity: int = Field(gt=0)


class ReturnCreate(BaseModel):
    order_id: int
    items: list[ReturnItemCreate] = Field(min_length=1)
    # Opcional porque la ley no obliga al cliente a justificar el retracto.
    reason: str | None = Field(default=None, max_length=500)


class ReturnResolution(BaseModel):
    """Nota de la dueña al aprobar o rechazar. Al rechazar es obligatoria
    (lo valida return_service)."""

    note: str | None = Field(default=None, max_length=500)


class ReturnReceived(BaseModel):
    # Por defecto la mercancía vuelve al inventario. Se manda false cuando
    # llegó dañada o usada y no se puede volver a vender.
    restock: bool = True


class ReturnRefund(BaseModel):
    # Comprobante del reembolso: id de la transacción de Wompi, o número
    # de la transferencia si se devolvió a mano.
    refund_reference: str | None = Field(default=None, max_length=100)


class ReturnItemRead(BaseModel):
    order_item_id: int
    quantity: int

    model_config = ConfigDict(from_attributes=True)


class ReturnRead(BaseModel):
    id: int
    order_id: int
    status: ReturnStatus
    reason: str | None = None
    admin_note: str | None = None
    refund_amount: float
    refund_reference: str | None = None
    restocked: bool
    created_at: datetime
    resolved_at: datetime | None = None
    received_at: datetime | None = None
    refunded_at: datetime | None = None
    # Hasta cuándo tiene la tienda para devolver la plata (30 días
    # calendario desde el retracto, art. 47).
    refund_due_at: datetime | None = None
    items: list[ReturnItemRead]

    model_config = ConfigDict(from_attributes=True)
