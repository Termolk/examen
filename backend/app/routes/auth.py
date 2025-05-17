from flask import Blueprint, request, jsonify, current_app, g
# werkzeug.security import generate_password_hash - уже не нужен напрямую здесь
from ..models import User, RefreshToken
from ..extensions import db
from ..schemas import UserSchema, RegisterSchema, LoginSchema
from ..utils.jwt_utils import (
    generate_access_token,
    generate_refresh_token,
    decode_token,
    jwt_required,
    revoke_refresh_token,
    is_refresh_token_revoked,
    get_jti_from_token,
    add_access_jti_to_denylist
)
from marshmallow import ValidationError
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone

# Импорт кастомных метрик
from ..extensions import USER_REGISTERED_COUNTER, USER_LOGIN_COUNTER

bp = Blueprint('auth', __name__)
user_schema = UserSchema()
register_schema = RegisterSchema()
login_schema = LoginSchema()

@bp.route('/register', methods=['POST'])
def register():
    json_data = request.get_json()
    if not json_data:
        current_app.logger.warning("Registration attempt with missing JSON data.")
        return jsonify({"msg": "Missing JSON in request"}), 400

    try:
        data = register_schema.load(json_data)
    except ValidationError as err:
        current_app.logger.warning(f"Registration validation error: {err.messages}")
        return jsonify(err.messages), 422

    if data['password'] != data['confirm_password']:
        current_app.logger.warning(f"Registration attempt for user '{data.get('username', 'N/A')}' with non-matching passwords.")
        return jsonify({"msg": "Passwords do not match"}), 400

    new_user = User(username=data['username'])
    new_user.set_password(data['password'])

    try:
        db.session.add(new_user)
        db.session.commit()
        USER_REGISTERED_COUNTER.inc() # Инкремент метрики
        current_app.logger.info(f"User '{new_user.username}' registered successfully. ID: {new_user.id}")
    except IntegrityError:
        db.session.rollback()
        current_app.logger.warning(f"Registration attempt for existing username: {data['username']}")
        return jsonify({"msg": "User with this username already exists"}), 409
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error during registration for user {data.get('username', 'N/A')}: {e}", exc_info=True)
        return jsonify({"msg": "Could not create user"}), 500

    return jsonify(UserSchema(exclude=("password_hash", "refresh_tokens_assc")).dump(new_user)), 201

@bp.route('/login', methods=['POST'])
def login():
    json_data = request.get_json()
    if not json_data:
        current_app.logger.warning("Login attempt with missing JSON data.")
        return jsonify({"msg": "Missing JSON in request"}), 400

    try:
        data = login_schema.load(json_data)
    except ValidationError as err:
        current_app.logger.warning(f"Login validation error: {err.messages}")
        return jsonify(err.messages), 422

    current_app.logger.info(f"Login attempt for username: {data.get('username', 'N/A')}")
    user = db.session.execute(
        db.select(User).where(User.username == data['username'])
    ).scalar_one_or_none()

    if user and user.check_password(data['password']):
        try:
            access_token = generate_access_token(user.id)
            refresh_token = generate_refresh_token(user.id)
            USER_LOGIN_COUNTER.inc() # Инкремент метрики
            current_app.logger.info(f"User '{user.username}' (ID: {user.id}) logged in successfully.")
            return jsonify(access_token=access_token, refresh_token=refresh_token), 200
        except Exception as e:
            current_app.logger.error(f"Token generation error for user '{user.username}' during login: {e}", exc_info=True)
            return jsonify({"msg": "Login successful, but could not generate tokens. Please try again."}), 500
    else:
        current_app.logger.warning(f"Failed login attempt for username: {data.get('username', 'N/A')}. Reason: Bad username or password.")
        return jsonify({"msg": "Bad username or password"}), 401

@bp.route('/refresh', methods=['POST'])
def refresh():
    json_data = request.get_json()
    if not json_data or 'refresh_token' not in json_data:
        current_app.logger.warning("Token refresh attempt with missing refresh_token.")
        return jsonify({"msg": "Missing refresh_token in JSON body"}), 400

    refresh_token_from_request = json_data['refresh_token']
    current_app.logger.info("Attempting to refresh token.")

    try:
        payload = decode_token(refresh_token_from_request, current_app.config['REFRESH_JWT_SECRET_KEY'])
        if payload is None or payload.get('type') != 'refresh':
            current_app.logger.warning(f"Invalid or expired refresh token provided for refresh. Payload: {payload}")
            return jsonify({"msg": "Invalid or expired refresh token"}), 401

        user_id = payload.get('sub')
        jti = payload.get('jti')

        if is_refresh_token_revoked(jti):
            current_app.logger.warning(f"Attempt to use revoked refresh token JTI: {jti} for user ID: {user_id}")
            return jsonify({"msg": "Refresh token has been revoked or is invalid"}), 401

        new_access_token = generate_access_token(user_id)
        current_app.logger.info(f"Access token refreshed successfully for user ID: {user_id}")
        return jsonify(access_token=new_access_token), 200

    except jwt.ExpiredSignatureError:
        current_app.logger.warning("Refresh token has expired (signature error).")
        return jsonify({"msg": "Refresh token has expired"}), 401
    except jwt.InvalidTokenError as e_jwt_invalid:
        current_app.logger.warning(f"Invalid refresh token (invalid token error): {e_jwt_invalid}")
        return jsonify({"msg": "Invalid refresh token"}), 401
    except Exception as e:
        current_app.logger.error(f"Error during token refresh: {e}", exc_info=True)
        return jsonify({"msg": "Error processing token refresh"}), 500

