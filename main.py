"""
Atajo para crear las tablas en una base local vacía. NO levanta la API.

    python main.py            # crea las tablas con create_all
    uvicorn app.main_app:app  # eso sí levanta la API (ver app/main_app.py)

En una base con datos reales (producción) NO se usa esto: el esquema se
maneja con Alembic (`alembic upgrade head`), que sí deja historial de
cambios. Ver README.md.
"""

from app.db.base import init_db


def main() -> None:
    init_db()
    print("Base de datos inicializada y conectada.")


if __name__ == "__main__":
    main()