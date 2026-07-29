"""Acceso a datos de Category. Solo queries, sin reglas de negocio."""

from sqlalchemy.orm import Session

from app.models.category import Category


def get_by_id(db: Session, category_id: int) -> Category | None:
    return db.query(Category).filter(Category.id == category_id).first()


def get_by_name(db: Session, name: str) -> Category | None:
    return db.query(Category).filter(Category.name == name).first()


def list_all(db: Session) -> list[Category]:
    return db.query(Category).order_by(Category.name).all()


def create(db: Session, *, name: str) -> Category:
    category = Category(name=name)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category