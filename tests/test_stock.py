"""Reserva y liberación de stock alrededor de un pedido.

La regla que estos tests protegen: el stock se reserva al crear el
pedido y se libera exactamente una vez cuando el pedido muere (cancelado,
expirado o pago rechazado). Si se libera de más, se vende algo que no
existe; si se libera de menos, queda inventario fantasma bloqueado.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.order import Order, OrderStatus
from app.repositories import cart_repository
from app.services import order_service


def test_crear_pedido_descuenta_el_stock_y_congela_precio_y_costo(db, usuario, crear_producto):
    producto = crear_producto(stock=10, precio="50000.00", costo="30000.00")
    cart_repository.create(db, user_id=usuario.id, product_id=producto.id, quantity=3)

    pedido = order_service.create_order_from_cart(db, user_id=usuario.id)

    db.refresh(producto)
    assert producto.stock == 7
    assert pedido.status == OrderStatus.PENDING
    assert float(pedido.total_amount) == 150000.0
    item = pedido.items[0]
    assert float(item.unit_price) == 50000.0
    assert float(item.unit_cost) == 30000.0

    # El histórico no se mueve aunque el producto cambie de precio después.
    producto.price = 99999
    db.commit()
    db.refresh(item)
    assert float(item.unit_price) == 50000.0


def test_sin_stock_suficiente_no_deja_reservas_a_medias(db, usuario, crear_producto):
    """Si el segundo producto no alcanza, el primero NO puede quedar
    descontado: o se reserva todo el pedido, o no se reserva nada."""
    disponible = crear_producto(nombre="Camiseta", stock=10)
    agotado = crear_producto(nombre="Pantaloneta", stock=1)
    cart_repository.create(db, user_id=usuario.id, product_id=disponible.id, quantity=2)
    cart_repository.create(db, user_id=usuario.id, product_id=agotado.id, quantity=5)

    with pytest.raises(order_service.InsufficientStockError):
        order_service.create_order_from_cart(db, user_id=usuario.id)

    db.rollback()
    db.refresh(disponible)
    db.refresh(agotado)
    assert disponible.stock == 10
    assert agotado.stock == 1
    assert db.query(Order).count() == 0


def test_carrito_vacio_no_crea_pedido(db, usuario):
    with pytest.raises(order_service.EmptyCartError):
        order_service.create_order_from_cart(db, user_id=usuario.id)


def test_checkout_dos_veces_con_el_mismo_carrito_reusa_el_pedido(db, usuario, crear_producto):
    """Doble clic en "Pagar" no debe crear dos pedidos ni descontar el
    stock dos veces."""
    producto = crear_producto(stock=10)
    cart_repository.create(db, user_id=usuario.id, product_id=producto.id, quantity=2)

    primero = order_service.create_order_from_cart(db, user_id=usuario.id)
    segundo = order_service.create_order_from_cart(db, user_id=usuario.id)

    assert primero.id == segundo.id
    db.refresh(producto)
    assert producto.stock == 8
    assert db.query(Order).count() == 1


def test_cancelar_devuelve_el_stock_una_sola_vez(db, usuario, crear_producto):
    producto = crear_producto(stock=10)
    cart_repository.create(db, user_id=usuario.id, product_id=producto.id, quantity=4)
    pedido = order_service.create_order_from_cart(db, user_id=usuario.id)

    order_service.cancel_order(db, pedido.id, usuario.id)

    db.refresh(producto)
    assert producto.stock == 10
    assert pedido.status == OrderStatus.CANCELLED

    # Cancelar de nuevo no puede devolver stock por segunda vez.
    with pytest.raises(order_service.InvalidStatusTransitionError):
        order_service.cancel_order(db, pedido.id, usuario.id)
    db.refresh(producto)
    assert producto.stock == 10


def test_no_se_puede_cancelar_el_pedido_de_otra_persona(db, usuario, crear_usuario, crear_producto):
    producto = crear_producto(stock=10)
    cart_repository.create(db, user_id=usuario.id, product_id=producto.id, quantity=1)
    pedido = order_service.create_order_from_cart(db, user_id=usuario.id)
    intruso = crear_usuario(email="intruso@pruebas.olivosport.co")

    with pytest.raises(order_service.OrderNotFoundError):
        order_service.cancel_order(db, pedido.id, intruso.id)

    db.refresh(pedido)
    assert pedido.status == OrderStatus.PENDING


def test_pedido_abandonado_expira_y_libera_el_stock(db, usuario, crear_producto):
    producto = crear_producto(stock=10)
    cart_repository.create(db, user_id=usuario.id, product_id=producto.id, quantity=6)
    pedido = order_service.create_order_from_cart(db, user_id=usuario.id)

    pedido.created_at = datetime.now(timezone.utc) - timedelta(
        hours=order_service.PENDING_ORDER_TTL_HOURS + 1
    )
    db.commit()

    assert order_service.expire_stale_orders(db) == 1

    db.refresh(pedido)
    db.refresh(producto)
    assert pedido.status == OrderStatus.EXPIRED
    assert producto.stock == 10

    # Segunda pasada: ya no queda nada por expirar ni stock que devolver.
    assert order_service.expire_stale_orders(db) == 0
    db.refresh(producto)
    assert producto.stock == 10


def test_entrega_sin_confirmar_se_autoconfirma_pasado_el_plazo(db, usuario, crear_producto):
    producto = crear_producto(stock=10)
    cart_repository.create(db, user_id=usuario.id, product_id=producto.id, quantity=1)
    pedido = order_service.create_order_from_cart(db, user_id=usuario.id)
    pedido.status = OrderStatus.AWAITING_CONFIRMATION
    pedido.delivered_at = datetime.now(timezone.utc) - timedelta(
        days=order_service.DELIVERY_AUTO_CONFIRM_DAYS + 1
    )
    db.commit()

    assert order_service.auto_confirm_stale_deliveries(db) == 1

    db.refresh(pedido)
    assert pedido.status == OrderStatus.DELIVERED
    assert pedido.delivery_confirmed_at is not None


def test_el_admin_no_puede_saltarse_estados_de_entrega(db, usuario, crear_producto):
    producto = crear_producto(stock=10)
    cart_repository.create(db, user_id=usuario.id, product_id=producto.id, quantity=1)
    pedido = order_service.create_order_from_cart(db, user_id=usuario.id)

    # PENDING -> IN_TRANSIT no existe: primero tiene que estar pago.
    with pytest.raises(order_service.InvalidStatusTransitionError):
        order_service.update_delivery_status(db, pedido.id, OrderStatus.IN_TRANSIT)

    pedido.status = OrderStatus.APPROVED
    db.commit()
    # DELIVERED solo lo pone el cliente (o la autoconfirmación), nunca el admin.
    with pytest.raises(order_service.InvalidStatusTransitionError):
        order_service.update_delivery_status(db, pedido.id, OrderStatus.DELIVERED)

    order_service.update_delivery_status(db, pedido.id, OrderStatus.IN_TRANSIT)
    db.refresh(pedido)
    assert pedido.status == OrderStatus.IN_TRANSIT
