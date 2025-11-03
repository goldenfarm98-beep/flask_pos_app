from logging.config import fileConfig
from alembic import context
from flask import current_app
from sqlalchemy import create_engine, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

def _target_metadata():
    return current_app.extensions["migrate"].db.metadata

def _get_url():
    try:
        # Ambil URL efektif dari engine Flask (sudah lewat resolver)
        return str(current_app.extensions["migrate"].db.get_engine().url)
    except Exception:
        # Fallback langsung via resolver jika dipanggil tanpa app context
        from app.config_db import load_env_once, resolve_database_uri
        load_env_once()
        return resolve_database_uri()

def run_migrations_offline():
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=_target_metadata(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    url = _get_url()
    connectable = create_engine(url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=_target_metadata())
        with context.begin_transaction():
            context.run_migrations()
