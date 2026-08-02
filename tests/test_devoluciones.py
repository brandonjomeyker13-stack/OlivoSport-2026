"""Devoluciones por derecho de retracto (Ley 1480 art. 47).

Las reglas que estos tests protegen:

- el plazo son 5 días HÁBILES desde la entrega, ni antes de entregar ni
  después de vencido;
- nadie puede devolver más unidades de las que compró, ni sumando varias
  solicitudes;
- el stock vuelve cuando la mercancía vuelve, no cuando se pide;
- la plata devuelta deja de contar como venta en los reportes.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.order import OrderStatus
from app.models.order_return import OrderReturn, ReturnStatus
from app.repositories import cart_repository, sales_repository
from app.services import order_service, return_service
from tests.conftest import TEST_DATABASE_URL


@pytest.fixture
def pedido_entregado(db, usuario, crear_producto):
    """Un pedido ya entregado, listo para retractarse: 3 camisetas de
    $50.000 y 1 pantaloneta de $20.000."""

    def _pedido_entregado(*, entregado_hace: timedelta = timedelta(hours=1)):
        camiseta = crear_producto(nombre="Camiseta", stock=10, precio="50000.00")
        pantaloneta = crear_producto(nombre="Pantaloneta", stock=10, precio="20000.00")
        cart_repository.create(db, user_id=usuario.id, product_id=camiseta.id, quantity=3)
        cart_repository.create(
            db, user_id=usuario.id, product_id=pantaloneta.id, quantity=1
        )

        pedido = order_service.create_order_from_cart(db, user_id=usuario.id)
        pedido.status = OrderStatus.DELIVERED
        pedido.delivered_at = datetime.now(timezone.utc) - entregado_hace
        db.commit()
        db.refresh(pedido)
        return pedido

    return _pedido_entregado


def _item(pedido, nombre: str):
    return next(item for item in pedido.items if item.product_name == nombre)


# --- El plazo -------------------------------------------------------------


def test_un_pedido_sin_entregar_no_se_puede_devolver(db, usuario, crear_producto, pedido_pendiente):
    producto = crear_producto(stock=10)
    pedido = pedido_pendiente(usuario, producto, cantidad=1)

    assert pedido.return_deadline is None
    assert pedido.can_request_return is False
    with pytest.raises(return_service.OrderNotReturnableError):
        return_service.request_return(
            db,
            order_id=pedido.id,
            user_id=usuario.id,
            items=[(pedido.items[0].id, 1)],
        )


def test_pasados_los_cinco_dias_habiles_ya_no_se_puede(db, usuario, pedido_entregado):
    # 15 días calendario son más de 5 hábiles con cualquier combinación de
    # festivos, así que el test no depende del día en que corra.
    pedido = pedido_entregado(entregado_hace=timedelta(days=15))

    assert pedido.can_request_return is False
    with pytest.raises(return_service.OrderNotReturnableError):
        return_service.request_return(
            db,
            order_id=pedido.id,
            user_id=usuario.id,
            items=[(_item(pedido, "Camiseta").id, 1)],
        )


def test_el_pedido_expone_hasta_cuando_puede_devolverse(db, usuario, pedido_entregado):
    pedido = pedido_entregado()

    assert pedido.can_request_return is True
    assert pedido.return_deadline > datetime.now(timezone.utc)


def test_tambien_se_puede_devolver_sin_haber_confirmado_la_entrega(
    db, usuario, pedido_entregado
):
    """La dueña ya entregó (AWAITING_CONFIRMATION): que el cliente no haya
    apretado "confirmar" no le quita el derecho a retractarse."""
    pedido = pedido_entregado()
    pedido.status = OrderStatus.AWAITING_CONFIRMATION
    db.commit()

    devolucion = return_service.request_return(
        db,
        order_id=pedido.id,
        user_id=usuario.id,
        items=[(_item(pedido, "Camiseta").id, 1)],
    )

    assert devolucion.status == ReturnStatus.REQUESTED


# --- Qué se puede devolver ------------------------------------------------


def test_se_puede_devolver_solo_una_parte_del_pedido(db, usuario, pedido_entregado):
    pedido = pedido_entregado()
    camiseta = _item(pedido, "Camiseta")

    devolucion = return_service.request_return(
        db,
        order_id=pedido.id,
        user_id=usuario.id,
        items=[(camiseta.id, 1)],
        reason="Me quedó grande",
    )

    assert devolucion.status == ReturnStatus.REQUESTED
    # 1 de 3 camisetas de $50.000: no el pedido completo de $170.000.
    assert devolucion.refund_amount == Decimal("50000.00")
    assert [(i.order_item_id, i.quantity) for i in devolucion.items] == [(camiseta.id, 1)]


def test_el_reembolso_usa_el_precio_que_pago_no_el_de_hoy(db, usuario, pedido_entregado):
    pedido = pedido_entregado()
    camiseta = _item(pedido, "Camiseta")
    camiseta.product.price = Decimal("99999.00")
    db.commit()

    devolucion = return_service.request_return(
        db, order_id=pedido.id, user_id=usuario.id, items=[(camiseta.id, 2)]
    )

    assert devolucion.refund_amount == Decimal("100000.00")


def test_no_se_puede_devolver_mas_de_lo_comprado(db, usuario, pedido_entregado):
    pedido = pedido_entregado()

    with pytest.raises(return_service.InvalidReturnItemsError):
        return_service.request_return(
            db,
            order_id=pedido.id,
            user_id=usuario.id,
            items=[(_item(pedido, "Camiseta").id, 4)],
        )


def test_dos_devoluciones_no_pueden_sumar_mas_de_lo_comprado(db, usuario, pedido_entregado):
    pedido = pedido_entregado()
    camiseta = _item(pedido, "Camiseta")
    return_service.request_return(
        db, order_id=pedido.id, user_id=usuario.id, items=[(camiseta.id, 2)]
    )

    with pytest.raises(return_service.InvalidReturnItemsError):
        return_service.request_return(
            db, order_id=pedido.id, user_id=usuario.id, items=[(camiseta.id, 2)]
        )

    # La tercera unidad sí, que es la que queda.
    otra = return_service.request_return(
        db, order_id=pedido.id, user_id=usuario.id, items=[(camiseta.id, 1)]
    )
    assert otra.refund_amount == Decimal("50000.00")


def test_una_devolucion_rechazada_libera_las_unidades(db, usuario, pedido_entregado):
    pedido = pedido_entregado()
    camiseta = _item(pedido, "Camiseta")
    devolucion = return_service.request_return(
        db, order_id=pedido.id, user_id=usuario.id, items=[(camiseta.id, 3)]
    )
    return_service.reject_return(db, devolucion.id, note="Llegó usada")

    # Las 3 unidades vuelven a estar disponibles para devolver.
    otra = return_service.request_return(
        db, order_id=pedido.id, user_id=usuario.id, items=[(camiseta.id, 3)]
    )
    assert otra.status == ReturnStatus.REQUESTED


def test_no_se_puede_devolver_un_item_de_otro_pedido(db, usuario, pedido_entregado):
    mio = pedido_entregado()
    ajeno_item_id = _item(mio, "Camiseta").id

    otro_pedido = pedido_entregado()
    with pytest.raises(return_service.InvalidReturnItemsError):
        return_service.request_return(
            db, order_id=otro_pedido.id, user_id=usuario.id, items=[(ajeno_item_id, 1)]
        )


def test_no_se_puede_devolver_el_pedido_de_otra_persona(
    db, usuario, crear_usuario, pedido_entregado
):
    pedido = pedido_entregado()
    intruso = crear_usuario(email="intruso@pruebas.olivosport.co")

    with pytest.raises(return_service.ReturnNotFoundError):
        return_service.request_return(
            db,
            order_id=pedido.id,
            user_id=intruso.id,
            items=[(_item(pedido, "Camiseta").id, 1)],
        )


def test_una_cantidad_en_cero_o_negativa_se_rechaza(db, usuario, pedido_entregado):
    pedido = pedido_entregado()

    with pytest.raises(return_service.InvalidReturnItemsError):
        return_service.request_return(
            db,
            order_id=pedido.id,
            user_id=usuario.id,
            items=[(_item(pedido, "Camiseta").id, 0)],
        )


# --- El flujo de la dueña -------------------------------------------------


def test_el_stock_vuelve_cuando_llega_la_mercancia_no_antes(db, usuario, pedido_entregado):
    pedido = pedido_entregado()
    camiseta = _item(pedido, "Camiseta")
    producto = camiseta.product
    stock_tras_la_venta = producto.stock

    devolucion = return_service.request_return(
        db, order_id=pedido.id, user_id=usuario.id, items=[(camiseta.id, 2)]
    )
    db.refresh(producto)
    assert producto.stock == stock_tras_la_venta

    return_service.approve_return(db, devolucion.id)
    db.refresh(producto)
    assert producto.stock == stock_tras_la_venta

    return_service.mark_received(db, devolucion.id)
    db.refresh(producto)
    assert producto.stock == stock_tras_la_venta + 2


def test_la_mercancia_dañada_no_vuelve_al_inventario(db, usuario, pedido_entregado):
    pedido = pedido_entregado()
    camiseta = _item(pedido, "Camiseta")
    producto = camiseta.product
    stock_tras_la_venta = producto.stock

    devolucion = return_service.request_return(
        db, order_id=pedido.id, user_id=usuario.id, items=[(camiseta.id, 1)]
    )
    return_service.approve_return(db, devolucion.id)
    devolucion = return_service.mark_received(db, devolucion.id, restock=False)

    db.refresh(producto)
    assert producto.stock == stock_tras_la_venta
    assert devolucion.restocked is False


def test_no_se_puede_reembolsar_algo_que_no_ha_llegado(db, usuario, pedido_entregado):
    pedido = pedido_entregado()
    devolucion = return_service.request_return(
        db, order_id=pedido.id, user_id=usuario.id, items=[(_item(pedido, "Camiseta").id, 1)]
    )
    return_service.approve_return(db, devolucion.id)

    with pytest.raises(return_service.InvalidReturnTransitionError):
        return_service.mark_refunded(db, devolucion.id)


def test_rechazar_sin_explicar_por_que_no_se_puede(db, usuario, pedido_entregado):
    pedido = pedido_entregado()
    devolucion = return_service.request_return(
        db, order_id=pedido.id, user_id=usuario.id, items=[(_item(pedido, "Camiseta").id, 1)]
    )

    with pytest.raises(return_service.InvalidReturnTransitionError):
        return_service.reject_return(db, devolucion.id, note="   ")


def test_el_flujo_completo_deja_fechas_y_comprobante(db, usuario, pedido_entregado):
    pedido = pedido_entregado()
    devolucion = return_service.request_return(
        db, order_id=pedido.id, user_id=usuario.id, items=[(_item(pedido, "Camiseta").id, 1)]
    )

    return_service.approve_return(db, devolucion.id, note="Trae la factura")
    return_service.mark_received(db, devolucion.id)
    devolucion = return_service.mark_refunded(db, devolucion.id, refund_reference="tx-123")

    assert devolucion.status == ReturnStatus.REFUNDED
    assert devolucion.refund_reference == "tx-123"
    assert devolucion.resolved_at is not None
    assert devolucion.received_at is not None
    assert devolucion.refunded_at is not None
    # 30 días calendario para devolver la plata (art. 47).
    assert (devolucion.refund_due_at - devolucion.created_at).days == 30


def test_el_cliente_puede_retirar_su_solicitud_hasta_que_le_respondan(
    db, usuario, pedido_entregado
):
    pedido = pedido_entregado()
    devolucion = return_service.request_return(
        db, order_id=pedido.id, user_id=usuario.id, items=[(_item(pedido, "Camiseta").id, 1)]
    )

    devolucion = return_service.cancel_return(db, devolucion.id, usuario.id)
    assert devolucion.status == ReturnStatus.CANCELLED

    with pytest.raises(return_service.InvalidReturnTransitionError):
        return_service.cancel_return(db, devolucion.id, usuario.id)


def test_borrar_el_pedido_borra_sus_devoluciones(db, usuario, pedido_entregado):
    pedido = pedido_entregado()
    return_service.request_return(
        db, order_id=pedido.id, user_id=usuario.id, items=[(_item(pedido, "Camiseta").id, 1)]
    )

    db.delete(pedido)
    db.commit()

    assert db.query(OrderReturn).count() == 0


# --- Reportes -------------------------------------------------------------


def test_lo_reembolsado_deja_de_contar_como_venta(db, usuario, pedido_entregado):
    pedido = pedido_entregado()
    camiseta = _item(pedido, "Camiseta")

    # 3 camisetas de $50.000 + 1 pantaloneta de $20.000 = $170.000
    assert sales_repository.get_total_sales(db)["revenue"] == Decimal("170000.00")

    devolucion = return_service.request_return(
        db, order_id=pedido.id, user_id=usuario.id, items=[(camiseta.id, 1)]
    )
    return_service.approve_return(db, devolucion.id)
    return_service.mark_received(db, devolucion.id)

    # Mientras la plata no se haya devuelto, la venta sigue siendo venta.
    assert sales_repository.get_total_sales(db)["revenue"] == Decimal("170000.00")

    return_service.mark_refunded(db, devolucion.id)

    resumen = sales_repository.get_total_sales(db)
    assert resumen["revenue"] == Decimal("120000.00")
    assert resumen["items_sold"] == 3
    assert resumen["returned_items"] == 1
    assert resumen["refunded_amount"] == Decimal("50000.00")


@pytest.mark.skipif(
    not TEST_DATABASE_URL.startswith("postgresql"),
    reason="date_trunc solo existe en Postgres (en CI corre en el job de migraciones).",
)
def test_la_devolucion_se_resta_del_mes_en_que_se_vendio(db, usuario, pedido_entregado):
    """No del mes en que se devolvió: el reporte de un mes cerrado tiene
    que reflejar lo que realmente quedó de ese mes."""
    pedido = pedido_entregado()
    devolucion = return_service.request_return(
        db, order_id=pedido.id, user_id=usuario.id, items=[(_item(pedido, "Camiseta").id, 1)]
    )
    return_service.approve_return(db, devolucion.id)
    return_service.mark_received(db, devolucion.id)
    return_service.mark_refunded(db, devolucion.id)

    ahora = datetime.now(timezone.utc)
    (mes,) = sales_repository.get_sales_by_period(
        db, "month", date_from=ahora - timedelta(days=1), date_to=ahora + timedelta(days=1)
    )

    assert mes["revenue"] == Decimal("120000.00")
    assert mes["refunded_amount"] == Decimal("50000.00")


# --- Permisos de la API ---------------------------------------------------


def test_las_acciones_de_la_dueña_no_las_puede_hacer_un_cliente(client, db, usuario, pedido_entregado):
    pedido = pedido_entregado()
    devolucion = return_service.request_return(
        db, order_id=pedido.id, user_id=usuario.id, items=[(_item(pedido, "Camiseta").id, 1)]
    )

    for ruta in ("approve", "reject", "received", "refund"):
        respuesta = client.patch(f"/api/v1/returns/{devolucion.id}/{ruta}", json={"note": "x"})
        assert respuesta.status_code == 401, ruta

    assert client.get("/api/v1/returns/admin/all").status_code == 401
    assert db.get(OrderReturn, devolucion.id).status == ReturnStatus.REQUESTED


def test_solicitar_una_devolucion_exige_estar_logueado(client):
    respuesta = client.post(
        "/api/v1/returns/", json={"order_id": 1, "items": [{"order_item_id": 1, "quantity": 1}]}
    )

    assert respuesta.status_code == 401


def test_la_dueña_puede_resolverla_desde_la_api(admin_client, db, usuario, pedido_entregado):
    pedido = pedido_entregado()
    devolucion = return_service.request_return(
        db, order_id=pedido.id, user_id=usuario.id, items=[(_item(pedido, "Camiseta").id, 1)]
    )

    aprobada = admin_client.patch(f"/api/v1/returns/{devolucion.id}/approve", json={})
    assert aprobada.status_code == 200
    assert aprobada.json()["status"] == "APPROVED"

    recibida = admin_client.patch(
        f"/api/v1/returns/{devolucion.id}/received", json={"restock": True}
    )
    assert recibida.status_code == 200

    reembolsada = admin_client.patch(
        f"/api/v1/returns/{devolucion.id}/refund", json={"refund_reference": "tx-9"}
    )
    assert reembolsada.json()["status"] == "REFUNDED"
    assert reembolsada.json()["refund_amount"] == 50000.0

    # Reembolsar dos veces no puede devolver la plata dos veces.
    assert (
        admin_client.patch(f"/api/v1/returns/{devolucion.id}/refund", json={}).status_code
        == 409
    )


def test_una_devolucion_de_otra_persona_no_se_puede_ni_ver(
    client, db, usuario, crear_usuario, pedido_entregado
):
    pedido = pedido_entregado()
    devolucion = return_service.request_return(
        db, order_id=pedido.id, user_id=usuario.id, items=[(_item(pedido, "Camiseta").id, 1)]
    )
    intruso = crear_usuario(email="intruso@pruebas.olivosport.co")

    with pytest.raises(return_service.ReturnNotFoundError):
        return_service.get_return_or_raise(db, devolucion.id, user_id=intruso.id)
    with pytest.raises(return_service.ReturnNotFoundError):
        return_service.cancel_return(db, devolucion.id, intruso.id)
