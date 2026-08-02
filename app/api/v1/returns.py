"""Devoluciones por derecho de retracto (Ley 1480 art. 47).

El cliente pide la devolución y la puede cancelar mientras no la respondan;
la dueña la aprueba o rechaza, marca cuándo llegó la mercancía y cuándo
devolvió la plata.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin_user, get_current_user
from app.db.session import get_db
from app.models.order_return import ReturnStatus
from app.models.user import User
from app.schemas.order_return import (
    ReturnCreate,
    ReturnRead,
    ReturnReceived,
    ReturnRefund,
    ReturnResolution,
)
from app.services import return_service

router = APIRouter()


@contextmanager
def _traducir_errores() -> Iterator[None]:
    """Las devoluciones que no existen y las que existen pero no admiten la
    acción pedida se traducen igual en todos los endpoints."""
    try:
        yield
    except return_service.ReturnNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except return_service.InvalidReturnTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/", response_model=ReturnRead, status_code=status.HTTP_201_CREATED)
def request_return(
    payload: ReturnCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """El cliente se retracta de parte (o todo) de un pedido ya entregado,
    dentro de los 5 días hábiles que da la ley. No tiene que justificarlo."""
    try:
        return return_service.request_return(
            db,
            order_id=payload.order_id,
            user_id=current_user.id,
            items=[(item.order_item_id, item.quantity) for item in payload.items],
            reason=payload.reason,
        )
    except return_service.ReturnNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except return_service.OrderNotReturnableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except return_service.InvalidReturnItemsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/", response_model=list[ReturnRead])
def list_my_returns(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return return_service.list_my_returns(db, current_user.id)


@router.get("/admin/all", response_model=list[ReturnRead])
def list_all_returns(
    skip: int = 0,
    limit: int = Query(default=100, le=300),
    return_status: ReturnStatus | None = Query(default=None, alias="status"),
    _admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    return return_service.list_all_returns(
        db, skip=skip, limit=limit, status=return_status
    )


@router.get("/{return_id}", response_model=ReturnRead)
def get_my_return(
    return_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _traducir_errores():
        return return_service.get_return_or_raise(db, return_id, user_id=current_user.id)


@router.patch("/{return_id}/cancel", response_model=ReturnRead)
def cancel_my_return(
    return_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """El cliente retira su solicitud, mientras la dueña no haya respondido."""
    with _traducir_errores():
        return return_service.cancel_return(db, return_id, current_user.id)


@router.patch("/{return_id}/approve", response_model=ReturnRead)
def approve_return(
    return_id: int,
    payload: ReturnResolution | None = None,
    _admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    with _traducir_errores():
        return return_service.approve_return(
            db, return_id, note=payload.note if payload else None
        )


@router.patch("/{return_id}/reject", response_model=ReturnRead)
def reject_return(
    return_id: int,
    payload: ReturnResolution,
    _admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """Rechazar exige explicarle al cliente por qué (dentro del plazo, el
    retracto es un derecho: negarlo debería ser excepcional)."""
    with _traducir_errores():
        return return_service.reject_return(db, return_id, note=payload.note or "")


@router.patch("/{return_id}/received", response_model=ReturnRead)
def mark_return_received(
    return_id: int,
    payload: ReturnReceived | None = None,
    _admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """La mercancía volvió. Si vino en condiciones de venderse otra vez,
    las unidades vuelven al stock acá (no antes)."""
    with _traducir_errores():
        return return_service.mark_received(
            db, return_id, restock=payload.restock if payload else True
        )


@router.patch("/{return_id}/refund", response_model=ReturnRead)
def mark_return_refunded(
    return_id: int,
    payload: ReturnRefund | None = None,
    _admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """Registra que ya se le devolvió la plata al cliente. El reembolso en
    sí se hace por fuera (Wompi o transferencia); esto guarda el
    comprobante y saca esos ítems de los reportes de ventas."""
    with _traducir_errores():
        return return_service.mark_refunded(
            db, return_id, refund_reference=payload.refund_reference if payload else None
        )
