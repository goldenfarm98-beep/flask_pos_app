import os

DEFAULT_URI = "postgresql://postgres:postgres@localhost/my_database"

def resolve_sqlalchemy_uri(app_config: dict | None = None) -> str:
    """Ambil DSN dari ENV > app_config > default."""
    env_uri = os.getenv("SQLALCHEMY_DATABASE_URI") or os.getenv("DATABASE_URL")
    if env_uri:
        return env_uri
    if app_config and app_config.get("SQLALCHEMY_DATABASE_URI"):
        return app_config["SQLALCHEMY_DATABASE_URI"]
    return DEFAULT_URI

def engine_options(uri: str) -> dict:
    """Opsi engine yang aman; MySQL diberi pool recycle, dll."""
    opts = {"pool_pre_ping": True}
    if uri.startswith("mysql"):
        opts.update({"pool_recycle": 1800, "pool_size": 5, "max_overflow": 10})
    return opts
