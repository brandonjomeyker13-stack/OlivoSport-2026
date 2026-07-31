"""Webhook de Wompi: firma e idempotencia.

Este endpoint es público (Wompi no manda JWT), así que la firma es lo
único que separa un pago real de alguien inventando un POST. Y como
Wompi reintenta el mismo evento hasta 3 veces en 24h, procesarlo dos
veces no puede descontar ni devolver stock dos veces.

El checksum se calcula acá a mano, a propósito: si estos tests usaran
`verify_event_signature` para construirlo, no probarían nada.
"""

import hashlib

from app.core.config import settings
from app.models.order import OrderStatus
from app.repositories import cart_repository
from app.services import order_service

WEBHOOK_URL = "/api/v1/webhooks/wompi"
PROPIEDADES_FIRMADAS = ["transaction.id", "transaction.status", "transaction.amount_in_cents"]


def evento_wompi(
    *,
    reference: str,
    status: str,
    transaction_id: str = "12345-1699999999-99999",
    amount_in_cents: int = 5000000,
    timestamp: int = 1699999999,
    secret: str | None = None,
) -> dict:
    """Arma un evento `transaction.updated` con checksum válido (o con uno
    inválido, si le pasas otro `secret`)."""
    transaction = {
        "id": transaction_id,
        "status": status,
        "reference": reference,
        "amount_in_cents": amount_in_cents,
    }
    concatenado = "".join(str(transaction[prop.split(".")[1]]) for prop in PROPIEDADES_FIRMADAS)
    concatenado += f"{timestamp}{secret or settings.WOMPI_EVENTS_SECRET}"

    return {
        "event": "transaction.updated",
        "data": {"transaction": transaction},
        "timestamp": timestamp,
        "signature": {
            "properties": PROPIEDADES_FIRMADAS,
            "checksum": hashlib.sha256(concatenado.encode("utf-8")).hexdigest(),
        },
    }


def pedido_pendiente(db, usuario, producto, cantidad: int = 2):
    cart_repository.create(db, user_id=usuario.id, product_id=producto.id, quantity=cantidad)
    return order_service.create_order_from_cart(db, user_id=usuario.id)


def test_firma_invalida_no_toca_el_pedido(client, db, usuario, crear_producto):
    producto = crear_producto(stock=10)
    pedido = pedido_pendiente(db, usuario, producto)

    respuesta = client.post(
        WEBHOOK_URL,
        json=evento_wompi(
            reference=pedido.reference, status="APPROVED", secret="secreto-del-atacante"
        ),
    )

    assert respuesta.status_code == 401
    db.refresh(pedido)
    assert pedido.status == OrderStatus.PENDING


def test_evento_sin_firma_es_rechazado(client, db, usuario, crear_producto):
    producto = crear_producto(stock=10)
    pedido = pedido_pendiente(db, usuario, producto)
    evento = evento_wompi(reference=pedido.reference, status="APPROVED")
    del evento["signature"]

    assert client.post(WEBHOOK_URL, json=evento).status_code == 401
    db.refresh(pedido)
    assert pedido.status == OrderStatus.PENDING


def test_pago_aprobado_confirma_el_pedido_sin_volver_a_descontar_stock(
    client, db, usuario, crear_producto
):
    producto = crear_producto(stock=10)
    pedido = pedido_pendiente(db, usuario, producto, cantidad=3)
    assert producto.stock == 7  # ya reservado al crear el pedido

    respuesta = client.post(
        WEBHOOK_URL, json=evento_wompi(reference=pedido.reference, status="APPROVED")
    )

    assert respuesta.status_code == 200
    db.refresh(pedido)
    db.refresh(producto)
    assert pedido.status == OrderStatus.APPROVED
    assert pedido.wompi_transaction_id == "12345-1699999999-99999"
    assert producto.stock == 7
    assert cart_repository.list_by_user(db, usuario.id) == []


def test_reintento_del_mismo_evento_es_idempotente(client, db, usuario, crear_producto):
    producto = crear_producto(stock=10)
    pedido = pedido_pendiente(db, usuario, producto, cantidad=3)
    evento = evento_wompi(reference=pedido.reference, status="APPROVED")

    for _ in range(3):
        assert client.post(WEBHOOK_URL, json=evento).status_code == 200

    db.refresh(pedido)
    db.refresh(producto)
    assert pedido.status == OrderStatus.APPROVED
    assert producto.stock == 7


def test_pago_rechazado_libera_el_stock_una_sola_vez(client, db, usuario, crear_producto):
    producto = crear_producto(stock=10)
    pedido = pedido_pendiente(db, usuario, producto, cantidad=4)
    evento = evento_wompi(reference=pedido.reference, status="DECLINED")

    client.post(WEBHOOK_URL, json=evento)
    db.refresh(pedido)
    db.refresh(producto)
    assert pedido.status == OrderStatus.DECLINED
    assert producto.stock == 10

    client.post(WEBHOOK_URL, json=evento)
    db.refresh(producto)
    assert producto.stock == 10


def test_evento_tardio_no_pisa_un_pedido_ya_entregado(client, db, usuario, crear_producto):
    producto = crear_producto(stock=10)
    pedido = pedido_pendiente(db, usuario, producto)
    pedido.status = OrderStatus.DELIVERED
    db.commit()

    respuesta = client.post(
        WEBHOOK_URL,
        json=evento_wompi(
            reference=pedido.reference, status="DECLINED", transaction_id="otra-transaccion"
        ),
    )

    assert respuesta.status_code == 200
    db.refresh(pedido)
    db.refresh(producto)
    assert pedido.status == OrderStatus.DELIVERED
    assert producto.stock == 8


def test_estado_intermedio_de_wompi_deja_el_pedido_pendiente(client, db, usuario, crear_producto):
    producto = crear_producto(stock=10)
    pedido = pedido_pendiente(db, usuario, producto)

    respuesta = client.post(
        WEBHOOK_URL, json=evento_wompi(reference=pedido.reference, status="PENDING")
    )

    assert respuesta.status_code == 200
    db.refresh(pedido)
    assert pedido.status == OrderStatus.PENDING


def test_referencia_desconocida_responde_200_para_que_wompi_no_reintente(client, db):
    respuesta = client.post(
        WEBHOOK_URL, json=evento_wompi(reference="olivosport-999-inexistente", status="APPROVED")
    )

    assert respuesta.status_code == 200
    assert respuesta.json() == {"received": True}


def test_otro_tipo_de_evento_se_ignora(client, db, usuario, crear_producto):
    producto = crear_producto(stock=10)
    pedido = pedido_pendiente(db, usuario, producto)
    evento = evento_wompi(reference=pedido.reference, status="APPROVED")
    evento["event"] = "nequi_token.updated"

    assert client.post(WEBHOOK_URL, json=evento).status_code == 200
    db.refresh(pedido)
    assert pedido.status == OrderStatus.PENDING
