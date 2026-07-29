from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.category import CategoryRead


class ProductBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    color: str = Field(..., min_length=2, max_length=50)
    size: str = Field(..., min_length=1, max_length=20)
    price: Decimal = Field(..., gt=0, decimal_places=2)
    stock: int = Field(default=0, ge=0)
    in_stock: bool = True


class ProductCreate(ProductBase):
    # Obligatoria: no tiene default, el admin SIEMPRE debe indicar a qué
    # categoría (ya existente) pertenece el producto.
    category_id: int = Field(...)


class ProductUpdate(BaseModel):
    """Todos los campos opcionales: solo se actualiza lo que se envíe."""

    name: str | None = Field(default=None, min_length=2, max_length=150)
    color: str | None = Field(default=None, min_length=2, max_length=50)
    size: str | None = Field(default=None, min_length=1, max_length=20)
    price: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    stock: int | None = Field(default=None, ge=0)
    category_id: int | None = Field(default=None)


class ProductRead(ProductBase):
    id: int
    image_url: str | None = None
    category: CategoryRead

    model_config = ConfigDict(from_attributes=True)