from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.order import OrderStatus


class OrderItemRead(BaseModel):
    # `id` es lo que hay que mandar como `order_item_id` para devolver
    # este ítem (ver POST /returns/).
    id: int
    product_id: int
    product_name: str
    unit_price: float
    quantity: int

    model_config = ConfigDict(from_attributes=True)


class OrderRead(BaseModel):
    id: int
    status: OrderStatus
    total_amount: float
    reference: str
    created_at: datetime
    delivered_at: datetime | None = None
    delivery_confirmed_at: datetime | None = None
    # Derecho de retracto: hasta cuándo puede devolverlo (None si todavía
    # no se entregó) y si el botón de devolver debe estar habilitado.
    return_deadline: datetime | None = None
    can_request_return: bool = False
    items: list[OrderItemRead]

    model_config = ConfigDict(from_attributes=True)


class OrderStatusUpdate(BaseModel):
    """Body del PATCH /orders/{id}/status que usa la dueña desde el panel
    admin. Las transiciones válidas se validan en order_service, no acá."""

    status: OrderStatus


class CheckoutResponse(BaseModel):
    """Todo lo que el frontend necesita para abrir el Widget de Wompi."""

    order_id: int
    public_key: str
    currency: str
    amount_in_cents: int
    reference: str
    signature: str