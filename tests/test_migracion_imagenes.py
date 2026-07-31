"""La migración de la galería no puede perder las imágenes ya cargadas.

Es el único test que corre las migraciones de verdad (las demás pruebas
crean las tablas con `create_all`), porque lo que se está probando es el
traspaso de datos de `products.image_url` a `product_images`. Necesita un
Postgres desechable —la migración lo deja en otro estado— así que solo
corre si se le pasa `MIGRATION_TEST_DATABASE_URL`; en CI se le da la base
del job de migraciones.
"""

import os

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command

MIGRATION_DATABASE_URL = os.getenv("MIGRATION_TEST_DATABASE_URL")

ANTES_DE_LA_GALERIA = "f627c998be66"
GALERIA = "a2374800a354"

URL_DE_UNA_IMAGEN_YA_SUBIDA = (
    "https://proyecto.supabase.co/storage/v1/object/public/"
    "product-images/product-7-9f8e7d.png"
)

pytestmark = pytest.mark.skipif(
    not MIGRATION_DATABASE_URL,
    reason="Necesita MIGRATION_TEST_DATABASE_URL: la migración modifica la base.",
)


@pytest.fixture
def alembic_config(monkeypatch) -> Config:
    # settings ya está construido con la URL de pytest.ini, y alembic/env.py
    # lee de ahí: se apunta a la base desechable para no tocar ninguna otra.
    from app.core.config import settings

    monkeypatch.setattr(settings, "DATABASE_URL", MIGRATION_DATABASE_URL)
    return Config("alembic.ini")


@pytest.fixture
def base_limpia(alembic_config):
    engine = create_engine(MIGRATION_DATABASE_URL)
    command.downgrade(alembic_config, "base")
    yield engine
    command.downgrade(alembic_config, "base")
    engine.dispose()


def _crear_producto_con_imagen(engine, image_url: str | None) -> int:
    with engine.begin() as conexion:
        category_id = conexion.execute(
            text("INSERT INTO categories (name) VALUES ('Camisetas') RETURNING id")
        ).scalar_one()
        return conexion.execute(
            text(
                "INSERT INTO products "
                "(name, color, size, price, stock, in_stock, category_id, image_url) "
                "VALUES ('Camiseta', 'negro', 'M', 50000, 5, true, :category_id, :image_url) "
                "RETURNING id"
            ),
            {"category_id": category_id, "image_url": image_url},
        ).scalar_one()


def test_la_imagen_ya_subida_pasa_a_la_galeria(alembic_config, base_limpia):
    command.upgrade(alembic_config, ANTES_DE_LA_GALERIA)
    product_id = _crear_producto_con_imagen(base_limpia, URL_DE_UNA_IMAGEN_YA_SUBIDA)

    command.upgrade(alembic_config, GALERIA)

    with base_limpia.connect() as conexion:
        fila = conexion.execute(
            text(
                "SELECT image_url, storage_path, position FROM product_images "
                "WHERE product_id = :product_id"
            ),
            {"product_id": product_id},
        ).one()

    assert fila.image_url == URL_DE_UNA_IMAGEN_YA_SUBIDA
    assert fila.position == 0
    # El nombre del archivo se saca de la URL para poder borrarlo del
    # bucket más adelante.
    assert fila.storage_path == "product-7-9f8e7d.png"


def test_un_producto_sin_imagen_no_estorba(alembic_config, base_limpia):
    command.upgrade(alembic_config, ANTES_DE_LA_GALERIA)
    product_id = _crear_producto_con_imagen(base_limpia, None)

    command.upgrade(alembic_config, GALERIA)

    with base_limpia.connect() as conexion:
        assert (
            conexion.execute(
                text(
                    "SELECT count(*) FROM product_images WHERE product_id = :product_id"
                ),
                {"product_id": product_id},
            ).scalar_one()
            == 0
        )


def test_al_revertir_la_imagen_principal_vuelve_a_la_columna(alembic_config, base_limpia):
    command.upgrade(alembic_config, ANTES_DE_LA_GALERIA)
    product_id = _crear_producto_con_imagen(base_limpia, URL_DE_UNA_IMAGEN_YA_SUBIDA)
    command.upgrade(alembic_config, GALERIA)

    command.downgrade(alembic_config, ANTES_DE_LA_GALERIA)

    with base_limpia.connect() as conexion:
        image_url = conexion.execute(
            text("SELECT image_url FROM products WHERE id = :product_id"),
            {"product_id": product_id},
        ).scalar_one()

    assert image_url == URL_DE_UNA_IMAGEN_YA_SUBIDA
