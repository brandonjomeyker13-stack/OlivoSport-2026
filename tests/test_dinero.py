"""Precisión del dinero y validación del monto que reporta Wompi.

Dos cosas distintas que se prueban acá:

1. Que las cuentas se hagan en Decimal. Con float, 3 ítems de 33.333,33
   dan 99.999,990000000005 y el total que se firma para Wompi deja de
   cuadrar al centavo con lo que se cobra.
2. Que un evento firmado por Wompi no alcance por sí solo para dar un
   pedido por pagado: la firma NO cubre la `reference`, así que hay que
   comparar monto, moneda y transacción contra el pedido.
"""

from decimal import Decimal

import pytest

from app.models.order import Order, OrderStatus
from app.repositories import cart_repository, sales_repository
from app.services import order_service

WEBHOOK_URL = "/api/v1/webhooks/wompi"


def test_el_total_del_pedido_se_suma_en_decimal_exacto(db, usuario, crear_producto):
    producto = crear_producto(precio="33333.33", stock=10)
    cart_repository.create(db, user_id=usuario.id, product_id=producto.id, quantity=3)

    pedido = order_service.create_order_from_cart(db, user_id=usuario.id)

    assert pedido.total_amount == Decimal("99999.99")
    assert order_service.to_cents(pedido.total_amount) == 9999999


def test_el_monto_que_se_firma_no_pierde_ni_gana_centavos(db, usuario, crear_producto):
    """El caso clásico de float: 0.1 + 0.2 = 0.30000000000000004."""
    producto = crear_producto(precio="0.10", stock=10)
    otro = crear_producto(nombre="Medias", precio="0.20", stock=10)
    cart_repository.create(db, user_id=usuario.id, product_id=producto.id, quantity=1)
    cart_repository.create(db, user_id=usuario.id, product_id=otro.id, quantity=1)

    pedido = order_service.create_order_from_cart(db, user_id=usuario.id)
    payload = order_service.build_checkout_payload(pedido)

    assert pedido.total_amount == Decimal("0.30")
    assert payload["amount_in_cents"] == 30


def test_to_cents_redondea_medio_centavo_hacia_arriba():
    assert order_service.to_cents(Decimal("1234.565")) == 123457
    assert order_service.to_cents(Decimal("1234.564")) == 123456
    assert order_service.to_cents(Decimal("0")) == 0


def test_la_ganancia_del_reporte_se_calcula_en_decimal(db, usuario, crear_producto):
    producto = crear_producto(precio="19999.99", costo="10000.01", stock=100)
    cart_repository.create(db, user_id=usuario.id, product_id=producto.id, quantity=7)
    pedido = order_service.create_order_from_cart(db, user_id=usuario.id)
    pedido.status = OrderStatus.APPROVED
    db.commit()

    resumen = sales_repository.get_total_sales(db)

    assert resumen["revenue"] == Decimal("139999.93")
    assert resumen["cost"] == Decimal("70000.07")
    assert resumen["profit"] == Decimal("69999.86")
    assert resumen["items_sold"] == 7


# --- El evento firmado tiene que cuadrar con el pedido -------------------


def test_un_evento_por_menos_plata_no_aprueba_el_pedido(
    client, db, usuario, crear_producto, pedido_pendiente, evento_wompi
):
    """El ataque que esto tapa: la firma de Wompi cubre id + status +
    amount_in_cents, pero NO la reference. Un evento real de una compra de
    $1.000 sigue teniendo checksum válido si le cambian la referencia por
    la de un pedido de $500.000."""
    producto = crear_producto(precio="250000.00", stock=10)
    pedido = pedido_pendiente(usuario, producto, cantidad=2)

    respuesta = client.post(
        WEBHOOK_URL,
        json=evento_wompi(pedido=pedido, status="APPROVED", amount_in_cents=100000),
    )

    assert respuesta.status_code == 200
    db.refresh(pedido)
    db.refresh(producto)
    assert pedido.status == OrderStatus.PENDING
    assert pedido.wompi_transaction_id is None
    assert producto.stock == 8  # la reserva sigue en pie hasta que expire


def test_un_evento_en_otra_moneda_no_aprueba_el_pedido(
    client, db, usuario, crear_producto, pedido_pendiente, evento_wompi
):
    producto = crear_producto(precio="250000.00", stock=10)
    pedido = pedido_pendiente(usuario, producto, cantidad=2)

    respuesta = client.post(
        WEBHOOK_URL, json=evento_wompi(pedido=pedido, status="APPROVED", currency="USD")
    )

    assert respuesta.status_code == 200
    db.refresh(pedido)
    assert pedido.status == OrderStatus.PENDING


def test_no_se_puede_reusar_la_misma_transaccion_en_otro_pedido(
    client, db, usuario, crear_producto, pedido_pendiente, evento_wompi
):
    """Mismo monto, misma moneda, firma válida... pero es la transacción
    que ya pagó otro pedido. Sin este chequeo, con una sola compra real se
    podrían dar por pagados todos los pedidos que valgan lo mismo."""
    producto = crear_producto(precio="100000.00", stock=10)
    primero = pedido_pendiente(usuario, producto, cantidad=1)
    client.post(WEBHOOK_URL, json=evento_wompi(pedido=primero, status="APPROVED"))
    db.refresh(primero)
    assert primero.status == OrderStatus.APPROVED

    segundo = pedido_pendiente(usuario, producto, cantidad=1)
    assert segundo.id != primero.id

    respuesta = client.post(WEBHOOK_URL, json=evento_wompi(pedido=segundo, status="APPROVED"))

    assert respuesta.status_code == 200
    db.refresh(segundo)
    assert segundo.status == OrderStatus.PENDING


def test_el_service_avisa_del_desajuste_en_vez_de_tragarselo(
    db, usuario, crear_producto, pedido_pendiente
):
    producto = crear_producto(precio="100000.00", stock=10)
    pedido = pedido_pendiente(usuario, producto, cantidad=1)

    with pytest.raises(order_service.WompiEventMismatchError):
        order_service.process_wompi_transaction(
            db,
            reference=pedido.reference,
            wompi_status="APPROVED",
            wompi_transaction_id="una-transaccion",
            amount_in_cents=1,
        )

    assert db.query(Order).filter(Order.status == OrderStatus.APPROVED).count() == 0
