from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf import CSRFProtect

from .config_db import load_env_once, resolve_database_uri, resolve_secret_key

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()

def create_app():
    app = Flask(__name__)

    # Load .env dan resolve DSN/SECRET
    load_env_once()
    app.config["SQLALCHEMY_DATABASE_URI"] = resolve_database_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = resolve_secret_key()

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # Optional: register blueprint jika ada
    try:
        from app.routes import bp
        app.register_blueprint(bp)
    except Exception:
        pass

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
