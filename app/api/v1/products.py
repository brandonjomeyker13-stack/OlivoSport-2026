from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin_user
from app.core.storage import upload_product_image
from app.db.session import get_db
from app.models.user import User
from app.schemas.product import ProductCreate, ProductRead, ProductUpdate
from app.services import product_service

router = APIRouter()


@router.get("/", response_model=list[ProductRead])
def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
):
    from app.repositories import product_repository

    return product_repository.list_all(db, skip=skip, limit=limit)


@router.get("/{product_id}", response_model=ProductRead)
def get_product(product_id: int, db: Session = Depends(get_db)):
    try:
        return product_service.get_product_or_raise(db, product_id)
    except product_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    return product_service.create_product(
        db,
        name=payload.name,
        color=payload.color,
        size=payload.size,
        price=payload.price,
        stock=payload.stock,
    )


@router.put("/{product_id}", response_model=ProductRead)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    try:
        return product_service.update_product(
            db,
            product_id,
            name=payload.name,
            color=payload.color,
            size=payload.size,
            price=payload.price,
            stock=payload.stock,
        )
    except product_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    try:
        product_service.delete_product(db, product_id)
    except product_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{product_id}/image", response_model=ProductRead)
async def upload_image(
    product_id: int,
    file: UploadFile,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    # Confirma que el producto existe antes de gastar tiempo subiendo el archivo.
    try:
        product_service.get_product_or_raise(db, product_id)
    except product_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    image_url = await upload_product_image(file, product_id)
    return product_service.set_product_image(db, product_id, image_url)