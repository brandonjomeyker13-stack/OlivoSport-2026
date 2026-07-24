"""
Subida de archivos a Supabase Storage.

Requiere que en el .env SUPABASE_URL y SUPABASE_KEY estén configurados,
y que SUPABASE_KEY sea la clave "service_role" (no la "anon"), porque
solo el service_role puede subir archivos sin pasar por las políticas
de acceso del bucket.
"""

import uuid

from fastapi import HTTPException, UploadFile, status
from supabase import create_client

from app.core.config import settings

BUCKET_NAME = "product-images"

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


def _get_client():
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SUPABASE_URL / SUPABASE_KEY no están configurados en el .env.",
        )
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


async def upload_product_image(file: UploadFile, product_id: int) -> str:
    """Sube la imagen y devuelve la URL pública para guardar en products.image_url."""

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se permiten imágenes JPG, PNG o WEBP.",
        )

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La imagen no puede pesar más de 5 MB.",
        )

    extension = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
    # Nombre único por producto para evitar sobrescribir el archivo anterior.
    path = f"product-{product_id}-{uuid.uuid4().hex}.{extension}"

    client = _get_client()
    client.storage.from_(BUCKET_NAME).upload(
        path, contents, {"content-type": file.content_type}
    )

    return client.storage.from_(BUCKET_NAME).get_public_url(path)