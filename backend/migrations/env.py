from alembic import context
from fitcheck_backend.storage.models import Base

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Use the FitCheck migration runner with an explicit connection")
context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
with context.begin_transaction():
    context.run_migrations()
