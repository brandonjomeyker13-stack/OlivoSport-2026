"""Capa de acceso a datos.

Cada repositorio se importa por su nombre completo:

    from app.repositories import product_repository

A propósito NO se re-exportan sus funciones acá: casi todos los
repositorios tienen una función `create` / `get_by_id` / `delete`, así
que un `import *` las pisaba entre sí y dejaba solo las del último
módulo importado.
"""
