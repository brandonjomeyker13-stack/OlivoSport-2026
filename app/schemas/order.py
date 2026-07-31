from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.order import OrderStatus


class OrderItemRead(BaseModel):
    id: int
    product_id: int
    product_name: str
    unit_price: float
    quantity: int

    model_config = ConfigDict(from_attributes=True)


class OrderCustomerRead(BaseModel):
    """Datos del comprador, para que el panel admin sepa a quién y a
    dónde entregar sin tener que ir a buscarlo aparte."""

    name: str
    email: str
    phone: str | None = None
    address: str | None = None
    city: str | None = None

    model_config = ConfigDict(from_attributes=True)


class OrderRead(BaseModel):
    id: int
    status: OrderStatus
    total_amount: float
    reference: str
    created_at: datetime
    delivered_at: datetime | None = None
    delivery_confirmed_at: datetime | None = None
    items: list[OrderItemRead]
    # Se arma solo desde Order.user (la relación ya existe en el modelo,
    # no hace falta ningún join manual ni endpoint aparte).
    user: OrderCustomerRead

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