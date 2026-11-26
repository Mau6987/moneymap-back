"""El reloj del sistema.

Ningún módulo llama a `datetime.now()`: el reloj sale de aquí, así que las
pruebas son deterministas (engineering §2.7). Se importa el módulo, no la
función, para poder reemplazarla desde una prueba.
"""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """El ahora en UTC y con zona, como el `timestamptz` de la base."""
    return datetime.now(UTC)
