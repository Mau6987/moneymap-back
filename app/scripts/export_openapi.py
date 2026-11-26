"""Imprime el contrato OpenAPI para generar el cliente de la app.

Uso: uv run python -m app.scripts.export_openapi > openapi.json
"""

import json

from app.main import app

if __name__ == "__main__":
    print(json.dumps(app.openapi(), ensure_ascii=False, indent=2))
