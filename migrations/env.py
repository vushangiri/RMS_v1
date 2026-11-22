import os

from alembic import context
from sqlalchemy import create_engine

with create_engine(os.environ["DATABASE_URL"]).begin() as connection:
    context.configure(connection=connection)
    context.run_migrations()
