"""
Conexión a la base de datos: engine + sesiones.

`get_db` es la dependencia que usan todos los endpoints; abre una sesión
por request y la cierra al terminar, pase lo que pase:

    @router.get("/products")
    def list_products(db: Session = Depends(get_db)):
        ...
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()