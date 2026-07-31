"""Webhook de Wompi: firma e idempotencia.

Este endpoint es público (Wompi no manda JWT), así que la firma es lo
único que separa un pago real de alguien inventando un POST. Y como
Wompi reintenta el mismo evento hasta 3 veces en 24h, procesarlo dos
veces no puede descontar ni devolver stock dos veces.

Los eventos los arma el fixture `evento_wompi` (ver conftest.py), que
calcula el checksum a mano a propósito: si lo pidiera prestado a
`verify_event_signature`, estos tests no probarían nada.
"""

from app.models.order import OrderStatus
from app.repositories import cart_repository

WEBHOOK_URL = "/api/v1/webhooks/wompi"


def test_firma_invalida_no_toca_el_pedido(
    client, db, usuario, crear_producto, pedido_pendiente, evento_wompi
):
    producto = crear_producto(stock=10)
    pedido = pedido_pendiente(usuario, producto)

    respuesta = client.post(
        WEBHOOK_URL,
        json=evento_wompi(pedido=pedido, status="APPROVED", secret="secreto-del-atacante"),
    )

    assert respuesta.status_code == 401
    db.refresh(pedido)
    assert pedido.status == OrderStatus.PENDING


def test_evento_sin_firma_es_rechazado(
    client, db, usuario, crear_producto, pedido_pendiente, evento_wompi
):
    producto = crear_producto(stock=10)
    pedido = pedido_pendiente(usuario, producto)
    evento = evento_wompi(pedido=pedido, status="APPROVED")
    del evento["signature"]

    assert client.post(WEBHOOK_URL, json=evento).status_code == 401
    db.refresh(pedido)
    assert pedido.status == OrderStatus.PENDING


def test_pago_aprobado_confirma_el_pedido_sin_volver_a_descontar_stock(
    client, db, usuario, crear_producto, pedido_pendiente, evento_wompi
):
    producto = crear_producto(stock=10)
    pedido = pedido_pendiente(usuario, producto, cantidad=3)
    assert producto.stock == 7  # ya reservado al crear el pedido

    respuesta = client.post(WEBHOOK_URL, json=evento_wompi(pedido=pedido, status="APPROVED"))

    assert respuesta.status_code == 200
    db.refresh(pedido)
    db.refresh(producto)
    assert pedido.status == OrderStatus.APPROVED
    assert pedido.wompi_transaction_id == "12345-1699999999-99999"
    assert producto.stock == 7
    assert cart_repository.list_by_user(db, usuario.id) == []


def test_reintento_del_mismo_evento_es_idempotente(
    client, db, usuario, crear_producto, pedido_pendiente, evento_wompi
):
    producto = crear_producto(stock=10)
    pedido = pedido_pendiente(usuario, producto, cantidad=3)
    evento = evento_wompi(pedido=pedido, status="APPROVED")

    for _ in range(3):
        assert client.post(WEBHOOK_URL, json=evento).status_code == 200

    db.refresh(pedido)
    db.refresh(producto)
    assert pedido.status == OrderStatus.APPROVED
    assert producto.stock == 7


def test_pago_rechazado_libera_el_stock_una_sola_vez(
    client, db, usuario, crear_producto, pedido_pendiente, evento_wompi
):
    producto = crear_producto(stock=10)
    pedido = pedido_pendiente(usuario, producto, cantidad=4)
    evento = evento_wompi(pedido=pedido, status="DECLINED")

    client.post(WEBHOOK_URL, json=evento)
    db.refresh(pedido)
    db.refresh(producto)
    assert pedido.status == OrderStatus.DECLINED
    assert producto.stock == 10

    client.post(WEBHOOK_URL, json=evento)
    db.refresh(producto)
    assert producto.stock == 10


def test_evento_tardio_no_pisa_un_pedido_ya_entregado(
    client, db, usuario, crear_producto, pedido_pendiente, evento_wompi
):
    producto = crear_producto(stock=10)
    pedido = pedido_pendiente(usuario, producto)
    pedido.status = OrderStatus.DELIVERED
    db.commit()

    respuesta = client.post(
        WEBHOOK_URL,
        json=evento_wompi(pedido=pedido, status="DECLINED", transaction_id="otra-transaccion"),
    )

    assert respuesta.status_code == 200
    db.refresh(pedido)
    db.refresh(producto)
    assert pedido.status == OrderStatus.DELIVERED
    assert producto.stock == 8


def test_estado_intermedio_de_wompi_deja_el_pedido_pendiente(
    client, db, usuario, crear_producto, pedido_pendiente, evento_wompi
):
    producto = crear_producto(stock=10)
    pedido = pedido_pendiente(usuario, producto)

    respuesta = client.post(WEBHOOK_URL, json=evento_wompi(pedido=pedido, status="PENDING"))

    assert respuesta.status_code == 200
    db.refresh(pedido)
    assert pedido.status == OrderStatus.PENDING


def test_referencia_desconocida_responde_200_para_que_wompi_no_reintente(client, evento_wompi):
    respuesta = client.post(
        WEBHOOK_URL,
        json=evento_wompi(
            reference="olivosport-999-inexistente", status="APPROVED", amount_in_cents=5000000
        ),
    )

    assert respuesta.status_code == 200
    assert respuesta.json() == {"received": True}


def test_otro_tipo_de_evento_se_ignora(
    client, db, usuario, crear_producto, pedido_pendiente, evento_wompi
):
    producto = crear_producto(stock=10)
    pedido = pedido_pendiente(usuario, producto)
    evento = evento_wompi(pedido=pedido, status="APPROVED")
    evento["event"] = "nequi_token.updated"

    assert client.post(WEBHOOK_URL, json=evento).status_code == 200
    db.refresh(pedido)
    assert pedido.status == OrderStatus.PENDING


def test_un_evento_incompleto_no_deja_los_datos_del_comprador_en_el_log(
    client, caplog, evento_wompi
):
    """El evento de Wompi trae email, teléfono y datos del medio de pago
    del comprador: si se loguea el payload entero, esa información queda
    guardada en los logs de Render sin necesidad."""
    evento = evento_wompi(reference=None, status="APPROVED", amount_in_cents=5000)
    evento["data"]["transaction"]["customer_email"] = "cliente@pruebas.olivosport.co"
    evento["data"]["transaction"]["customer_data"] = {"phone_number": "3001234567"}

    with caplog.at_level("WARNING"):
        assert client.post(WEBHOOK_URL, json=evento).status_code == 200

    assert "cliente@pruebas.olivosport.co" not in caplog.text
    assert "3001234567" not in caplog.text
    assert "reference" in caplog.text
