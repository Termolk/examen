from minio import Minio
from minio.error import S3Error
from flask import current_app # current_app здесь нужен для get_minio_client, но не для init_minio_client логгера
import io
from urllib.parse import urlparse, urlunparse
from datetime import timedelta # Добавлен импорт timedelta

# init_minio_client(app) использует app.logger
# get_minio_client() использует current_app.logger (обычно вызывается в контексте запроса)

def init_minio_client(app):
    """Инициализирует клиент Minio и сохраняет его в app.extensions."""
    try:
        client = Minio(
            endpoint=app.config['MINIO_URL'].replace('http://', '').replace('https://', ''),
            access_key=app.config['MINIO_ACCESS_KEY'],
            secret_key=app.config['MINIO_SECRET_KEY'],
            secure=app.config['MINIO_SECURE']
        )
        if not hasattr(app, 'extensions'):
            app.extensions = {}
        app.extensions['minio'] = client

        bucket_name = app.config['MINIO_BUCKET_NAME']
        found = client.bucket_exists(bucket_name)
        if not found:
            client.make_bucket(bucket_name)
            app.logger.info(f"Bucket '{bucket_name}' created.") # ИЗМЕНЕНО
            # Пример установки политики (если нужно, но лучше presigned URLs)
            # import json
            # client.set_bucket_policy(bucket_name, json.dumps({
            # "Version": "2012-10-17",
            # "Statement": [{
            # "Effect": "Allow",
            # "Principal": {"AWS": "*"},
            # "Action": ["s3:GetObject"],
            # "Resource": [f"arn:aws:s3:::{bucket_name}/*"]
            # }]
            # }))
            # app.logger.info(f"Bucket '{bucket_name}' policy set to public-read (for development).") # ИЗМЕНЕНО
        else:
            app.logger.info(f"Bucket '{bucket_name}' already exists.") # ИЗМЕНЕНО
        app.logger.info("Minio client initialized successfully.") # ИЗМЕНЕНО

    except Exception as e:
        app.logger.error(f"Minio client initialization error: {e}") # ИЗМЕНЕНО
        if hasattr(app, 'extensions'):
            app.extensions.pop('minio', None)


def get_minio_client():
    """Получает клиент Minio из current_app.extensions."""
    # Эта функция обычно вызывается внутри контекста запроса, где current_app доступен.
    if 'minio' not in current_app.extensions:
        current_app.logger.error("Minio client not found in app.extensions. Was it initialized?")
        raise RuntimeError("Minio client not initialized")
    return current_app.extensions['minio']


def upload_file_to_minio(file_storage, object_name, content_type=None):
    """
    Загружает файл (werkzeug.FileStorage) в Minio.
    object_name: полное имя объекта в Minio, включая "папки", например, "listings/uuid_filename.jpg"
    """
    # Используем get_minio_client, который работает с current_app,
    # так как эта функция будет вызываться в контексте запроса.
    client = get_minio_client()
    bucket_name = current_app.config['MINIO_BUCKET_NAME']

    try:
        file_stream = file_storage.stream
        file_stream.seek(0)

        file_data = file_stream.read()
        file_size = len(file_data)
        # file_stream.seek(0) # Не нужно, так как BytesIO(file_data) создаст новый поток

        if not content_type:
            content_type = file_storage.content_type or 'application/octet-stream'

        client.put_object(
            bucket_name,
            object_name,
            io.BytesIO(file_data), # Создаем новый BytesIO из прочитанных данных
            length=file_size,
            content_type=content_type
        )
        file_url = f"{current_app.config['MINIO_URL']}/{bucket_name}/{object_name}"
        current_app.logger.info(f"File {object_name} uploaded successfully to Minio. URL: {file_url}")
        return file_url # Возвращаем object_name, а не полный URL, т.к. URL может быть непрямым
                        # Вернем object_name, как было в оригинальной логике image_url в ListingImage
                        # return object_name
    except S3Error as e:
        current_app.logger.error(f"Minio S3 Error during upload of {object_name}: {e}")
        raise
    except Exception as e:
        current_app.logger.error(f"Unexpected error during upload of {object_name} to Minio: {e}")
        raise


def delete_file_from_minio(object_name):
    """Удаляет файл из Minio."""
    client = get_minio_client()
    bucket_name = current_app.config['MINIO_BUCKET_NAME']
    try:
        client.remove_object(bucket_name, object_name)
        current_app.logger.info(f"File {object_name} deleted successfully from Minio.")
        return True
    except S3Error as e:
        current_app.logger.error(f"Minio S3 Error during deletion of {object_name}: {e}")
        return False # Было raise, но для удаления лучше вернуть False и залогировать
    except Exception as e:
        current_app.logger.error(f"Unexpected error during deletion of {object_name} from Minio: {e}")
        return False # Аналогично


def get_presigned_url_for_minio(object_name, expires_in_seconds=3600):
    bucket_name = current_app.config['MINIO_BUCKET_NAME']
    public_minio_url_str = current_app.config.get('MINIO_PUBLIC_URL', 'http://localhost:9000')

    current_app.logger.info(f"--- Generating presigned URL (Region Fix v2) ---")
    current_app.logger.info(f"Object Name: '{object_name}'")
    current_app.logger.info(f"Target Bucket Name (from config): '{bucket_name}'") # Убедитесь, что это 'shareandrent-bucket' если это так
    current_app.logger.info(f"MinIO Public URL (for signature & final URL): '{public_minio_url_str}'")

    parsed_public_url = urlparse(public_minio_url_str)
    public_endpoint_host_port = parsed_public_url.netloc
    public_scheme_is_secure = parsed_public_url.scheme == 'https'

    # Определяем регион: используем MINIO_REGION из переменных окружения, если задано, иначе 'us-east-1'
    # 'us-east-1' является безопасным значением по умолчанию для MinIO, если на сервере не настроен особый регион.
    region_to_use = current_app.config.get('MINIO_REGION', 'us-east-1')
    current_app.logger.info(f"Region to be used for signing_client: '{region_to_use}'")

    try:
        signing_client = Minio(
            endpoint=public_endpoint_host_port, # Это будет '127.0.0.1:9000' или 'localhost:9000'
            access_key=current_app.config['MINIO_ACCESS_KEY'],
            secret_key=current_app.config['MINIO_SECRET_KEY'],
            secure=public_scheme_is_secure,
            region=region_to_use  # Явно указываем регион
        )

        presigned_url = signing_client.presigned_get_object(
            bucket_name,
            object_name,
            expires=timedelta(seconds=expires_in_seconds)
        )
        current_app.logger.info(f"Generated presigned URL using public endpoint context and region '{region_to_use}': {presigned_url}")
        current_app.logger.info(f"--- End of presigned URL generation (Region Fix v2) ---")

        return presigned_url

    except S3Error as e:
        current_app.logger.error(f"Minio S3 Error generating presigned URL for '{object_name}' with region '{region_to_use}': {e}", exc_info=True)
        if hasattr(e, 'response') and e.response is not None:
             current_app.logger.error(f"S3Error response data: {e.response.data}")
        return None
    except Exception as e:
        # Эта секция ловит другие ошибки, включая NewConnectionError, если они все еще возникают
        current_app.logger.error(f"Unexpected error generating presigned URL for '{object_name}' with region '{region_to_use}': {e}", exc_info=True)
        return None