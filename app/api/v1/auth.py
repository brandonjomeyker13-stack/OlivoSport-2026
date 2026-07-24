from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.limiter import limiter
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserRead
from app.services import user_service

router = APIRouter()


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register(request: Request, payload: UserCreate, db: Session = Depends(get_db)):
    try:
        return user_service.register_user(
            db,
            name=payload.name,
            email=payload.email,
            password=payload.password,
            accepted_terms=payload.accepted_terms,
        )
    except user_service.EmailAlreadyRegisteredError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/login")
@limiter.limit("10/minute")
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    # OAuth2PasswordRequestForm expone el email como "username".
    try:
        user = user_service.authenticate(db, email=form_data.username, password=form_data.password)
    except user_service.InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    token = create_access_token(subject=str(user.id))
    return {"access_token": token, "token_type": "bearer"}


# Endpoints de datos personales: acceso, rectificación y supresión.


@router.get("/me", response_model=UserRead)
def get_my_profile(current_user: User = Depends(get_current_user)):
    """Derecho de acceso: el usuario puede ver qué datos tenemos de él."""
    return current_user


class UserUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=100)
    email: EmailStr | None = None


@router.patch("/me", response_model=UserRead)
def update_my_profile(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Derecho de rectificación: el usuario puede corregir sus datos."""
    try:
        return user_service.update_profile(
            db, user=current_user, name=payload.name, email=payload.email
        )
    except user_service.EmailAlreadyRegisteredError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_account(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Derecho de supresión: el usuario puede pedir que borremos su cuenta.
    Los ítems de carrito se borran en cascada (ver relationship en User)."""
    user_service.delete_account(db, user=current_user)