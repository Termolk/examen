import logging
from flask import Flask
from config import current_config
from flask_cors import CORS
from .extensions import db, migrate, ma, metrics, init_redis
from .services.minio_service import init_minio_client

def create_app(config_object=current_config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    CORS(app, resources={

    r"/api/*": {"origins": "http://127.0.0.1:8000", "supports_credentials": True},

    r"/auth/*": {"origins": "http://127.0.0.1:8000", "supports_credentials": True}

    }, expose_headers = ["Content-Type", "Authorization"],

    allow_headers = ["Content-Type", "Authorization", "X-Requested-With"])

    # Инициализация расширений
    db.init_app(app)
    migrate.init_app(app, db)
    ma.init_app(app)
    metrics.init_app(app) # metrics = PrometheusMetrics(app)
    init_redis(config_object)
    init_minio_client(app)

    # Настройка логирования
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s %(threadName)s : %(message)s')
    app.logger.info("ShareAndRent App Starting Up...")

    # Регистрация Blueprints (маршрутов)
    from .routes import auth, items # Импортируем здесь, чтобы избежать циклических зависимостей
    app.register_blueprint(auth.bp, url_prefix='/auth')
    app.register_blueprint(items.bp, url_prefix='/api') # Префикс /api для основных ресурсов

    from . import seed  # Убедись, что seed.py находится в той же директории (backend/app/)
    app.cli.add_command(seed.seed_cli)

    @app.route('/health')
    def health_check():
        app.logger.info("Health check accessed")
        return {"status": "healthy"}, 200

    # Создание таблиц БД (если не используются миграции для инициализации)
    # with app.app_context():
    # db.create_all() # Лучше использовать flask db upgrade

    return app