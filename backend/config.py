import os
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'your_default_secret_key')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///./shareandrent.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'fallback_jwt_secret')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=30) # Быстро для демонстрации
    REFRESH_JWT_SECRET_KEY = os.environ.get('REFRESH_JWT_SECRET_KEY', 'fallback_refresh_secret')
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

    MINIO_URL = os.environ.get('MINIO_URL', 'http://localhost:9000')
    MINIO_PUBLIC_URL = os.environ.get('MINIO_PUBLIC_URL', 'http://127.0.0.1:9000')
    MINIO_ACCESS_KEY = os.environ.get('MINIO_ACCESS_KEY', 'minioadmin')
    MINIO_SECRET_KEY = os.environ.get('MINIO_SECRET_KEY', 'minioadmin')
    MINIO_BUCKET_NAME = os.environ.get('MINIO_BUCKET_NAME', 'shareandrent-bucket')
    MINIO_SECURE = MINIO_URL.startswith('https') if MINIO_URL else False


class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False
    # Здесь могут быть другие настройки для продакшена

# Выбираем конфигурацию в зависимости от FLASK_ENV
config_by_name = dict(
    development=DevelopmentConfig,
    production=ProductionConfig
)

current_config = config_by_name.get(os.getenv('FLASK_ENV', 'development'), DevelopmentConfig)