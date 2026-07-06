"""
Punto de entrada local, solo para desarrollo.

- Ahora: crea las tablas directo con create_all (rápido para prototipar).
- Cuando tengas datos reales: usa Alembic en vez de esta función
  (ver README.md, sección "Migraciones").
- Cuando conectes FastAPI: la app vive en app/main.py (uvicorn app.main:app),
  este archivo NO se mezcla con ese.
"""

from app.db.base import init_db


def main() -> None:
    init_db()
    print("Base de datos inicializada y conectada.")


if __name__ == "__main__":
    main()