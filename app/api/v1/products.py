""" endpoints del producto"""
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin_user
from app.core.storage import delete_product_image_file, upload_product_image
from app.db.session import get_db
from app.models.product_image import ProductImage
from app.models.user import User
from app.schemas.product import ProductAdminRead, ProductCreate, ProductRead, ProductUpdate
from app.services import product_service

router = APIRouter()


@router.get("/", response_model=list[ProductRead])
def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    category_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return product_service.list_products(
        db, skip=skip, limit=limit, category_id=category_id
    )


@router.get("/{product_id}", response_model=ProductRead)
def get_product(product_id: int, db: Session = Depends(get_db)):
    try:
        return product_service.get_product_or_raise(db, product_id)
    except product_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{product_id}/admin", response_model=ProductAdminRead)
def get_product_admin(
    product_id: int,
    db: Session = Depends(get_db),
    is_admin: User = Depends(get_current_admin_user),
):
    """Igual que GET /{product_id}, pero solo-admin e incluye `cost` —
    para poder precargar el campo Costo en el formulario de edición."""
    try:
        return product_service.get_product_or_raise(db, product_id)
    except product_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/", response_model=ProductAdminRead, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    is_admin: User = Depends(get_current_admin_user),
):
    try:
        return product_service.create_product(
            db,
            name=payload.name,
            color=payload.color,
            size=payload.size,
            price=payload.price,
            stock=payload.stock,
            category_id=payload.category_id,
            cost=payload.cost,
        )
    except product_service.CategoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/{product_id}", response_model=ProductAdminRead)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    is_admin: User = Depends(get_current_admin_user),
):
    try:
        return product_service.update_product(
            db,
            product_id,
            name=payload.name,
            color=payload.color,
            size=payload.size,
            price=payload.price,
            stock=payload.stock,
            category_id=payload.category_id,
            cost=payload.cost,
        )
    except product_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except product_service.CategoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    is_admin: User = Depends(get_current_admin_user),
):
    try:
        product_service.delete_product(db, product_id)
    except product_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except product_service.ProductHasOrdersError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


def _borrar_del_bucket(imagenes: list[ProductImage]) -> None:
    for image in imagenes:
        if image.storage_path:
            delete_product_image_file(image.storage_path)


@router.post("/{product_id}/images", response_model=ProductAdminRead)
async def upload_images(
    product_id: int,
    files: list[UploadFile],
    db: Session = Depends(get_db),
    is_admin: User = Depends(get_current_admin_user),
):
    """Agrega imágenes a la galería del producto, hasta 4 en total.

    Ninguna es obligatoria: un producto puede quedarse sin imágenes. Se
    pueden mandar varias en el mismo request (campo `files` repetido).
    """
    try:
        product_service.get_product_or_raise(db, product_id)
    except product_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if len(files) > product_service.MAX_PRODUCT_IMAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Máximo {product_service.MAX_PRODUCT_IMAGES} imágenes por producto.",
        )

    subidas = [await upload_product_image(file, product_id) for file in files]

    try:
        return product_service.add_product_images(
            db, product_id, [(subida.url, subida.path) for subida in subidas]
        )
    except product_service.TooManyProductImagesError as exc:
        # Ya estaban en el bucket cuando se supo que no cabían: se limpian
        # para no dejar archivos que nadie referencia.
        for subida in subidas:
            delete_product_image_file(subida.path)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{product_id}/images/{image_id}", response_model=ProductAdminRead)
def delete_image(
    product_id: int,
    image_id: int,
    db: Session = Depends(get_db),
    is_admin: User = Depends(get_current_admin_user),
):
    """Quita una imagen. Las que quedan se corren un lugar, así que la
    siguiente pasa a ser la principal."""
    try:
        borrada = product_service.delete_product_image(db, product_id, image_id)
    except product_service.ProductImageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    _borrar_del_bucket([borrada])
    return product_service.get_product_or_raise(db, product_id)


@router.post("/{product_id}/image", response_model=ProductAdminRead, deprecated=True)
async def upload_image(
    product_id: int,
    file: UploadFile,
    db: Session = Depends(get_db),
    is_admin: User = Depends(get_current_admin_user),
):
    """Deja el producto con esta única imagen (reemplaza las que tuviera).

    Es el endpoint viejo de una sola imagen, se mantiene para no romper al
    frontend que ya lo llama. Para la galería usa POST /{id}/images.
    """
    try:
        product_service.get_product_or_raise(db, product_id)
    except product_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    subida = await upload_product_image(file, product_id)
    product, anteriores = product_service.replace_product_images(
        db, product_id, [(subida.url, subida.path)]
    )
    _borrar_del_bucket(anteriores)
    return product