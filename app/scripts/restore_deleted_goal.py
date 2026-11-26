"""Restaura una meta borrada lógicamente para que su saldo vuelva a una cuenta.

El borrado de metas es lógico: la fila y sus aportes siguen en la base, pero la
meta no aparece. Si se borró con saldo antes de la regla nueva (migración 0022),
este script la vuelve a mostrar; después, desde la app, se retira el saldo a la
cuenta que corresponda y se borra con el flujo nuevo. No crea ni mueve dinero.

Uso (primero sin `--apply`, que solo muestra qué haría):

    uv run python -m app.scripts.restore_deleted_goal persona@ejemplo.com cars
    uv run python -m app.scripts.restore_deleted_goal persona@ejemplo.com cars --apply

La conexión es la de las migraciones (rol dueño) y sale de `DATABASE_URL` /
`MIGRATIONS_DATABASE_URL` del entorno, igual que Alembic. No se ejecuta desde la
API.
"""

import argparse
import asyncio
import sys
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings


async def main() -> None:
    parser = argparse.ArgumentParser(description="Restaura una meta borrada con saldo.")
    parser.add_argument("email", help="Correo del usuario dueño de la meta")
    parser.add_argument("goal", help="Nombre exacto de la meta o su id")
    parser.add_argument("--apply", action="store_true", help="Aplica el cambio; sin esto solo muestra")
    args = parser.parse_args()

    engine = create_async_engine(get_settings().migrations_database_url)
    async with engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    text(
                        """
                    SELECT goals.id, goals.user_id, goals.name, goals.current_amount,
                           goals.target_amount, goals.deleted_at
                    FROM goals.goals AS goals
                    JOIN iam.users AS users ON users.id = goals.user_id
                    WHERE users.email = :email
                      AND goals.deleted_at IS NOT NULL
                      AND (goals.id::text = :goal OR lower(goals.name) = lower(:goal))
                    ORDER BY goals.deleted_at DESC
                    LIMIT 1
                    """
                    ),
                    {"email": args.email, "goal": args.goal},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            print("No hay una meta borrada con ese correo y nombre/id.")
            return

        duplicate = (
            await connection.execute(
                text(
                    """
                    SELECT 1
                    FROM goals.goals
                    WHERE user_id = :user_id AND deleted_at IS NULL
                      AND lower(name) = lower(:name)
                    """
                ),
                {"user_id": row["user_id"], "name": row["name"]},
            )
        ).first()
        if duplicate is not None:
            print(f"Ya hay una meta viva llamada «{row['name']}». Renombrala o borrala antes de restaurar la otra.")
            return

        print(
            f"Meta: {row['name']} ({row['id']})\n"
            f"Ahorrado: {row['current_amount']} de {row['target_amount']}\n"
            f"Borrada: {row['deleted_at']}"
        )
        if not args.apply:
            print("Sin cambios. Volvé a ejecutarlo con --apply para restaurarla.")
            return

        await connection.execute(
            text("UPDATE goals.goals SET deleted_at = NULL WHERE id = :goal_id"),
            {"goal_id": UUID(str(row["id"]))},
        )
        await connection.commit()
        print("Meta restaurada. Abrí la app, retirá el saldo a una cuenta y después borrala.")
    await engine.dispose()


if __name__ == "__main__":
    if sys.platform == "win32":
        # psycopg async no corre en el ProactorEventLoop de Windows.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
