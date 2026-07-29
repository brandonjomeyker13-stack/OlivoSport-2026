from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr


class UserCreate(UserBase):
    password: str = Field(..., min_length=8)
    # Debe ser explícitamente True: no hay valor por defecto, así el
    # frontend está obligado a mandar una casilla marcada por el usuario
    # (no premarcada), como exige la ley de Habeas Data en Colombia.
    accepted_terms: bool = Field(...)

    @field_validator("accepted_terms")
    @classmethod
    def must_accept_terms(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "Debes aceptar los Términos y Condiciones y la Política de "
                "Tratamiento de Datos para registrarte."
            )
        return value


class GoogleAuthRequest(BaseModel):
    id_token: str
    # Solo se exige (y se valida en el service) si es un usuario NUEVO.
    # Para un login de alguien que ya existe, este valor se ignora.
    accepted_terms: bool = False
    # Opcional: si viene, se guarda como contraseña de respaldo SOLO
    # cuando se está creando la cuenta por primera vez (se pide una única
    # vez en el flujo de registro con Google). En logins posteriores o en
    # cuentas ya existentes, este valor se ignora.
    password: str | None = Field(default=None, min_length=8)


class GoogleLinkRequest(BaseModel):
    id_token: str


class SetPasswordRequest(BaseModel):
    # Solo se exige (y se valida en el service) si el usuario YA tiene
    # una contraseña — para cambiarla hay que probar que sabes la actual.
    # Si el usuario todavía no tiene ninguna (cuenta creada solo con
    # Google), este campo se ignora.
    current_password: str | None = None
    new_password: str = Field(..., min_length=8)


class UserRead(UserBase):
    id: int
    address: str | None = None
    city: str | None = None
    is_active: bool
    is_admin: bool
    accepted_terms: bool

    model_config = ConfigDict(from_attributes=True)