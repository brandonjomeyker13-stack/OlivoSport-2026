from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.cart import CartItemCreate, CartItemRead, CartItemUpdate
from app.services import cart_service, product_service

router = APIRouter()


@router.get("/", response_model=list[CartItemRead])
def get_my_cart(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return cart_service.get_cart(db, user_id=current_user.id)


@router.post("/", response_model=CartItemRead, status_code=status.HTTP_201_CREATED)
def add_to_cart(
    payload: CartItemCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return cart_service.add_to_cart(
            db,
            user_id=current_user.id,
            product_id=payload.product_id,
            quantity=payload.quantity,
        )
    except product_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except cart_service.InsufficientStockError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.put("/{cart_item_id}", response_model=CartItemRead)
def update_cart_item(
    cart_item_id: int,
    payload: CartItemUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return cart_service.update_cart_item_quantity(
            db,
            user_id=current_user.id,
            cart_item_id=cart_item_id,
            quantity=payload.quantity,
        )
    except cart_service.CartItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except product_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except cart_service.InsufficientStockError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{cart_item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_from_cart(
    cart_item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        cart_service.remove_from_cart(db, user_id=current_user.id, cart_item_id=cart_item_id)
    except cart_service.CartItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc