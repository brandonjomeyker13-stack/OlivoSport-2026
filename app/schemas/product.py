from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProductBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    color: str = Field(..., min_length=2, max_length=50)
    size: str = Field(..., min_length=1, max_length=20)
    price: Decimal = Field(..., gt=0, decimal_places=2)
    stock: int = Field(default=0, ge=0)
    in_stock: bool = True


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    """Todos los campos opcionales: solo se actualiza lo que se envíe."""

    name: str | None = Field(default=None, min_length=2, max_length=150)
    color: str | None = Field(default=None, min_length=2, max_length=50)
    size: str | None = Field(default=None, min_length=1, max_length=20)
    price: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    stock: int | None = Field(default=None, ge=0)


class ProductRead(ProductBase):
    id: int
    image_url: str | None = None

    model_config = ConfigDict(from_attributes=True)