"""Devolución de un pedido por derecho de retracto (Ley 1480 de 2011,
art. 47): en las ventas no presenciales el cliente puede arrepentirse
dentro de los 5 días hábiles siguientes a la entrega, sin tener que
justificar por qué, y el comerciante debe devolverle el dinero.

Una devolución es SIEMPRE parcial-capaz: guarda qué ítems del pedido y
cuántas unidades de cada uno se devuelven, no el pedido entero. Alguien
que compró 3 camisetas puede devolver solo 1.
"""

import enum
from datetime import datetime, timedelta

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class ReturnStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"  # el cliente la pidió, falta que la dueña responda
    APPROVED = "APPROVED"  # aceptada: falta que llegue la mercancía de vuelta
    REJECTED = "REJECTED"  # rechazada (siempre con motivo escrito)
    RECEIVED = "RECEIVED"  # la mercancía ya volvió; falta devolver la plata
    REFUNDED = "REFUNDED"  # plata devuelta: acá termina
    CANCELLED = "CANCELLED"  # el cliente se arrepintió de arrepentirse


# Estados en los que las unidades siguen "comprometidas": no se pueden
# volver a pedir en otra devolución del mismo pedido. Rechazada o
# cancelada, en cambio, liberan las unidades para intentarlo de nuevo.
ACTIVE_RETURN_STATUSES = {
    ReturnStatus.REQUESTED,
    ReturnStatus.APPROVED,
    ReturnStatus.RECEIVED,
    ReturnStatus.REFUNDED,
}

# Estados que el cliente ve como "en curso" (todavía puede pasar algo).
OPEN_RETURN_STATUSES = {
    ReturnStatus.REQUESTED,
    ReturnStatus.APPROVED,
    ReturnStatus.RECEIVED,
}

# Art. 47: el dinero se devuelve "a más tardar dentro de los treinta (30)
# días calendario siguientes" a que el cliente ejerza el retracto. Estos
# sí son calendario, no hábiles.
REFUND_DEADLINE_DAYS = 30


class OrderReturn(Base):
    __tablename__ = "order_returns"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(
        Integer,
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status = Column(Enum(ReturnStatus), nullable=False, default=ReturnStatus.REQUESTED)

    # El motivo es opcional a propósito: dentro de los 5 días hábiles el
    # retracto NO requiere justificación. Se pide igual porque sirve para
    # saber qué se está devolviendo y por qué.
    reason = Column(String(500), nullable=True)

    # Respuesta de la dueña. Obligatoria cuando rechaza (lo valida el
    # service), para que el cliente sepa por qué.
    admin_note = Column(String(500), nullable=True)

    # Cuánto hay que devolverle. Se calcula al crear la devolución con los
    # precios que quedaron congelados en el pedido, no con los de hoy: si
    # el producto subió de precio después, se le devuelve lo que pagó.
    refund_amount = Column(Numeric(10, 2), nullable=False)

    # Comprobante del reembolso (el número de la transacción de Wompi, o
    # de la transferencia si se hizo a mano).
    refund_reference = Column(String(100), nullable=True)

    # Si la mercancía volvió en condiciones de venderse otra vez, la dueña
    # marca que sí y las unidades vuelven al stock.
    restocked = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)  # aprobada o rechazada
    received_at = Column(DateTime(timezone=True), nullable=True)
    refunded_at = Column(DateTime(timezone=True), nullable=True)

    order = relationship("Order", back_populates="returns")
    items = relationship(
        "OrderReturnItem",
        back_populates="order_return",
        cascade="all, delete-orphan",
    )

    @property
    def refund_due_at(self) -> datetime | None:
        """Fecha límite legal para tener la plata devuelta. Sirve para que
        la dueña vea en el panel cuáles se le están venciendo."""
        if self.created_at is None:
            return None
        return self.created_at + timedelta(days=REFUND_DEADLINE_DAYS)


class OrderReturnItem(Base):
    __tablename__ = "order_return_items"

    id = Column(Integer, primary_key=True, index=True)
    return_id = Column(
        Integer,
        ForeignKey("order_returns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_item_id = Column(
        Integer,
        ForeignKey("order_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quantity = Column(Integer, nullable=False)

    order_return = relationship("OrderReturn", back_populates="items")
    order_item = relationship("OrderItem")

    __table_args__ = (
        # El mismo ítem del pedido no puede aparecer dos veces en la misma
        # devolución: si el cliente quiere devolver 2 unidades, va en
        # quantity, no en dos filas.
        UniqueConstraint("return_id", "order_item_id", name="uq_order_return_items_item"),
    )
