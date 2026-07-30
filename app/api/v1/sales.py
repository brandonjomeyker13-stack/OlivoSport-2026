"""Endpoints de reportes de ventas — TODO este router es solo-admin.
La protección está a nivel de router (dependencies=[...]) para que
ningún endpoint nuevo que se agregue acá quede sin proteger por olvido."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin_user
from app.db.session import get_db
from app.schemas.sales import SalesPeriod, SalesSummary
from app.services import sales_service

router = APIRouter(dependencies=[Depends(get_current_admin_user)])


@router.get("/total", response_model=SalesSummary)
def get_total_sales(db: Session = Depends(get_db)):
    """Ventas de TODO el historial (APPROVED, IN_TRANSIT,
    AWAITING_CONFIRMATION, DELIVERED)."""
    return sales_service.get_total_sales(db)


@router.get("/daily", response_model=list[SalesPeriod])
def get_daily_sales(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Sin date_from/date_to: últimos 30 días."""
    try:
        return sales_service.get_sales_by_period(db, "day", date_from, date_to)
    except sales_service.InvalidGranularityError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/weekly", response_model=list[SalesPeriod])
def get_weekly_sales(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return sales_service.get_sales_by_period(db, "week", date_from, date_to)


@router.get("/monthly", response_model=list[SalesPeriod])
def get_monthly_sales(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return sales_service.get_sales_by_period(db, "month", date_from, date_to)