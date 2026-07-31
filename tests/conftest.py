"""Infraestructura común de los tests.

Por defecto todo corre contra SQLite en memoria: los tests no necesitan
Postgres ni Docker, y cada test arranca con la base vacía. Si quieres
correrlos contra Postgres (para validar cosas propias del motor, como
`date_trunc` en los reportes), exporta `TEST_DATABASE_URL`:

    TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost/olivosport_test pytest

Las variables de entorno que necesita `app.core.config` las define
`pytest.ini`, así que importar la app desde acá es seguro.
"""

import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import DateTime, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator

from app.core.limiter import limiter
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main_app import app
from app.models.category import Category
from app.models.product import Product
from app.models.user import User

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")


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
