from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import engine
from app.core.errors import ApiError, api_error_handler, db_error_handler, validation_error_handler
from app.modules import ROUTERS

app = FastAPI(title="MoneyMap API", version="0.1.0")
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(DBAPIError, db_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
for router in ROUTERS:
    app.include_router(router, prefix="/v1")


@app.get("/health", tags=["ops"])
async def health() -> dict[str, bool | str]:
    """Para el monitoreo: la API responde y llega a la base de datos."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok", "database": db_ok}
