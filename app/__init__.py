import os
from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf import CSRFProtect
from .config_db import resolve_sqlalchemy_uri, engine_options

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()

def create_app():
    # pakai instance_relative_config agar instance/config.py (opsional) bisa dipakai
    app = Flask(__name__, instance_relative_config=True)

    # 1) DEFAULTS (boleh di-override)
    app.config.update(
        SECRET_KEY="default-secret-key",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_DATABASE_URI="postgresql://postgres:postgres@localhost/my_database",
    )

    # 2) INSTANCE CONFIG (opsional) – override default
    app.config.from_pyfile("config.py", silent=True)

    # 3) ENV OVERRIDES – paling akhir agar ENV selalu menang
    uri = resolve_sqlalchemy_uri(app.config)
    app.config["SQLALCHEMY_DATABASE_URI"] = uri
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_options(uri)

    # Inisialisasi ekstensi
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # Registrasi blueprint
    from app.routes import bp
    app.register_blueprint(bp)

    # Endpoint debug cepat
    @app.get("/_debug_db")
    def _debug_db():
        return jsonify(
            uri=app.config["SQLALCHEMY_DATABASE_URI"],
            engine_options=app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {}),
            env_sqlalchemy=os.getenv("SQLALCHEMY_DATABASE_URI"),
            env_database_url=os.getenv("DATABASE_URL"),
        )

    return app
