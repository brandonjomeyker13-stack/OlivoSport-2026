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


class UserRead(UserBase):
    id: int
    is_active: bool
    is_admin: bool
    accepted_terms: bool

    model_config = ConfigDict(from_attributes=True)