"""Order = un pedido ya confirmado (a diferencia del carrito, que es
"lo que estoy pensando comprar"). Se crea al iniciar el checkout, y sus
ítems guardan una FOTO del precio en ese momento — si el producto cambia
de precio después, los pedidos viejos no se ven afectados."""

import enum

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

from app.db.base import Base


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    VOIDED = "VOIDED"
    ERROR = "ERROR"
    EXPIRED = "EXPIRED"  # nadie completó el pago a tiempo (abandonado)


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

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)

    # Foto del producto en el momento de la compra. Si el producto se
    # borra o cambia después, el pedido conserva estos datos igual.
    product_name = Column(String(150), nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    quantity = Column(Integer, nullable=False)

    order = relationship("Order", back_populates="items")
    product = relationship("Product")
    
