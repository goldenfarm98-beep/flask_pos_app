try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # fallback kalau dependency belum terpasang
    def load_dotenv(*_args, **_kwargs):
        return False

load_dotenv()  # akan membaca file .env di root project, no-op jika modul tidak tersedia
from datetime import datetime
import re
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf import CSRFProtect


from .config_db import load_env_once, resolve_database_uri, resolve_secret_key

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()


def normalize_phone(value):
    if value is None:
        return ""
    if isinstance(value, float):
        value = str(int(value)) if value.is_integer() else str(value)
    else:
        value = str(value)
    value = value.strip()
    if not value:
        return ""
    if re.fullmatch(r"\d+\.0+", value):
        value = value.split(".", 1)[0]
    digits = re.sub(r"\D", "", value)
    if not digits:
        return ""
    if digits.startswith("62"):
        digits = "0" + digits[2:]
    elif not digits.startswith("0"):
        digits = "0" + digits
    return digits


def create_app():
    app = Flask(__name__)

    # Load .env dan resolve DSN/SECRET
    load_env_once()
    app.config["SQLALCHEMY_DATABASE_URI"] = resolve_database_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = resolve_secret_key()
    # CSRF token dibiarkan tidak kedaluwarsa agar interaksi form panjang tidak gagal
    app.config["WTF_CSRF_TIME_LIMIT"] = None

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    app.jinja_env.filters["normalize_phone"] = normalize_phone

    # Optional: register blueprint jika ada
    try:
        from app.routes import bp

        app.register_blueprint(bp)
    except Exception:
        pass

    @app.context_processor
    def inject_template_globals():
        return {"current_year": datetime.utcnow().year}

    @app.shell_context_processor
    def _ctx():
        # supaya model langsung tersedia di flask shell
        try:
            from app import models

            ctx = {"db": db}
            for name in dir(models):
                if not name.startswith("_"):
                    ctx[name] = getattr(models, name)
            return ctx
        except Exception:
            return {"db": db}

    return app