@bp.route('/logout', methods=['POST'])
@jwt_required
def logout():
    current_app.logger.info(f"User '{g.current_user.username}' (ID: {g.current_user_id}, JTI: {g.access_jti}) initiated logout.")
    json_data = request.get_json()
    if not json_data or 'refresh_token' not in json_data:
        current_app.logger.warning(f"Logout attempt by user '{g.current_user.username}' missing refresh_token in JSON body.")
        return jsonify({"msg": "Missing refresh_token in JSON body for full logout"}), 400

    refresh_token_to_revoke_str = json_data['refresh_token']
    access_jti_to_denylist = getattr(g, 'access_jti', None)
    access_token_payload = getattr(g, 'jwt_payload', None)

    refresh_revoked_db_status = False
    access_token_denylisted_redis_status = False
    final_message_parts = ["Logout process initiated."]

    try:
        payload_refresh = decode_token(refresh_token_to_revoke_str, current_app.config['REFRESH_JWT_SECRET_KEY'])
        if payload_refresh and payload_refresh.get('type') == 'refresh' and payload_refresh.get('sub') == g.current_user_id:
            jti_refresh = payload_refresh.get('jti')
            if revoke_refresh_token(jti_refresh):
                refresh_revoked_db_status = True
        else:
            current_app.logger.warning(f"Invalid refresh token or token mismatch during logout for user '{g.current_user.username}'. Refresh JTI for DB revocation not processed.")
    except Exception as e:
        current_app.logger.error(f"Error during refresh token DB revocation part of logout for user '{g.current_user.username}': {e}", exc_info=True)
        jti_refresh_fallback = get_jti_from_token(refresh_token_to_revoke_str, current_app.config['REFRESH_JWT_SECRET_KEY'])
        if jti_refresh_fallback and revoke_refresh_token(jti_refresh_fallback):
            refresh_revoked_db_status = True

    if refresh_revoked_db_status:
        final_message_parts.append("Refresh token revoked from DB.")
        current_app.logger.info(f"Refresh token for user '{g.current_user.username}' successfully revoked from DB.")
    else:
        final_message_parts.append("Refresh token DB revocation failed or was not applicable.")
        current_app.logger.warning(f"Refresh token DB revocation failed or not applicable for user '{g.current_user.username}'.")

    if access_jti_to_denylist and access_token_payload:
        exp_timestamp = access_token_payload.get('exp')
        if exp_timestamp:
            expires_at_dt = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
            now_utc = datetime.now(timezone.utc)
            if expires_at_dt > now_utc:
                time_until_expiry_seconds = (expires_at_dt - now_utc).total_seconds()
                if time_until_expiry_seconds > 0:
                    if add_access_jti_to_denylist(access_jti_to_denylist, time_until_expiry_seconds):
                        access_token_denylisted_redis_status = True
                    else:
                        current_app.logger.error(f"Failed to denylist access token JTI {access_jti_to_denylist} in Redis for user '{g.current_user.username}'.")
                else:
                    current_app.logger.info(f"Access token JTI {access_jti_to_denylist} for user '{g.current_user.username}' already (or about to be) expired, not adding to denylist.")
            else:
                current_app.logger.info(f"Access token JTI {access_jti_to_denylist} for user '{g.current_user.username}' has already expired based on 'exp' claim.")
        else:
            current_app.logger.warning(f"Access token JTI {access_jti_to_denylist} for user '{g.current_user.username}' payload missing 'exp' claim, cannot denylist with expiry.")
    else:
        current_app.logger.warning(f"Access token JTI or payload not available for denylisting during logout for user '{g.current_user.username}'.")

    if access_token_denylisted_redis_status:
        final_message_parts.append("Access token denylisted in Redis.")
        current_app.logger.info(f"Access token JTI {access_jti_to_denylist} for user '{g.current_user.username}' denylisted in Redis.")
    elif access_jti_to_denylist :
        final_message_parts.append("Access token was not denylisted in Redis (e.g. already expired or Redis issue).")
    else:
        final_message_parts.append("Access token could not be processed for Redis denylist (JTI not available).")

    current_app.logger.info(f"Logout completed for user '{g.current_user.username}'. Message: {' '.join(final_message_parts)}")
    return jsonify({"msg": " ".join(final_message_parts)}), 200

@bp.route('/protected', methods=['GET'])
@jwt_required
def protected():
    current_app.logger.debug(f"Protected route accessed by user '{g.current_user.username}' (ID: {g.current_user_id}, JTI: {g.access_jti})")
    return jsonify(logged_in_as=g.current_user.username, user_id=g.current_user_id, access_token_jti=g.access_jti), 200