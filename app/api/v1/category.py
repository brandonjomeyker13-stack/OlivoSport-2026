"""Categorías de productos. Solo el admin las crea; cualquiera las lista
(para armar el filtro del catálogo)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.category import CategoryCreate, CategoryRead
from app.services import category_service

router = APIRouter()


@router.get("/", response_model=list[CategoryRead])
def list_categories(db: Session = Depends(get_db)):
    return category_service.list_categories(db)


@router.post("/", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreate,
    _admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    try:
        return category_service.create_category(db, name=payload.name)
    except category_service.CategoryAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc