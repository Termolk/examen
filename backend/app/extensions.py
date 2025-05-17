from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_marshmallow import Marshmallow
from prometheus_flask_exporter import PrometheusMetrics
from prometheus_client import Counter, Gauge # <--- Импортируем типы метрик
import redis

db = SQLAlchemy()
migrate = Migrate()
ma = Marshmallow()
metrics = PrometheusMetrics(app=None, group_by='endpoint') # Инициализируем позже
redis_client = None # Инициализируем позже

# --- Кастомные метрики ---
USER_REGISTERED_COUNTER = Counter(
    'app_user_registered_total',
    'Total number of registered users'
)
USER_LOGIN_COUNTER = Counter(
    'app_user_login_total',
    'Total number of successful user logins'
)
LISTINGS_CREATED_COUNTER = Counter(
    'app_listings_created_total',
    'Total number of listings created',
    ['category_name']  # Пример метрики с меткой (label)
)
BOOKINGS_CREATED_COUNTER = Counter(
    'app_bookings_created_total',
    'Total number of bookings created'
)
REVIEWS_CREATED_COUNTER = Counter(
    'app_reviews_created_total',
    'Total number of reviews created'
)
MINIO_UPLOADS_TOTAL = Counter(
    'app_minio_uploads_total',
    'Total number of files successfully uploaded to MinIO'
)
MINIO_UPLOAD_ERRORS_TOTAL = Counter(
    'app_minio_upload_errors_total',
    'Total errors during MinIO uploads'
)
CURRENT_LISTINGS_GAUGE = Gauge(
    'app_current_listings_total',
    'Current total number of listings (active or not)'
)
# -------------------------

def init_redis(app_config):
    global redis_client
    redis_client = redis.from_url(app_config.REDIS_URL, decode_responses=True)
    try:
        redis_client.ping()
        current_app.logger.info("Successfully connected to Redis!") # Используем current_app.logger, если доступно, или print
    except redis.exceptions.ConnectionError as e:
        # В момент инициализации current_app может быть недоступен, если init_redis вызывается до создания app
        print(f"Could not connect to Redis: {e}") # Используем print как fallback
    except Exception as e_global: # Ловим другие возможные ошибки при инициализации Redis
        print(f"An unexpected error occurred during Redis initialization: {e_global}")