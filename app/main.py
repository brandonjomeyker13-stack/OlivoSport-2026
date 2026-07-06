"""
App de FastAPI. Se corre con:

    uvicorn app.main:app --reload

(el `main.py` de la raíz sigue siendo solo para crear las tablas, no lo
mezcles con este archivo).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1 import auth, cart, products
from app.core.limiter import limiter

app = FastAPI(title="OlivoSport API", version="1.0.0")

# Rate limiting global (protege sobre todo /auth/login y /auth/register
# de ataques de fuerza bruta). Los límites puntuales se definen en cada
# endpoint con @limiter.limit(...).
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Mientras no tengas el dominio real de tu frontend, deja aquí solo los
# orígenes de desarrollo que uses (ej. Vite, Create React App, Next.js).
# Cuando despliegues el frontend, agrega su URL real (ej. "https://olivosport.com")
# y quita las de localhost si ya no las necesitas.
origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "https://.*\.(lovable\.app|lovableproject\.com)"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(products.router, prefix="/api/v1/products", tags=["products"])
app.include_router(cart.router, prefix="/api/v1/cart", tags=["cart"])


@app.get("/")
def root():
    return {"message": "OlivoSport API está corriendo"}


@app.get("/health")
def health_check():
    return {"status": "ok"}