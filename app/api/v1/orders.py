from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin_user, get_current_user
from app.core.limiter import limiter
from app.db.session import get_db
from app.models.order import OrderStatus
from app.models.user import User
from app.schemas.order import CheckoutResponse, OrderRead, OrderStatusUpdate
from app.services import order_service

router = APIRouter()


@router.post("/checkout", response_model=CheckoutResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
def checkout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
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


@router.post("/{order_id}/pay", response_model=CheckoutResponse)
@limiter.limit("5/minute")
def pay_existing_order(
    request: Request,
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Botón "Pagar" en un pedido ya creado (PENDING, o reintentar uno
    DECLINED/ERROR). Devuelve lo que el frontend necesita para abrir el
    Widget de Wompi, con una referencia nueva (Wompi no deja reusar la
    de un intento anterior)."""
    try:
        return order_service.get_checkout_payload_for_order(db, order_id, current_user.id)
    except order_service.OrderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except order_service.InvalidStatusTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except order_service.InsufficientStockError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except order_service.WompiNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@router.get("/", response_model=list[OrderRead])
def list_my_orders(
    stage: str | None = Query(default=None, pattern="^(active|completed)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """?stage=active -> PENDING/APPROVED/IN_TRANSIT/AWAITING_CONFIRMATION
    ?stage=completed -> DELIVERED/CANCELLED/EXPIRED/DECLINED/VOIDED/ERROR
    Sin `stage`, devuelve todos (como antes)."""
    return order_service.list_my_orders(db, current_user.id, stage=stage)


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
    limit: int = Query(default=100, le=300),
    order_status: OrderStatus | None = Query(default=None, alias="status"),
    _admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    return order_service.list_all_orders(db, skip=skip, limit=limit, status=order_status)


@router.patch("/{order_id}/cancel", response_model=OrderRead)
def cancel_my_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """El cliente cancela su propio pedido mientras siga PENDING (antes de
    pagar). Libera el stock que se había reservado al crearlo."""
    try:
        return order_service.cancel_order(db, order_id, current_user.id)
    except order_service.OrderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except order_service.InvalidStatusTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/{order_id}/confirm-delivery", response_model=OrderRead)
def confirm_order_delivery(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """El CLIENTE confirma que ya recibió su pedido (solo el dueño del
    pedido puede hacerlo). Si no confirma en 5 días, se autoconfirma solo."""
    try:
        return order_service.confirm_delivery(db, order_id, current_user.id)
    except order_service.OrderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except order_service.InvalidStatusTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/{order_id}/status", response_model=OrderRead)
def update_order_delivery_status(
    order_id: int,
    payload: OrderStatusUpdate,
    _admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """Panel de la dueña: marca un pedido como IN_TRANSIT o DELIVERED.
    Las transiciones inválidas (ej. saltar de PENDING a DELIVERED) las
    rechaza order_service con 409."""
    try:
        return order_service.update_delivery_status(db, order_id, payload.status)
    except order_service.OrderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except order_service.InvalidStatusTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc