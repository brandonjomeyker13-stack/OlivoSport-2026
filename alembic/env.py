"""Configuración de Alembic para OlivoSport.

La URL de la base NO se escribe en alembic.ini: se lee de
`settings.DATABASE_URL` (la misma variable que usa la app), para que
`alembic upgrade head` apunte siempre a la misma base que el backend,
tanto en local como en Render, y para no dejar credenciales en un
archivo versionado.

`target_metadata` apunta a `Base.metadata`: importar `app.db.base` trae
todos los modelos con él, que es lo que necesita `--autogenerate` para
ver las tablas nuevas.
"""

from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context
from app.core.config import settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Genera el SQL sin conectarse a la base (`alembic upgrade head --sql`)."""
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Sin esto, Alembic no detecta cambios de tipo ni de default en
        # una columna que ya existe (ej. Numeric(10,2) -> Numeric(12,2)).
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Corre las migraciones contra la base real."""
    # Se construye el engine a mano en vez de leer "sqlalchemy.url" del
    # .ini: ConfigParser interpreta los `%` como interpolación, y una
    # contraseña url-encoded (ej. `%40` por una @) rompería la conexión.
    connectable = create_engine(settings.DATABASE_URL, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
