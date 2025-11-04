import os
from urllib.parse import quote_plus
from typing import Optional

from dotenv import load_dotenv, dotenv_values

_ENV_LOADED = False
_DOTENV_VALUES = {}

def load_env_once(dotenv_path: Optional[str] = None) -> None:
    """
    Load .env sekali saja dan simpan nilai mentah dari file .env di _DOTENV_VALUES.
    """
    global _ENV_LOADED, _DOTENV_VALUES
    if _ENV_LOADED:
        return
    path = dotenv_path or os.path.join(os.getcwd(), ".env")
    # load ke os.environ (supaya Flask/extension juga kebagian)
    load_dotenv(path)
    # simpan nilai mentah file .env (tanpa override dari shell)
    _DOTENV_VALUES = dotenv_values(path)
    _ENV_LOADED = True

def _first_nonempty(*vals: Optional[str]) -> Optional[str]:
    for v in vals:
        if v:
            v = v.strip()
            if v:
                return v
    return None

def _normalize_pg(url: Optional[str]) -> Optional[str]:
    if url and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url

def _mysql_from_parts() -> Optional[str]:
    """
    Rakit DSN MySQL dari kombinasi ENV dan .env:
      MYSQL_USER / MYSQL_USERNAME
      MYSQL_PASSWORD
      MYSQL_HOST (default 127.0.0.1)
      MYSQL_PORT (default 3306)
      MYSQL_DB / MYSQL_DATABASE
      MYSQL_CHARSET (default utf8mb4)
    """
    def gv(key: str, default: Optional[str] = None) -> Optional[str]:
        # Prioritas: ENV -> .env mentah
        return os.environ.get(key) or _DOTENV_VALUES.get(key) or default

    user = _first_nonempty(gv("MYSQL_USER"), gv("MYSQL_USERNAME"))
    pwd  = gv("MYSQL_PASSWORD", "")
    host = gv("MYSQL_HOST", "127.0.0.1")
    port = gv("MYSQL_PORT", "3306")
    db   = _first_nonempty(gv("MYSQL_DB"), gv("MYSQL_DATABASE"))
    charset = gv("MYSQL_CHARSET", "utf8mb4")

    if not (user and db):
        return None

    pwd_q = quote_plus(pwd or "")
    return f"mysql+pymysql://{user}:{pwd_q}@{host}:{port}/{db}?charset={charset}"

def resolve_database_uri() -> str:
    """
    Prioritas final:
      1) ENV SQLALCHEMY_DATABASE_URI
      2) .env SQLALCHEMY_DATABASE_URI
      3) .env DATABASE_URL
      4) ENV DATABASE_URL
      5) Rakit dari MYSQL_* (ENV/.env)
      6) Fallback sqlite:///instance/app.db
    Plus: normalize postgres:// -> postgresql://
    """
    # 1/2
    v1 = os.environ.get("SQLALCHEMY_DATABASE_URI")
    v2 = _DOTENV_VALUES.get("SQLALCHEMY_DATABASE_URI")
    url = _first_nonempty(v1, v2)
    if url:
        return _normalize_pg(url)

    # 3/4
    v3 = _DOTENV_VALUES.get("DATABASE_URL")
    v4 = os.environ.get("DATABASE_URL")
    url = _first_nonempty(v3, v4)
    if url:
        return _normalize_pg(url)

    # 5
    url = _mysql_from_parts()
    if url:
        return url

    # 6
    # pastikan folder instance ada
    inst = os.path.abspath(os.path.join(os.getcwd(), "instance"))
    os.makedirs(inst, exist_ok=True)
    return f"sqlite:///{os.path.join(inst, 'app.db')}"

def resolve_secret_key() -> str:
    """
    SECRET_KEY: ENV dulu, lalu .env, terakhir fallback.
    """
    return _first_nonempty(os.environ.get("SECRET_KEY"),
                           _DOTENV_VALUES.get("SECRET_KEY"),
                           "dev-secret-key")  # jangan pakai di production
