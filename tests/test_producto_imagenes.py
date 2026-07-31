"""Galería de imágenes del producto: hasta 4, todas opcionales, y solo el
admin puede tocarlas."""

import io

import pytest

from app.api.v1 import products as products_api
from app.core.storage import UploadedImage
from app.services import product_service

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture(autouse=True)
def supabase_falso(monkeypatch):
    """Los tests no hablan con Supabase: se simula la subida y se anota
    qué archivos se mandaron a borrar del bucket."""
    borrados: list[str] = []
    subidas: list[str] = []

    async def _subir(file, product_id: int) -> UploadedImage:
        await file.read()
        path = f"product-{product_id}-{len(subidas)}.png"
        subidas.append(path)
        return UploadedImage(
            url=f"https://supabase.test/storage/v1/object/public/product-images/{path}",
            path=path,
        )

    monkeypatch.setattr(products_api, "upload_product_image", _subir)
    monkeypatch.setattr(products_api, "delete_product_image_file", borrados.append)
    return borrados


def _archivos(cantidad: int) -> list[tuple[str, tuple[str, io.BytesIO, str]]]:
    return [
        ("files", (f"foto-{i}.png", io.BytesIO(PNG), "image/png")) for i in range(cantidad)
    ]


def subir(client, product_id: int, cantidad: int = 1):
    return client.post(f"/api/v1/products/{product_id}/images", files=_archivos(cantidad))


def test_un_producto_sin_imagenes_es_valido(client, crear_producto):
    """Ninguna imagen es obligatoria: el producto se lista igual."""
    producto = crear_producto()

    respuesta = client.get(f"/api/v1/products/{producto.id}")

    assert respuesta.status_code == 200
    assert respuesta.json()["images"] == []
    assert respuesta.json()["image_url"] is None


def test_se_pueden_subir_varias_imagenes_de_una(admin_client, crear_producto):
    producto = crear_producto()

    respuesta = subir(admin_client, producto.id, cantidad=3)

    assert respuesta.status_code == 200
    imagenes = respuesta.json()["images"]
    assert [imagen["position"] for imagen in imagenes] == [0, 1, 2]
    # La principal es la primera de la galería, no una URL aparte.
    assert respuesta.json()["image_url"] == imagenes[0]["image_url"]


def test_las_imagenes_se_van_acumulando_hasta_4(admin_client, crear_producto):
    producto = crear_producto()

    subir(admin_client, producto.id, cantidad=2)
    respuesta = subir(admin_client, producto.id, cantidad=2)

    assert respuesta.status_code == 200
    assert len(respuesta.json()["images"]) == product_service.MAX_PRODUCT_IMAGES


def test_la_quinta_imagen_se_rechaza_y_no_queda_basura_en_el_bucket(
    admin_client, crear_producto, supabase_falso
):
    producto = crear_producto()
    subir(admin_client, producto.id, cantidad=4)

    respuesta = subir(admin_client, producto.id)

    assert respuesta.status_code == 409
    assert "4" in respuesta.json()["detail"]
    # La imagen ya estaba subida cuando se supo que no cabía: se borra
    # para no dejar un archivo que nadie referencia.
    assert supabase_falso == ["product-1-4.png"]
    assert len(admin_client.get(f"/api/v1/products/{producto.id}").json()["images"]) == 4


def test_mandar_mas_de_4_en_un_solo_request_se_rechaza(admin_client, crear_producto):
    producto = crear_producto()

    respuesta = subir(admin_client, producto.id, cantidad=5)

    assert respuesta.status_code == 400
    assert admin_client.get(f"/api/v1/products/{producto.id}").json()["images"] == []


def test_borrar_una_imagen_corre_las_demas_y_libera_el_archivo(
    admin_client, crear_producto, supabase_falso
):
    producto = crear_producto()
    imagenes = subir(admin_client, producto.id, cantidad=3).json()["images"]

    respuesta = admin_client.delete(
        f"/api/v1/products/{producto.id}/images/{imagenes[0]['id']}"
    )

    assert respuesta.status_code == 200
    quedan = respuesta.json()["images"]
    assert [imagen["id"] for imagen in quedan] == [imagenes[1]["id"], imagenes[2]["id"]]
    # Sin huecos: la que era segunda ahora es la principal.
    assert [imagen["position"] for imagen in quedan] == [0, 1]
    assert respuesta.json()["image_url"] == imagenes[1]["image_url"]
    assert supabase_falso == ["product-1-0.png"]


def test_despues_de_borrar_se_puede_volver_a_llenar_hasta_4(admin_client, crear_producto):
    """Renumerar no es cosmético: si quedaran huecos en las posiciones, la
    siguiente subida chocaría contra la constraint (product_id, position)."""
    producto = crear_producto()
    imagenes = subir(admin_client, producto.id, cantidad=4).json()["images"]
    admin_client.delete(f"/api/v1/products/{producto.id}/images/{imagenes[1]['id']}")

    respuesta = subir(admin_client, producto.id)

    assert respuesta.status_code == 200
    assert [imagen["position"] for imagen in respuesta.json()["images"]] == [0, 1, 2, 3]


def test_no_se_puede_borrar_una_imagen_de_otro_producto(admin_client, crear_producto):
    producto = crear_producto()
    otro = crear_producto(nombre="Otra camiseta")
    imagen = subir(admin_client, producto.id).json()["images"][0]

    respuesta = admin_client.delete(f"/api/v1/products/{otro.id}/images/{imagen['id']}")

    assert respuesta.status_code == 404
    assert len(admin_client.get(f"/api/v1/products/{producto.id}").json()["images"]) == 1


def test_borrar_el_producto_se_lleva_sus_imagenes(admin_client, db, crear_producto):
    from app.repositories import product_image_repository

    producto = crear_producto()
    subir(admin_client, producto.id, cantidad=2)

    assert admin_client.delete(f"/api/v1/products/{producto.id}").status_code == 204
    assert product_image_repository.list_by_product(db, producto.id) == []


def test_el_endpoint_viejo_de_una_imagen_reemplaza_la_galeria(
    admin_client, crear_producto, supabase_falso
):
    """El frontend que ya existe llama a POST /{id}/image esperando que el
    producto quede con esa imagen, no con una más."""
    producto = crear_producto()
    subir(admin_client, producto.id, cantidad=3)

    respuesta = admin_client.post(
        f"/api/v1/products/{producto.id}/image",
        files={"file": ("foto.png", io.BytesIO(PNG), "image/png")},
    )

    assert respuesta.status_code == 200
    assert len(respuesta.json()["images"]) == 1
    assert supabase_falso == ["product-1-0.png", "product-1-1.png", "product-1-2.png"]


def test_subir_imagenes_es_solo_para_el_admin(client, crear_producto):
    producto = crear_producto()

    assert subir(client, producto.id).status_code == 401
    assert client.delete(f"/api/v1/products/{producto.id}/images/1").status_code == 401


def test_subir_a_un_producto_que_no_existe_da_404(admin_client):
    assert subir(admin_client, 999).status_code == 404
