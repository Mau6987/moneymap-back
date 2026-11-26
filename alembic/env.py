from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings

# Las migraciones corren con el dueño de las tablas (no con moneymap_app).
connectable = create_engine(get_settings().migrations_database_url, poolclass=pool.NullPool)

with connectable.connect() as connection:
    context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()
