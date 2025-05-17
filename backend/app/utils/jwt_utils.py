import jwt
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import request, jsonify, current_app, g
from ..models import User, RefreshToken # RefreshToken для управления отзывом refresh-токенов в БД
from ..extensions import db, redis_client # Импортируем redis_client
import uuid

def generate_access_token(user_id):
    payload = {
        'exp': datetime.now(timezone.utc) + current_app.config['JWT_ACCESS_TOKEN_EXPIRES'],
        'iat': datetime.now(timezone.utc),
        'sub': user_id,
        'type': 'access',
        'jti': str(uuid.uuid4())  # Уникальный идентификатор токена (важно для черного списка)
    }
    return jwt.encode(payload, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')

def generate_refresh_token(user_id):
    jti = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + current_app.config['JWT_REFRESH_TOKEN_EXPIRES']

    payload = {
        'exp': expires_at,
        'iat': datetime.now(timezone.utc),
        'sub': user_id,
        'type': 'refresh',
        'jti': jti
    }

    try:
        refresh_token_db = RefreshToken(
            user_id=user_id,
            token_jti=jti,
            expires_at=expires_at,
            revoked=False
        )
        db.session.add(refresh_token_db)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error saving refresh token JTI to DB: {e}")
        raise
    return jwt.encode(payload, current_app.config['REFRESH_JWT_SECRET_KEY'], algorithm='HS256')

def decode_token(token, secret_key):
    try:
        return jwt.decode(token, secret_key, algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        current_app.logger.warning("Token expired")
        return None
    except jwt.InvalidTokenError:
        current_app.logger.warning("Invalid token")
        return None

def add_access_jti_to_denylist(jti, expires_in_seconds):
    """Добавляет JTI access-токена в черный список Redis с временем жизни."""
    if not redis_client:
        current_app.logger.error("Redis client not initialized. Cannot add JTI to denylist.")
        return False
    try:
        key_name = f"denylist_access_jti:{jti}"
        redis_client.setex(key_name, int(expires_in_seconds), "revoked")
        current_app.logger.info(f"Access JTI {jti} added to denylist in Redis, expires in {int(expires_in_seconds)}s.")
        return True
    except Exception as e:
        current_app.logger.error(f"Error adding JTI {jti} to Redis denylist: {e}")
        return False

def is_access_jti_denylisted(jti):
    """Проверяет, находится ли JTI access-токена в черном списке Redis."""
    if not redis_client:
        current_app.logger.error("Redis client not initialized. Cannot check JTI in denylist.")
        return False # Если Redis недоступен, безопаснее считать, что токен не в списке (или наоборот, в зависимости от политики)
    try:
        key_name = f"denylist_access_jti:{jti}"
        return redis_client.exists(key_name)
    except Exception as e:
        current_app.logger.error(f"Error checking JTI {jti} in Redis denylist: {e}")
        return False # В случае ошибки, для простоты считаем, что токен не в списке

def jwt_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({"msg": "Missing Authorization Header"}), 401

        parts = auth_header.split()
        if parts[0].lower() != 'bearer' or len(parts) == 1 or len(parts) > 2:
            return jsonify({"msg": "Invalid Authorization Header format. Expected 'Bearer <token>'"}), 401

        token = parts[1]

        try:
            payload = decode_token(token, current_app.config['JWT_SECRET_KEY'])
            if payload is None or payload.get('type') != 'access':
                # decode_token вернет None, если токен истек или невалиден
                return jsonify({"msg": "Invalid or expired access token (payload check or decode failed)"}), 401

            access_jti = payload.get('jti')
            if not access_jti:
                current_app.logger.error("Access token JTI is missing in payload!")
                return jsonify({"msg": "Access token is missing JTI"}), 401

            if is_access_jti_denylisted(access_jti):
                current_app.logger.warning(f"Access token with JTI {access_jti} is denylisted (logout).")
                return jsonify({"msg": "Access token has been revoked (logged out)"}), 401

            user_id = payload.get('sub')
            current_user = db.session.execute(
                db.select(User).where(User.id == user_id)
            ).scalar_one_or_none()

            if not current_user:
                return jsonify({"msg": "User not found"}), 401

            g.current_user = current_user
            g.current_user_id = user_id
            g.jwt_payload = payload
            g.access_jti = access_jti

        except jwt.ExpiredSignatureError: # Эта ветка может быть уже не нужна, т.к. decode_token ее обработает
            return jsonify({"msg": "Access token has expired (signature)"}), 401
        except jwt.InvalidTokenError: # Аналогично
            return jsonify({"msg": "Invalid access token (invalid)"}), 401
        except Exception as e:
            current_app.logger.error(f"Error in jwt_required: {e}")
            return jsonify({"msg": "Error processing token"}), 500

        return f(*args, **kwargs)
    return decorated_function

def get_jti_from_token(token, secret_key):
    """Извлекает JTI из токена, не проверяя срок его действия."""
    try:
        payload = jwt.decode(token, secret_key, algorithms=['HS256'], options={"verify_exp": False})
        return payload.get('jti')
    except jwt.InvalidTokenError:
        return None

def revoke_refresh_token(jti):
    """Отзывает refresh-токен в базе данных."""
    if not jti:
        return False
    try:
        token_entry = RefreshToken.query.filter_by(token_jti=jti).first()
        if token_entry:
            if token_entry.revoked:
                current_app.logger.info(f"Refresh token JTI {jti} was already revoked in DB.")
                return True # Считаем успешным, если уже отозван
            token_entry.revoked = True
            db.session.commit()
            current_app.logger.info(f"Refresh token JTI {jti} successfully revoked in DB.")
            return True
        current_app.logger.warning(f"Refresh token JTI {jti} not found in DB for revocation.")
        return False
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error revoking refresh token JTI {jti} in DB: {e}")
        return False

def is_refresh_token_revoked(jti):
    """Проверяет, отозван ли refresh-токен в базе данных."""
    if not jti:
        return True # Считаем отозванным, если нет JTI
    token_entry = RefreshToken.query.filter_by(token_jti=jti).first()
    return token_entry is None or token_entry.revoked