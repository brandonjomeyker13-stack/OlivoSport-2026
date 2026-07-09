from pydantic import BaseModel, ConfigDict, Field


class CartItemBase(BaseModel):
    product_id: int
    quantity: int = Field(..., gt=0)


class CartItemCreate(CartItemBase):
    """user_id NO va aquí: en la API vendrá del usuario autenticado
    (token), nunca del body que manda el cliente."""


class CartItemRead(CartItemBase):
    id: int
    user_id: int

    model_config = ConfigDict(from_attributes=True)
    
class CartItemUpdate(BaseModel):
    quantity: int = Field(..., gt=0)