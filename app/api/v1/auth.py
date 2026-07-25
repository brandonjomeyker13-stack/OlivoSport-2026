from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.cookies import refresh_cookie_kwargs
from app.core.google_oauth import InvalidGoogleTokenError, verify_google_id_token
from app.core.limiter import limiter
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import GoogleAuthRequest, GoogleLinkRequest, UserCreate, UserRead
from app.services import auth_service, user_service

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
    response: Response,
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

    access_token, raw_refresh, max_age = auth_service.issue_tokens(db, user_id=user.id)

    # El refresh token va SOLO en cookie httpOnly — el frontend nunca lo
    # toca ni lo puede leer con JS. El access_token sí va en el body: la
    # idea es que el frontend lo guarde en memoria (variable/estado de la
    # app), NUNCA en localStorage/sessionStorage.
    response.set_cookie(value=raw_refresh, **refresh_cookie_kwargs(max_age_seconds=max_age))
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/google")
@limiter.limit("10/minute")
def login_with_google(
    request: Request,
    response: Response,
    payload: GoogleAuthRequest,
    db: Session = Depends(get_db),
):
    """Login (o registro, si el email no existe todavía) con Google.
    El frontend obtiene el id_token con Google Identity Services y lo
    manda acá — este endpoint NUNCA confía en un email mandado suelto."""
    try:
        claims = verify_google_id_token(payload.id_token)
    except InvalidGoogleTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    email = claims["email"]
    google_id = claims["sub"]
    name = claims.get("name") or email.split("@")[0]

    try:
        user = user_service.authenticate_google(
            db,
            email=email,
            google_id=google_id,
            name=name,
            accepted_terms=payload.accepted_terms,
            password=payload.password,
        )
    except user_service.GoogleAccountConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except user_service.TermsNotAcceptedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except user_service.InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    access_token, raw_refresh, max_age = auth_service.issue_tokens(db, user_id=user.id)
    response.set_cookie(value=raw_refresh, **refresh_cookie_kwargs(max_age_seconds=max_age))
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/google/link", response_model=UserRead)
def link_google_account(
    payload: GoogleLinkRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Para un usuario YA logueado (con contraseña) que quiere poder
    entrar también con Google. Requiere que el email de la cuenta de
    Google sea exactamente el mismo que el de su perfil."""
    try:
        claims = verify_google_id_token(payload.id_token)
    except InvalidGoogleTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    try:
        return user_service.link_google_account(
            db, user=current_user, email=claims["email"], google_id=claims["sub"]
        )
    except user_service.GoogleAccountConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/refresh")
@limiter.limit("30/minute")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    """El frontend llama esto al cargar la app (o cuando un request le
    devuelve 401) para conseguir un access_token nuevo sin pedirle la
    contraseña de nuevo al usuario."""
    raw_refresh = request.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
    if not raw_refresh:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No hay sesión activa."
        )

    try:
        access_token, new_raw_refresh, max_age = auth_service.rotate_refresh_token(
            db, raw_refresh
        )
    except auth_service.InvalidRefreshTokenError as exc:
        # Cookie inválida/reusada: la borramos del navegador para no
        # dejarla dando vueltas.
        response.delete_cookie(
            key=settings.REFRESH_TOKEN_COOKIE_NAME, path="/api/v1/auth"
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    response.set_cookie(
        value=new_raw_refresh, **refresh_cookie_kwargs(max_age_seconds=max_age)
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    raw_refresh = request.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
    if raw_refresh:
        auth_service.revoke_refresh_token(db, raw_refresh)
    response.delete_cookie(key=settings.REFRESH_TOKEN_COOKIE_NAME, path="/api/v1/auth")


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