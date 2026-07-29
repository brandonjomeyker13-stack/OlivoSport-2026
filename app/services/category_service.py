"""Reglas de negocio de Category."""

from sqlalchemy.orm import Session

from app.models.category import Category
from app.repositories import category_repository


class CategoryAlreadyExistsError(Exception):
    pass


class CategoryNotFoundError(Exception):
    pass


def create_category(db: Session, *, name: str) -> Category:
    name = name.strip()
    if category_repository.get_by_name(db, name) is not None:
        raise CategoryAlreadyExistsError(f"Ya existe una categoría llamada '{name}'.")
    return category_repository.create(db, name=name)


def list_categories(db: Session) -> list[Category]:
    return category_repository.list_all(db)


def get_category_or_raise(db: Session, category_id: int) -> Category:
    category = category_repository.get_by_id(db, category_id)
    if category is None:
        raise CategoryNotFoundError(f"Categoría {category_id} no encontrada.")
    return category