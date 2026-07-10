"""
Base declarativa única para todos los modelos.

IMPORTANTE: este archivo importa todos los modelos SOLO para que Alembic
los "vea" al hacer autogenerate de migraciones. Los modelos en sí importan
`Base` desde aquí, nunca al revés.
"""

from sqlalchemy.orm import declarative_base

Base = declarative_base()

# Import al final para evitar import circular: los modelos importan `Base`
# de este mismo módulo.
from app.models.user import User  # noqa: E402,F401
from app.models.product import Product  # noqa: E402,F401
from app.models.cart import CartItem  # noqa: E402,F401
from app.models.order_models import Order, OrderItem  # noqa: E402,F401


def init_db() -> None:
    """Crea las tablas si no existen. Útil solo para desarrollo local.

    En producción usa Alembic (ver README) en vez de esta función.
    """
    from app.db.session import engine

    Base.metadata.create_all(bind=engine)