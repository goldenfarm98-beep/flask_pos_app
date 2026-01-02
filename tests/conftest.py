# tests/conftest.py
import os
import pytest
from sqlalchemy.pool import StaticPool

# --- Paksa environment test yang aman ---
os.environ.setdefault("FLASK_ENV", "test")
os.environ.setdefault("SECRET_KEY", "test")
# Gunakan SQLite in-memory agar tidak butuh MySQL saat CI
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# Kosongkan env MYSQL_* supaya kode tidak memaksa DSN MySQL
for k in ("MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"):
    os.environ.setdefault(k, "")

_app = None
_db = None

def _build_app():
    """
    Coba beberapa pola umum:
    - from app import create_app, db
    - import app (yang berisi 'app' dan/atau 'db')
    """
    global _app, _db

    try:
        # Pola pabrik aplikasi (factory)
        from app import create_app, db as dbobj  # type: ignore
        # beberapa proyek pakai create_app("testing") / ("test")
        try:
            a = create_app("testing")
        except Exception:
            try:
                a = create_app("test")
            except Exception:
                a = create_app()
        _app, _db = a, dbobj
        return
    except Exception:
        pass

    try:
        # Pola script tunggal app.py
        import app as app_module  # type: ignore
        a = getattr(app_module, "app", None)
        d = getattr(app_module, "db", None)
        if a is None and hasattr(app_module, "create_app"):
            a = app_module.create_app()  # type: ignore
            d = getattr(app_module, "db", d)
        if a is None:
            raise RuntimeError("Tidak bisa menemukan objek Flask 'app' atau 'create_app'")
        _app, _db = a, d
        return
    except Exception as e:
        raise RuntimeError(f"Gagal membangun aplikasi untuk testing: {e!r}")

# Inisialisasi satu kali per session
_build_app()

@pytest.fixture(scope="session")
def app():
    # Buat semua tabel untuk test (jika SQLAlchemy ada)
    if _db is not None and hasattr(_db, "create_all"):
        _app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            SQLALCHEMY_ENGINE_OPTIONS={
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            },
        )
        with _app.app_context():
            _db.create_all()
    return _app

@pytest.fixture()
def client(app):
    return app.test_client()

@pytest.fixture()
def runner(app):
    return app.test_cli_runner()
