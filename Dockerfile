# Imagen de la API. El `dockerfile` que había antes estaba vacío (0 bytes),
# así que cualquier build fallaba.
#
#   docker build -t olivosport-api .
#   docker run --rm -p 8000:8000 --env-file .env olivosport-api
#
# Las migraciones NO se corren en el arranque a propósito: si dos
# instancias arrancan a la vez, dos `alembic upgrade head` compitiendo
# sobre la misma base es un problema. Se corren aparte, antes de
# desplegar:  alembic upgrade head

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /code

# Se copian primero los requirements para que Docker reuse la capa de
# dependencias mientras solo cambie el código.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Sin esto el proceso corre como root dentro del contenedor.
RUN useradd --create-home --uid 1000 olivo && chown -R olivo:olivo /code
USER olivo

EXPOSE 8000

# `sh -c` para que $PORT se expanda: Render (y varios PaaS) asignan el
# puerto por variable de entorno, no siempre es el 8000.
CMD ["sh", "-c", "uvicorn app.main_app:app --host 0.0.0.0 --port ${PORT}"]
