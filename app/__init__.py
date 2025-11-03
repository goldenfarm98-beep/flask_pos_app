# app/__init__.py
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()

def create_app():
    app = Flask(__name__)

    # --- gunakan ENV, fallback ke SQLite lokal bila ENV kosong ---
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
        'SQLALCHEMY_DATABASE_URI',
        'sqlite:///app.db'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-secret-key')

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # optional: endpoint debug untuk cek koneksi DB
    @app.get("/_debug_db")
    def _debug_db():
        from sqlalchemy import text
        eng = db.engine
        info = {
            "dialect": eng.dialect.name,
            "driver": eng.driver,
            "url": str(eng.url).replace(eng.url.password or "", "****") if eng.url.password else str(eng.url),
        }
        try:
            with eng.connect() as c:
                if eng.dialect.name == "mysql":
                    row = c.exec_driver_sql("SELECT @@version AS version, DATABASE() AS db").fetchone()
                elif eng.dialect.name in ("postgresql", "postgres"):
                    row = c.exec_driver_sql("SELECT version() AS version, current_database() AS db").fetchone()
                else:
                    row = None
            if row:
                info["server_version"] = row[0]
                info["current_db"] = row[1]
        except Exception as e:
            info["probe_error"] = repr(e)
        return info, 200

    from app.routes import bp
    app.register_blueprint(bp)

    return app
