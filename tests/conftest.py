"""Infraestructura común de los tests.

Por defecto todo corre contra SQLite en memoria: los tests no necesitan
Postgres ni Docker, y cada test arranca con la base vacía. Si quieres
correrlos contra Postgres (para validar cosas propias del motor, como
`date_trunc` en los reportes), exporta `TEST_DATABASE_URL`:

    TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost/olivosport_test pytest

Las variables de entorno que necesita `app.core.config` las define
`pytest.ini`, así que importar la app desde acá es seguro.
"""

import hashlib
import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import DateTime, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator

from app.api.deps import get_current_admin_user
from app.core.config import settings
from app.core.limiter import limiter
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main_app import app
from app.models.category import Category
from app.models.order import Order
from app.models.product import Product
from app.models.user import User
from app.repositories import cart_repository
from app.services import order_service

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")

# Lo que Wompi firma de cada transacción. OJO: la `reference` NO está acá.
PROPIEDADES_FIRMADAS = ["transaction.id", "transaction.status", "transaction.amount_in_cents"]


class _DateTimeConZonaHoraria(TypeDecorator):
    """SQLite no guarda la zona horaria: devuelve datetimes "naive" aunque
    la columna sea `DateTime(timezone=True)`, y comparar eso contra un
    `datetime.now(timezone.utc)` revienta con TypeError. Postgres (lo que
    corre en producción) sí devuelve el offset, así que esto solo empareja
    a SQLite con el motor real: los valores ya se guardan en UTC.
    """

    impl = DateTime
    cache_ok = True

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


def _emparejar_datetimes_con_postgres() -> None:
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, DateTime) and column.type.timezone:
                column.type = _DateTimeConZonaHoraria(timezone=True)


@pytest.fixture
def engine():
    if TEST_DATABASE_URL.startswith("sqlite"):
        _emparejar_datetimes_con_postgres()
        # StaticPool + una sola conexión: si no, cada sesión abriría su
        # propia base en memoria y no vería las tablas de la anterior.
        engine = create_engine(
            TEST_DATABASE_URL,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(TEST_DATABASE_URL)

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db(engine):
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    """TestClient que comparte la MISMA sesión que el fixture `db`, para
    poder revisar en la base lo que dejó una request."""
    app.dependency_overrides[get_db] = lambda: db
    # slowapi cuenta en memoria y no se reinicia entre tests: sin esto, el
    # límite de 5/minuto de /register haría fallar tests según el orden en
    # que corran, no según lo que prueban.
    limiter.enabled = False
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        limiter.enabled = True
        app.dependency_overrides.clear()


@pytest.fixture
def admin_client(client, db):
    """Como `client`, pero saltándose el login del admin.

    Solo reemplaza QUIÉN es el usuario, no el `Depends(get_current_admin_user)`
    de cada endpoint: si alguien le quita esa dependencia a una ruta de
    admin, los tests que dependen de ella igual la seguirían pegando sin
    token y no avisarían. Por eso los tests de "esto es solo para el
    admin" usan el `client` normal.
    """
    admin = User(
        name="Admin de prueba",
        email="admin@pruebas.olivosport.co",
        password_hash=hash_password("password-de-prueba"),
        is_active=True,
        is_admin=True,
        accepted_terms=True,
    )
    db.add(admin)
    db.commit()

    app.dependency_overrides[get_current_admin_user] = lambda: admin
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_current_admin_user, None)


@pytest.fixture
def categoria(db) -> Category:
    category = Category(name="Camisetas")
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@pytest.fixture
def crear_producto(db, categoria):
    def _crear_producto(
        *,
        nombre: str = "Camiseta deportiva",
        stock: int = 10,
        precio: str = "50000.00",
        costo: str = "30000.00",
    ) -> Product:
        product = Product(
            name=nombre,
            color="negro",
            size="M",
            price=Decimal(precio),
            cost=Decimal(costo),
            stock=stock,
            in_stock=stock > 0,
            category_id=categoria.id,
        )
        db.add(product)
        db.commit()
        db.refresh(product)
        return product

    return _crear_producto


@pytest.fixture
def crear_usuario(db):
    def _crear_usuario(
        *,
        email: str = "cliente@pruebas.olivosport.co",
        password: str | None = "password-de-prueba",
        is_active: bool = True,
    ) -> User:
        user = User(
            name="Cliente de prueba",
            email=email,
            password_hash=hash_password(password) if password else None,
            is_active=is_active,
            accepted_terms=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    return _crear_usuario


@pytest.fixture
def usuario(crear_usuario) -> User:
    return crear_usuario()


@pytest.fixture
def pedido_pendiente(db):
    """Deja un pedido PENDING (con su stock ya reservado) listo para
    simularle eventos de Wompi."""

    def _pedido_pendiente(usuario: User, producto: Product, cantidad: int = 2) -> Order:
        cart_repository.create(
            db, user_id=usuario.id, product_id=producto.id, quantity=cantidad
        )
        return order_service.create_order_from_cart(db, user_id=usuario.id)

    return _pedido_pendiente


@pytest.fixture
def evento_wompi():
    """Arma un evento `transaction.updated` con checksum válido (o con uno
    inválido, si le pasas otro `secret`). Por defecto cobra exactamente lo
    que vale el pedido, que es lo que hace Wompi.

    El checksum se calcula acá a mano a propósito: si se armara llamando a
    `verify_event_signature`, los tests de firma no probarían nada.
    """

    def _evento_wompi(
        *,
        pedido: Order | None = None,
        reference: str | None = None,
        status: str,
        transaction_id: str = "12345-1699999999-99999",
        amount_in_cents: int | None = None,
        currency: str | None = None,
        timestamp: int = 1699999999,
        secret: str | None = None,
    ) -> dict:
        if pedido is not None:
            reference = reference or pedido.reference
            if amount_in_cents is None:
                amount_in_cents = order_service.to_cents(pedido.total_amount)

        transaction = {
            "id": transaction_id,
            "status": status,
            "reference": reference,
            "amount_in_cents": amount_in_cents,
            "currency": currency or settings.WOMPI_CURRENCY,
        }
        concatenado = "".join(
            str(transaction[prop.split(".")[1]]) for prop in PROPIEDADES_FIRMADAS
        )
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

    return _evento_wompi
