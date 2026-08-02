"""Order = un pedido ya confirmado (a diferencia del carrito, que es
"lo que estoy pensando comprar"). Se crea al iniciar el checkout, y sus
ítems guardan una FOTO del precio en ese momento — si el producto cambia
de precio después, los pedidos viejos no se ven afectados."""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import relationship

from app.core.dias_habiles import fin_del_plazo
from app.db.base import Base


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    VOIDED = "VOIDED"
    ERROR = "ERROR"
    EXPIRED = "EXPIRED"  # nadie completó el pago a tiempo (abandonado)
    CANCELLED = "CANCELLED"  # el cliente lo canceló él mismo, antes de pagar

    # Logística: solo se llega acá DESPUÉS de APPROVED, nunca directo.
    IN_TRANSIT = "IN_TRANSIT"  # la dueña ya salió a entregar el pedido
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"  # la dueña dice que ya entregó, falta que el cliente confirme
    DELIVERED = "DELIVERED"  # ambas partes de acuerdo (o se confirmó solo tras 5 días sin respuesta)


# Los grupos viven acá, junto al enum, y no en un service: los usan tanto
# los services como los repositorios de reportes, y un repositorio no
# puede importar de un service (la dependencia va en el otro sentido).

# Estados en los que un pedido representa dinero YA cobrado de verdad
# (Wompi aprobó el pago). Es la fuente única de verdad de "esto es una
# venta real" — se reusa en los reportes de /sales y al borrar productos,
# para no tener dos definiciones de lo mismo que se puedan desincronizar.
SALE_ORDER_STATUSES = {
    OrderStatus.APPROVED,
    OrderStatus.IN_TRANSIT,
    OrderStatus.AWAITING_CONFIRMATION,
    OrderStatus.DELIVERED,
}

# Agrupación para separar "en curso" de "finalizados" en el historial del
# cliente (GET /orders/?stage=active|completed).
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

# Derecho de retracto, Ley 1480 de 2011 art. 47: 5 días HÁBILES contados
# desde la entrega del bien. El cliente no tiene que justificar nada.
RETRACTO_DIAS_HABILES = 5

# Estados en los que la mercancía ya está en manos del cliente y por lo
# tanto puede retractarse. AWAITING_CONFIRMATION cuenta: la dueña ya
# entregó, que el cliente no haya apretado el botón de confirmar no le
# quita el derecho ni le corre el plazo.
RETURNABLE_ORDER_STATUSES = {
    OrderStatus.AWAITING_CONFIRMATION,
    OrderStatus.DELIVERED,
}


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Referencia única mandada a Wompi. Es distinta por cada intento de
    # pago (Wompi no permite reusar una referencia), aunque sea del mismo
    # pedido, por eso NO es simplemente el id del pedido.
    reference = Column(String(100), unique=True, nullable=False, index=True)

    status = Column(Enum(OrderStatus), nullable=False, default=OrderStatus.PENDING)

    # Guardado en pesos (no en centavos) para que sea consistente con
    # Product.price. La conversión a centavos para Wompi se hace al vuelo.
    total_amount = Column(Numeric(10, 2), nullable=False)

    # Datos de la transacción de Wompi, una vez que responde (útil para
    # soporte/conciliación sin tener que llamar a su API cada vez).
    wompi_transaction_id = Column(String(100), nullable=True)

    # delivered_at: cuándo la dueña marcó "ya lo entregué" (momento real
    # de la entrega física). Este es el que cuenta para el derecho de
    # retracto de la Ley 1480 (5 días hábiles desde la entrega).
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    # delivery_confirmed_at: cuándo quedó en DELIVERED — porque el
    # cliente confirmó, o porque pasaron 5 días sin respuesta y se
    # autoconfirmó.
    delivery_confirmed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    returns = relationship(
        "OrderReturn", back_populates="order", cascade="all, delete-orphan"
    )

    @property
    def return_deadline(self) -> datetime | None:
        """Hasta cuándo puede retractarse el cliente. None si el pedido
        todavía no se entregó (el plazo no ha empezado a correr)."""
        if self.delivered_at is None:
            return None
        return fin_del_plazo(self.delivered_at, RETRACTO_DIAS_HABILES)

    @property
    def can_request_return(self) -> bool:
        """Para que el frontend sepa si mostrar el botón de devolver. No
        mira si ya se devolvió todo lo del pedido — eso lo valida el
        service, que sí puede consultar la base."""
        vence = self.return_deadline
        return (
            self.status in RETURNABLE_ORDER_STATUSES
            and vence is not None
            and datetime.now(timezone.utc) <= vence
        )


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)

    # Foto del producto en el momento de la compra. Si el producto se
    # borra o cambia después, el pedido conserva estos datos igual.
    product_name = Column(String(150), nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    unit_cost = Column(Numeric(10, 2), nullable=True)
    quantity = Column(Integer, nullable=False)

    order = relationship("Order", back_populates="items")
    product = relationship("Product")