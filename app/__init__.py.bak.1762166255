from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()

def create_app():
    app = Flask(__name__)

    # Konfigurasi aplikasi
    app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:postgres@localhost/my_database'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = 'default-secret-key'

    # Inisialisasi plugin
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # Registrasi blueprint
    from app.routes import bp
    app.register_blueprint(bp)

    return app
