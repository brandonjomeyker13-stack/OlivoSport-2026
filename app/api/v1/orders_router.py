from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin_user, get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.order import CheckoutResponse, OrderRead
from app.services import order_service

router = APIRouter()


@router.post("/checkout", response_model=CheckoutResponse, status_code=status.HTTP_201_CREATED)
def checkout(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Congela el carrito en un pedido y devuelve lo que el frontend
    necesita para abrir el Widget de Wompi."""
    try:
        order = order_service.create_order_from_cart(db, user_id=current_user.id)
        return order_service.build_checkout_payload(order)
    except order_service.EmptyCartError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except order_service.InsufficientStockError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except order_service.WompiNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@router.get("/", response_model=list[OrderRead])
def list_my_orders(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return order_service.list_my_orders(db, current_user.id)


@router.get("/{order_id}", response_model=OrderRead)
def get_my_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return order_service.get_order_or_raise(db, order_id, user_id=current_user.id)
    except order_service.OrderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/admin/all", response_model=list[OrderRead])
def list_all_orders_admin(
    skip: int = 0,
    limit: int = 100,
    _admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    return order_service.list_all_orders(db, skip=skip, limit=limit)