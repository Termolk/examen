from flask import Blueprint, request, jsonify, current_app, g
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy import and_, or_  # exists не используется явно, но может быть полезен для сложных запросов в будущем
from datetime import date, datetime, timezone
import uuid

from ..models import db, User, Category, Listing, ListingImage, Booking, Favorite, Review
from ..schemas import (
    CategorySchema, CreateCategorySchema,
    ListingSchema, CreateListingSchema, ListingImageSchema,
    BookingSchema, CreateBookingSchema,
    FavoriteSchema,
    ReviewSchema, CreateReviewSchema
)
from ..utils.jwt_utils import jwt_required
from ..services.minio_service import upload_file_to_minio, delete_file_from_minio, get_presigned_url_for_minio
from marshmallow import ValidationError

# Импорт кастомных метрик
from ..extensions import (
    LISTINGS_CREATED_COUNTER,
    BOOKINGS_CREATED_COUNTER,
    REVIEWS_CREATED_COUNTER,
    CURRENT_LISTINGS_GAUGE
    # Добавьте другие метрики из extensions.py, если они специфичны для items
)

bp = Blueprint('items', __name__)

# --- Схемы ---
category_schema = CategorySchema()
categories_schema = CategorySchema(many=True)
create_category_schema = CreateCategorySchema()

listing_schema = ListingSchema()
listings_schema = ListingSchema(many=True)
create_listing_schema = CreateListingSchema()
listing_image_schema = ListingImageSchema()

booking_schema = BookingSchema()
bookings_schema = BookingSchema(many=True)
create_booking_schema = CreateBookingSchema()

favorite_schema = FavoriteSchema()
favorites_schema = FavoriteSchema(many=True)

review_schema = ReviewSchema()
reviews_schema = ReviewSchema(many=True)
create_review_schema = CreateReviewSchema()


# --- Категории ---

@bp.route('/categories', methods=['POST'])
@jwt_required
def create_category():
    json_data = request.get_json()
    if not json_data:
        current_app.logger.warning(f"User {g.current_user_id}: Create category attempt with missing JSON data.")
        return jsonify({"msg": "Missing JSON in request"}), 400

    try:
        data = create_category_schema.load(json_data)
    except ValidationError as err:
        current_app.logger.warning(f"User {g.current_user_id}: Create category validation error: {err.messages}")
        return jsonify(err.messages), 422

    current_app.logger.info(
        f"User {g.current_user_id} attempting to create category: '{data['name']}' with parent_id: {data.get('parent_id')}")
    new_category = Category(name=data['name'], parent_id=data.get('parent_id'))

    try:
        db.session.add(new_category)
        db.session.commit()
        current_app.logger.info(
            f"Category '{new_category.name}' (ID: {new_category.id}) created successfully by user {g.current_user_id}.")
        return jsonify(category_schema.dump(new_category)), 201
    except IntegrityError:
        db.session.rollback()
        current_app.logger.warning(
            f"User {g.current_user_id}: Create category failed for name '{data['name']}': already exists or invalid parent_id.")
        return jsonify({"msg": "Category with this name already exists or invalid parent_id"}), 409
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"User {g.current_user_id}: Error creating category '{data['name']}': {e}",
                                 exc_info=True)
        return jsonify({"msg": "Could not create category"}), 500


@bp.route('/categories', methods=['GET'])
def get_categories():
    current_app.logger.info("Fetching all top-level categories with subcategories.")
    try:
        top_level_categories_query = db.select(Category).where(Category.parent_id.is_(None)) \
            .options(selectinload(Category.subcategories).selectinload(Category.subcategories))

        top_level_categories_result = db.session.execute(top_level_categories_query)
        result = categories_schema.dump(top_level_categories_result.scalars().all())
        current_app.logger.debug(f"Successfully fetched {len(result)} top-level categories.")
        return jsonify(result), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching categories: {e}", exc_info=True)
        return jsonify({"msg": "Could not fetch categories"}), 500


@bp.route('/categories/<int:category_id>', methods=['GET'])
def get_category(category_id):
    current_app.logger.info(f"Fetching category with ID: {category_id}.")
    try:
        category_query = db.select(Category).where(Category.id == category_id) \
            .options(selectinload(Category.subcategories).selectinload(Category.subcategories))
        category_result = db.session.execute(category_query)
        category = category_result.scalar_one_or_none()

        if category:
            current_app.logger.debug(f"Category ID {category_id} ('{category.name}') found.")
            return jsonify(category_schema.dump(category)), 200
        else:
            current_app.logger.warning(f"Category with ID {category_id} not found.")
            return jsonify({"msg": "Category not found"}), 404
    except Exception as e:
        current_app.logger.error(f"Error fetching category {category_id}: {e}", exc_info=True)
        return jsonify({"msg": "Could not fetch category"}), 500


@bp.route('/categories/<int:category_id>', methods=['PUT'])
@jwt_required
def update_category(category_id):
    json_data = request.get_json()
    if not json_data:
        current_app.logger.warning(
            f"User {g.current_user_id}: Update category {category_id} attempt with missing JSON data.")
        return jsonify({"msg": "Missing JSON in request"}), 400

    current_app.logger.info(
        f"User {g.current_user_id} attempting to update category ID: {category_id} with data: {json_data}")
    try:
        data = create_category_schema.load(json_data, partial=True)
    except ValidationError as err:
        current_app.logger.warning(
            f"User {g.current_user_id}: Update category {category_id} validation error: {err.messages}")
        return jsonify(err.messages), 422

    category_to_update = db.session.get(Category, category_id)
    if not category_to_update:
        current_app.logger.warning(
            f"User {g.current_user_id}: Update category failed. Category ID {category_id} not found.")
        return jsonify({"msg": "Category not found"}), 404

    if 'parent_id' in data and data.get('parent_id') == category_id:
        current_app.logger.warning(
            f"User {g.current_user_id}: Update category {category_id} failed. Category cannot be its own parent.")
        return jsonify({"msg": "Category cannot be its own parent"}), 400

    # TODO: Добавить проверку на циклические зависимости, если parent_id изменяется

    original_name = category_to_update.name
    original_parent_id = category_to_update.parent_id

    if 'name' in data:
        category_to_update.name = data['name']
    if 'parent_id' in data:
        category_to_update.parent_id = data.get('parent_id')

    try:
        db.session.commit()
        current_app.logger.info(
            f"Category ID {category_id} (Old name: '{original_name}', New name: '{category_to_update.name}') updated successfully by user {g.current_user_id}.")
        return jsonify(category_schema.dump(category_to_update)), 200
    except IntegrityError:
        db.session.rollback()
        current_app.logger.warning(
            f"User {g.current_user_id}: Update category {category_id} failed. Name conflict or invalid parent_id.")
        return jsonify({"msg": "Category name conflict or invalid parent_id"}), 409
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"User {g.current_user_id}: Error updating category {category_id}: {e}", exc_info=True)
        return jsonify({"msg": "Could not update category"}), 500


@bp.route('/categories/<int:category_id>', methods=['DELETE'])
@jwt_required
def delete_category(category_id):
    current_app.logger.info(f"User {g.current_user_id} attempting to delete category ID: {category_id}.")
    category_to_delete = db.session.get(Category, category_id)
    if not category_to_delete:
        current_app.logger.warning(
            f"User {g.current_user_id}: Delete category failed. Category ID {category_id} not found.")
        return jsonify({"msg": "Category not found"}), 404

    category_name_for_log = category_to_delete.name

    has_subcategories_query = db.select(Category.id).where(Category.parent_id == category_id).limit(1)
    has_subcategories = (db.session.execute(has_subcategories_query)).scalar_one_or_none()

    has_listings_query = db.select(Listing.id).where(Listing.category_id == category_id).limit(1)
    has_listings = (db.session.execute(has_listings_query)).scalar_one_or_none()

    if has_subcategories or has_listings:
        msg = "Cannot delete category with subcategories or listings. Please reassign them first."
        current_app.logger.warning(
            f"User {g.current_user_id}: Delete category '{category_name_for_log}' (ID: {category_id}) failed. Reason: {msg}")
        return jsonify({"msg": msg}), 400

    try:
        db.session.delete(category_to_delete)
        db.session.commit()
        current_app.logger.info(
            f"Category '{category_name_for_log}' (ID: {category_id}) deleted successfully by user {g.current_user_id}.")
        return jsonify({"msg": "Category deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"User {g.current_user_id}: Error deleting category '{category_name_for_log}' (ID: {category_id}): {e}",
            exc_info=True)
        return jsonify({"msg": "Could not delete category"}), 500


# --- Объявления (Listings) ---

@bp.route('/listings', methods=['POST'])
@jwt_required
def create_listing():
    json_data = request.get_json()
    if not json_data:
        current_app.logger.warning(f"User {g.current_user_id}: Create listing attempt with missing JSON data.")
        return jsonify({"msg": "Missing JSON in request"}), 400

    try:
        data = create_listing_schema.load(json_data)
    except ValidationError as err:
        current_app.logger.warning(f"User {g.current_user_id}: Create listing validation error: {err.messages}")
        return jsonify(err.messages), 422

    current_app.logger.info(
        f"User {g.current_user_id} attempting to create listing with title: '{data.get('title', 'N/A')}' in category ID: {data['category_id']}")
    category_exists = db.session.get(Category, data['category_id'])
    if not category_exists:
        current_app.logger.warning(
            f"User {g.current_user_id}: Create listing attempt with non-existent category ID: {data['category_id']}")
        return jsonify({"msg": f"Category with id {data['category_id']} not found"}), 404

    new_listing = Listing(
        title=data['title'],
        description=data.get('description'),
        user_id=g.current_user_id,
        category_id=data['category_id'],
        price_per_day=data['price_per_day'],
        phone_number=data['phone_number'],
        is_active=data.get('is_active', True)  # По умолчанию активно
    )

    try:
        db.session.add(new_listing)
        db.session.commit()

        category_name = category_exists.name if category_exists else "unknown"
        LISTINGS_CREATED_COUNTER.labels(category_name=category_name).inc()
        CURRENT_LISTINGS_GAUGE.inc()

        current_app.logger.info(
            f"Listing '{new_listing.title}' (ID: {new_listing.id}) created successfully by user {g.current_user_id} in category '{category_name}'.")
        return jsonify(listing_schema.dump(new_listing)), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"User {g.current_user_id}: Error creating listing with title '{data.get('title', 'N/A')}': {e}",
            exc_info=True)
        return jsonify({"msg": "Could not create listing"}), 500


@bp.route('/listings/<int:listing_id>/images', methods=['POST'])
@jwt_required
def upload_listing_image(listing_id):
    current_app.logger.info(f"User {g.current_user_id} attempting to upload image for listing ID: {listing_id}.")
    listing = db.session.get(Listing, listing_id)
    if not listing:
        current_app.logger.warning(
            f"User {g.current_user_id}: Image upload attempt for non-existent listing ID: {listing_id}")
        return jsonify({"msg": "Listing not found"}), 404

    if listing.user_id != g.current_user_id:
        current_app.logger.error(
            f"User {g.current_user_id} FORBIDDEN to upload image for listing {listing_id} (owner: {listing.user_id}).")
        return jsonify({"msg": "Forbidden: You are not the owner of this listing"}), 403

    if 'image' not in request.files:
        current_app.logger.warning(
            f"User {g.current_user_id}: Image upload for listing {listing_id} with no image file provided.")
        return jsonify({"msg": "No image file provided"}), 400

    file = request.files['image']
    if file.filename == '':
        current_app.logger.warning(
            f"User {g.current_user_id}: Image upload for listing {listing_id} with no selected file (empty filename).")
        return jsonify({"msg": "No selected file"}), 400

    current_app.logger.info(
        f"User {g.current_user_id}: Processing image upload '{file.filename}' for listing {listing_id}.")

    file_extension = ''
    if '.' in file.filename:
        file_extension = file.filename.rsplit('.', 1)[1].lower()

    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif'}
    if file_extension not in allowed_extensions:
        current_app.logger.warning(
            f"User {g.current_user_id}: Image upload for listing {listing_id} with invalid file type: '{file_extension}'. Allowed: {allowed_extensions}")
        return jsonify({"msg": f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"}), 400

    object_name = f"listings/{listing_id}/{uuid.uuid4()}.{file_extension}"

    try:
        # upload_file_to_minio уже логирует и инкрементирует метрики MinIO (MINIO_UPLOADS_TOTAL, MINIO_UPLOAD_ERRORS_TOTAL)
        upload_file_to_minio(file, object_name, content_type=file.content_type)

        new_image = ListingImage(listing_id=listing_id, image_url=object_name)
        db.session.add(new_image)
        db.session.commit()

        presigned_url = get_presigned_url_for_minio(object_name)
        current_app.logger.info(
            f"Image for listing {listing_id} (DB ID: {new_image.id}, MinIO object: {object_name}) metadata saved to DB by user {g.current_user_id}.")
        return jsonify({
            "msg": "Image uploaded successfully",
            "image_id": new_image.id,
            "image_path": new_image.image_url,
            "presigned_url": presigned_url
        }), 201

    except Exception as e:  # Это может быть ошибка от MinIO (уже залогированная там) или ошибка DB commit
        db.session.rollback()  # Откатываем только запись ListingImage в БД
        current_app.logger.error(
            f"User {g.current_user_id}: Error saving image record to DB for listing {listing_id} (MinIO object: {object_name}) after potential MinIO upload: {e}",
            exc_info=True)
        # Метрика ошибки MinIO уже должна была сработать в minio_service
        return jsonify({"msg": "Could not save image record to database"}), 500


@bp.route('/listings', methods=['GET'])
def get_listings():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    category_id_filter = request.args.get('category_id', type=int)
    search_term = request.args.get('search', type=str)
    user_id_filter = request.args.get('user_id', type=int)

    current_app.logger.info(
        f"Fetching listings. Page: {page}, PerPage: {per_page}, CategoryID: {category_id_filter}, Search: '{search_term}', UserID: {user_id_filter}")

    query = db.select(Listing).where(Listing.is_active == True) \
        .options(
        joinedload(Listing.owner).load_only(User.id, User.username),
        joinedload(Listing.category).load_only(Category.id, Category.name),
        selectinload(Listing.images).load_only(ListingImage.id, ListingImage.image_url)
    )

    if category_id_filter:
        query = query.where(Listing.category_id == category_id_filter)
    if user_id_filter:
        query = query.where(Listing.user_id == user_id_filter)
    if search_term:
        query = query.where(
            or_(
                Listing.title.ilike(f"%{search_term}%"),
                Listing.description.ilike(f"%{search_term}%")
            )
        )

    query = query.order_by(Listing.created_at.desc())

    try:
        paginated_listings_result = db.paginate(query, page=page, per_page=per_page, error_out=False)
        current_app.logger.debug(
            f"Fetched {len(paginated_listings_result.items)} listings for page {page}. Total: {paginated_listings_result.total}")

        processed_items = []
        for listing_item in paginated_listings_result.items:
            item_dump = listing_schema.dump(listing_item)
            if item_dump.get('images'):
                for img in item_dump['images']:
                    if img.get('image_url'):
                        try:
                            img['presigned_url'] = get_presigned_url_for_minio(img['image_url'])
                        except Exception as e_minio:
                            current_app.logger.error(
                                f"Failed to get presigned URL for image '{img['image_url']}' of listing ID {listing_item.id}: {e_minio}",
                                exc_info=False)  # exc_info=False to reduce noise for common error
                            img['presigned_url'] = None
            processed_items.append(item_dump)

        return jsonify({
            "items": processed_items,
            "total": paginated_listings_result.total,
            "page": paginated_listings_result.page,
            "per_page": paginated_listings_result.per_page,
            "pages": paginated_listings_result.pages
        }), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching listings: {e}", exc_info=True)
        return jsonify({"msg": "Could not fetch listings"}), 500


@bp.route('/listings/<int:listing_id>', methods=['GET'])
def get_listing_detail(listing_id):
    current_app.logger.info(f"Fetching details for listing ID: {listing_id}.")
    try:
        listing_query = db.select(Listing).where(Listing.id == listing_id) \
            .options(
            joinedload(Listing.owner).load_only(User.id, User.username),
            joinedload(Listing.category).load_only(Category.id, Category.name),
            selectinload(Listing.images).load_only(ListingImage.id, ListingImage.image_url),
            selectinload(Listing.reviews).options(
                joinedload(Review.reviewer).load_only(User.id, User.username)
            )
        )
        listing_result = db.session.execute(listing_query)
        listing = listing_result.scalar_one_or_none()

        if listing:
            if not listing.is_active:
                # Consider if owner should see their inactive listings via this public endpoint
                current_app.logger.warning(f"Attempt to access inactive listing ID: {listing_id}.")
                return jsonify({"msg": "Listing not found or is not active"}), 404

            current_app.logger.debug(f"Listing ID {listing_id} ('{listing.title}') found.")
            listing_data = listing_schema.dump(listing)

            if listing_data.get('images'):
                for img_data in listing_data['images']:
                    if img_data.get('image_url'):
                        try:
                            img_data['presigned_url'] = get_presigned_url_for_minio(img_data['image_url'])
                        except Exception as e_minio:
                            current_app.logger.error(
                                f"Failed to get presigned URL for image '{img_data['image_url']}' of listing ID {listing_id}: {e_minio}",
                                exc_info=False)
                            img_data['presigned_url'] = None
            return jsonify(listing_data), 200
        else:
            current_app.logger.warning(f"Listing with ID {listing_id} not found.")
            return jsonify({"msg": "Listing not found"}), 404
    except Exception as e:
        current_app.logger.error(f"Error fetching listing details for ID {listing_id}: {e}", exc_info=True)
        return jsonify({"msg": "Could not fetch listing details"}), 500


@bp.route('/listings/<int:listing_id>', methods=['PUT'])
@jwt_required
def update_listing(listing_id):
    json_data = request.get_json()
    if not json_data:
        current_app.logger.warning(
            f"User {g.current_user_id}: Update listing {listing_id} attempt with missing JSON data.")
        return jsonify({"msg": "Missing JSON in request"}), 400

    current_app.logger.info(
        f"User {g.current_user_id} attempting to update listing ID: {listing_id}. Data: {json_data}")
    listing_to_update = db.session.get(Listing, listing_id)
    if not listing_to_update:
        current_app.logger.warning(
            f"User {g.current_user_id}: Update listing failed. Listing ID {listing_id} not found.")
        return jsonify({"msg": "Listing not found"}), 404

    if listing_to_update.user_id != g.current_user_id:
        current_app.logger.error(
            f"User {g.current_user_id} FORBIDDEN to update listing {listing_id} (owner: {listing_to_update.user_id}).")
        return jsonify({"msg": "Forbidden: You are not the owner of this listing"}), 403

    try:
        data = CreateListingSchema(partial=True).load(json_data)
    except ValidationError as err:
        current_app.logger.warning(
            f"User {g.current_user_id}: Update listing {listing_id} validation error: {err.messages}")
        return jsonify(err.messages), 422

    if 'category_id' in data:
        category_exists = db.session.get(Category, data['category_id'])
        if not category_exists:
            current_app.logger.warning(
                f"User {g.current_user_id}: Update listing {listing_id} attempt with non-existent category ID: {data['category_id']}")
            return jsonify({"msg": f"Category with id {data['category_id']} not found"}), 404
        listing_to_update.category_id = data['category_id']
        current_app.logger.info(
            f"User {g.current_user_id}: Listing {listing_id} category updated to ID {data['category_id']}.")

    updated_fields = []
    for field, value in data.items():
        if field == 'category_id': continue  # Already handled
        if hasattr(listing_to_update, field):
            old_value = getattr(listing_to_update, field)
            if old_value != value:
                setattr(listing_to_update, field, value)
                updated_fields.append(f"{field}: from '{old_value}' to '{value}'")

    listing_to_update.updated_at = datetime.now(timezone.utc)

    try:
        db.session.commit()
        current_app.logger.info(
            f"Listing ID {listing_id} (Title: '{listing_to_update.title}') updated successfully by user {g.current_user_id}. Changes: [{'; '.join(updated_fields)}]")
        return jsonify(listing_schema.dump(listing_to_update)), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"User {g.current_user_id}: Error updating listing {listing_id}: {e}", exc_info=True)
        return jsonify({"msg": "Could not update listing"}), 500


@bp.route('/listings/<int:listing_id>', methods=['DELETE'])
@jwt_required
def delete_listing(listing_id):
    current_app.logger.info(f"User {g.current_user_id} attempting to delete listing ID: {listing_id}.")
    listing_to_delete = db.session.get(Listing, listing_id, options=[selectinload(Listing.images)])
    if not listing_to_delete:
        current_app.logger.warning(
            f"User {g.current_user_id}: Delete listing failed. Listing ID {listing_id} not found.")
        return jsonify({"msg": "Listing not found"}), 404

    if listing_to_delete.user_id != g.current_user_id:
        current_app.logger.error(
            f"User {g.current_user_id} FORBIDDEN to delete listing {listing_id} (owner: {listing_to_delete.user_id}).")
        return jsonify({"msg": "Forbidden: You are not the owner of this listing"}), 403

    title_for_log = listing_to_delete.title
    current_app.logger.info(
        f"User {g.current_user_id}: Proceeding with deletion of listing '{title_for_log}' (ID: {listing_id}).")

    # TODO: Проверка на активные бронирования

    try:
        for image in listing_to_delete.images:
            try:
                current_app.logger.info(
                    f"User {g.current_user_id}: Deleting image {image.image_url} from MinIO for listing {listing_id}.")
                delete_file_from_minio(
                    image.image_url)  # Эта функция уже логирует свои ошибки и не должна останавливать процесс если ошибка MinIO
            except Exception as e_minio_ignored:  # Ловим все, чтобы не прервать удаление из БД
                current_app.logger.error(
                    f"User {g.current_user_id}: Exception during MinIO image deletion for {image.image_url} (listing {listing_id}), but proceeding with DB deletion: {e_minio_ignored}",
                    exc_info=True)

        db.session.delete(listing_to_delete)
        db.session.commit()
        CURRENT_LISTINGS_GAUGE.dec()
        current_app.logger.info(
            f"Listing '{title_for_log}' (ID: {listing_id}) and associated images/bookings/reviews/favorites deleted successfully from DB by user {g.current_user_id}.")
        return jsonify({"msg": "Listing and associated data deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"User {g.current_user_id}: Error deleting listing '{title_for_log}' (ID: {listing_id}) from DB: {e}",
            exc_info=True)
        return jsonify({"msg": "Could not delete listing"}), 500


@bp.route('/listings/<int:listing_id>/images/<int:image_id>', methods=['DELETE'])
@jwt_required
def delete_listing_image(listing_id, image_id):
    current_app.logger.info(
        f"User {g.current_user_id} attempting to delete image ID: {image_id} for listing ID: {listing_id}.")
    listing = db.session.get(Listing, listing_id)
    if not listing:
        current_app.logger.warning(f"User {g.current_user_id}: Delete image failed. Listing ID {listing_id} not found.")
        return jsonify({"msg": "Listing not found"}), 404

    if listing.user_id != g.current_user_id:
        current_app.logger.error(
            f"User {g.current_user_id} FORBIDDEN to delete image {image_id} for listing {listing_id} (owner: {listing.user_id}).")
        return jsonify({"msg": "Forbidden: You are not the owner of this listing"}), 403

    image_to_delete = db.session.get(ListingImage, image_id)
    if not image_to_delete or image_to_delete.listing_id != listing_id:
        current_app.logger.warning(
            f"User {g.current_user_id}: Delete image failed. Image ID {image_id} not found or does not belong to listing {listing_id}.")
        return jsonify({"msg": "Image not found or does not belong to this listing"}), 404

    image_url_for_log = image_to_delete.image_url
    current_app.logger.info(
        f"User {g.current_user_id}: Proceeding with deletion of image '{image_url_for_log}' (DB ID: {image_id}) for listing {listing_id}.")

    try:
        delete_file_from_minio(image_to_delete.image_url)  # Уже логирует
        db.session.delete(image_to_delete)
        db.session.commit()
        current_app.logger.info(
            f"Image '{image_url_for_log}' (DB ID: {image_id}) for listing {listing_id} deleted successfully from DB and MinIO by user {g.current_user_id}.")
        return jsonify({"msg": "Image deleted successfully"}), 200
    except Exception as e:  # Ошибка может быть от MinIO (если там raise) или DB
        db.session.rollback()
        current_app.logger.error(
            f"User {g.current_user_id}: Error deleting image '{image_url_for_log}' (DB ID: {image_id}) for listing {listing_id}: {e}",
            exc_info=True)
        return jsonify({"msg": "Could not delete image"}), 500


# --- Бронирования ---

@bp.route('/listings/<int:listing_id>/book', methods=['POST'])
@jwt_required
def create_booking(listing_id):
    current_app.logger.info(f"User {g.current_user_id} attempting to create booking for listing ID: {listing_id}.")
    listing = db.session.get(Listing, listing_id)
    if not listing:
        current_app.logger.warning(
            f"User {g.current_user_id}: Create booking failed. Listing ID {listing_id} not found.")
        return jsonify({"msg": "Listing not found"}), 404

    if not listing.is_active:
        current_app.logger.warning(
            f"User {g.current_user_id}: Create booking failed for listing {listing_id}. Listing is not active.")
        return jsonify({"msg": "Listing is not active and cannot be booked"}), 400

    if listing.user_id == g.current_user_id:
        current_app.logger.warning(
            f"User {g.current_user_id} (owner) attempted to book their own listing ID: {listing_id}.")
        return jsonify({"msg": "You cannot book your own listing"}), 400

    json_data = request.get_json()
    if not json_data:
        current_app.logger.warning(
            f"User {g.current_user_id}: Create booking for listing {listing_id} attempt with missing JSON data.")
        return jsonify({"msg": "Missing JSON in request"}), 400

    try:
        data = create_booking_schema.load(json_data)
        start_date_req = data['start_date']
        end_date_req = data['end_date']
    except ValidationError as err:
        current_app.logger.warning(
            f"User {g.current_user_id}: Create booking for listing {listing_id} validation error: {err.messages}")
        return jsonify(err.messages), 422

    current_app.logger.info(
        f"User {g.current_user_id}: Validated booking request for listing {listing_id} (Title: '{listing.title}') from {start_date_req} to {end_date_req}.")

    if start_date_req < date.today():
        current_app.logger.warning(
            f"User {g.current_user_id}: Create booking for listing {listing_id} failed. Start date {start_date_req} is in the past.")
        return jsonify({"msg": "Booking start date cannot be in the past"}), 400
    if end_date_req < start_date_req:
        current_app.logger.warning(
            f"User {g.current_user_id}: Create booking for listing {listing_id} failed. End date {end_date_req} is before start date {start_date_req}.")
        return jsonify({"msg": "Booking end date cannot be before start date"}), 400

    conflict_query = db.select(Booking.id).where(
        Booking.listing_id == listing_id,
        Booking.start_date <= end_date_req,
        Booking.end_date >= start_date_req
    ).limit(1)
    if (db.session.execute(conflict_query)).scalar_one_or_none():
        current_app.logger.warning(
            f"User {g.current_user_id}: Create booking for listing {listing_id} failed. Listing already booked for dates {start_date_req}-{end_date_req}.")
        return jsonify({"msg": "Listing is already booked for the selected dates"}), 409

    new_booking = Booking(
        listing_id=listing_id,
        user_id=g.current_user_id,
        start_date=start_date_req,
        end_date=end_date_req
    )

    try:
        db.session.add(new_booking)
        db.session.commit()
        BOOKINGS_CREATED_COUNTER.inc()
        current_app.logger.info(
            f"Booking ID {new_booking.id} for listing {listing_id} (Dates: {start_date_req} to {end_date_req}) created successfully by user {g.current_user_id}.")

        refreshed_booking_result = db.session.execute(
            db.select(Booking).where(Booking.id == new_booking.id)
            .options(joinedload(Booking.listing), joinedload(Booking.renter))
        )
        booking_data = booking_schema.dump(refreshed_booking_result.scalar_one())

        return jsonify({
            "msg": "Booking created successfully",
            "booking": booking_data,
            "owner_phone_number": listing.phone_number
        }), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"User {g.current_user_id}: Error creating booking for listing {listing_id}: {e}",
                                 exc_info=True)
        return jsonify({"msg": "Could not create booking"}), 500


@bp.route('/my-bookings', methods=['GET'])
@jwt_required
def get_my_bookings():
    current_app.logger.info(f"User {g.current_user_id} fetching their bookings.")
    try:
        bookings_query = db.select(Booking).where(Booking.user_id == g.current_user_id) \
            .options(
            joinedload(Booking.listing).options(
                joinedload(Listing.category).load_only(Category.id, Category.name),
                joinedload(Listing.owner).load_only(User.id, User.username),
                selectinload(Listing.images).load_only(ListingImage.id, ListingImage.image_url)
            )) \
            .order_by(Booking.start_date.desc())

        user_bookings_result = db.session.execute(bookings_query)
        bookings_data_list = user_bookings_result.scalars().all()
        bookings_data = bookings_schema.dump(bookings_data_list)
        current_app.logger.debug(f"User {g.current_user_id} fetched {len(bookings_data_list)} bookings.")

        for booking_item in bookings_data:
            if booking_item.get('listing') and booking_item['listing'].get('images'):
                for img in booking_item['listing']['images']:
                    if img.get('image_url'):
                        try:
                            img['presigned_url'] = get_presigned_url_for_minio(img['image_url'])
                        except Exception as e_minio:
                            current_app.logger.error(
                                f"Failed to get presigned URL for image '{img['image_url']}' in my-bookings for user {g.current_user_id}: {e_minio}",
                                exc_info=False)
                            img['presigned_url'] = None
        return jsonify(bookings_data), 200
    except Exception as e:
        current_app.logger.error(f"User {g.current_user_id}: Error fetching their bookings: {e}", exc_info=True)
        return jsonify({"msg": "Could not fetch your bookings"}), 500


@bp.route('/my-listings-bookings', methods=['GET'])
@jwt_required
def get_my_listings_bookings():
    current_app.logger.info(f"User {g.current_user_id} fetching bookings for their listings.")
    try:
        user_listing_ids_query = db.select(Listing.id).where(Listing.user_id == g.current_user_id)
        user_listing_ids_result = db.session.execute(user_listing_ids_query)
        listing_ids = user_listing_ids_result.scalars().all()

        if not listing_ids:
            current_app.logger.info(f"User {g.current_user_id} has no listings, so no bookings on their listings.")
            return jsonify([]), 200

        bookings_query = db.select(Booking).where(Booking.listing_id.in_(listing_ids)) \
            .options(
            joinedload(Booking.listing).load_only(Listing.id, Listing.title),
            joinedload(Booking.renter).load_only(User.id, User.username)
        ) \
            .order_by(Booking.listing_id, Booking.start_date.desc())

        listings_bookings_result = db.session.execute(bookings_query)
        bookings_list = listings_bookings_result.scalars().all()
        current_app.logger.debug(f"User {g.current_user_id} fetched {len(bookings_list)} bookings on their listings.")
        return jsonify(bookings_schema.dump(bookings_list)), 200
    except Exception as e:
        current_app.logger.error(f"User {g.current_user_id}: Error fetching bookings for their listings: {e}",
                                 exc_info=True)
        return jsonify({"msg": "Could not fetch bookings for your listings"}), 500


# --- Избранное ---

@bp.route('/listings/<int:listing_id>/favorite', methods=['POST'])
@jwt_required
def toggle_favorite(listing_id):
    current_app.logger.info(
        f"User {g.current_user_id} attempting to toggle favorite status for listing ID: {listing_id}.")
    listing = db.session.get(Listing, listing_id)
    if not listing:
        current_app.logger.warning(
            f"User {g.current_user_id}: Toggle favorite failed. Listing ID {listing_id} not found.")
        return jsonify({"msg": "Listing not found"}), 404

    if not listing.is_active:
        current_app.logger.warning(
            f"User {g.current_user_id}: Toggle favorite for listing {listing_id} failed. Listing is not active.")
        return jsonify({"msg": "Cannot favorite an inactive listing"}), 400

    existing_favorite_query = db.select(Favorite).where(
        Favorite.user_id == g.current_user_id,
        Favorite.listing_id == listing_id
    )
    favorite_entry_result = db.session.execute(existing_favorite_query)
    favorite_entry = favorite_entry_result.scalar_one_or_none()

    try:
        if favorite_entry:
            db.session.delete(favorite_entry)
            db.session.commit()
            current_app.logger.info(f"User {g.current_user_id}: Listing ID {listing_id} removed from favorites.")
            return jsonify({"msg": "Removed from favorites"}), 200
        else:
            new_favorite = Favorite(user_id=g.current_user_id, listing_id=listing_id)
            db.session.add(new_favorite)
            db.session.commit()
            current_app.logger.info(
                f"User {g.current_user_id}: Listing ID {listing_id} added to favorites. Favorite ID: {new_favorite.id}")

            refreshed_favorite_result = db.session.execute(
                db.select(Favorite).where(Favorite.id == new_favorite.id)
                .options(joinedload(Favorite.listing), joinedload(Favorite.user))
            )
            return jsonify(favorite_schema.dump(refreshed_favorite_result.scalar_one())), 201
    except IntegrityError:  # Should ideally not happen with the check above, but good for safety
        db.session.rollback()
        current_app.logger.warning(
            f"User {g.current_user_id}: Toggle favorite for listing {listing_id} resulted in IntegrityError (e.g. race condition).")
        return jsonify({"msg": "Action already performed or conflict."}), 409
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"User {g.current_user_id}: Error toggling favorite for listing {listing_id}: {e}",
                                 exc_info=True)
        return jsonify({"msg": "Could not update favorites"}), 500


@bp.route('/my-favorites', methods=['GET'])
@jwt_required
def get_my_favorites():
    current_app.logger.info(f"User {g.current_user_id} fetching their favorite listings.")
    try:
        favorites_query = db.select(Favorite).where(Favorite.user_id == g.current_user_id) \
            .options(joinedload(Favorite.listing).options(
            joinedload(Listing.category).load_only(Category.id, Category.name),
            joinedload(Listing.owner).load_only(User.id, User.username),
            selectinload(Listing.images).load_only(ListingImage.id, ListingImage.image_url)
        )) \
            .order_by(Favorite.created_at.desc())

        user_favorites_result = db.session.execute(favorites_query)
        favorites_list = user_favorites_result.scalars().all()
        favorites_data = favorites_schema.dump(favorites_list)
        current_app.logger.debug(f"User {g.current_user_id} fetched {len(favorites_list)} favorite listings.")

        for fav_item in favorites_data:
            if fav_item.get('listing') and fav_item['listing'].get('images'):
                for img in fav_item['listing']['images']:
                    if img.get('image_url'):
                        try:
                            img['presigned_url'] = get_presigned_url_for_minio(img['image_url'])
                        except Exception as e_minio:
                            current_app.logger.error(
                                f"Failed to get presigned URL for image '{img['image_url']}' in my-favorites for user {g.current_user_id}: {e_minio}",
                                exc_info=False)
                            img['presigned_url'] = None
        return jsonify(favorites_data), 200
    except Exception as e:
        current_app.logger.error(f"User {g.current_user_id}: Error fetching their favorites: {e}", exc_info=True)
        return jsonify({"msg": "Could not fetch your favorites"}), 500


# --- Отзывы ---

@bp.route('/listings/<int:listing_id>/reviews', methods=['POST'])
@jwt_required
def create_review(listing_id):
    current_app.logger.info(f"User {g.current_user_id} attempting to create review for listing ID: {listing_id}.")
    listing = db.session.get(Listing, listing_id)
    if not listing:
        current_app.logger.warning(
            f"User {g.current_user_id}: Create review failed. Listing ID {listing_id} not found.")
        return jsonify({"msg": "Listing not found"}), 404

    if not listing.is_active:
        current_app.logger.warning(
            f"User {g.current_user_id}: Create review for listing {listing_id} failed. Listing is not active.")
        return jsonify({"msg": "Cannot review an inactive listing"}), 400

    if listing.user_id == g.current_user_id:
        current_app.logger.warning(
            f"User {g.current_user_id} (owner) attempted to review their own listing ID: {listing_id}.")
        return jsonify({"msg": "You cannot review your own listing"}), 403

    json_data = request.get_json()
    if not json_data:
        current_app.logger.warning(
            f"User {g.current_user_id}: Create review for listing {listing_id} attempt with missing JSON data.")
        return jsonify({"msg": "Missing JSON in request"}), 400

    try:
        data = create_review_schema.load(json_data)
    except ValidationError as err:
        current_app.logger.warning(
            f"User {g.current_user_id}: Create review for listing {listing_id} validation error: {err.messages}")
        return jsonify(err.messages), 422

    current_app.logger.info(
        f"User {g.current_user_id}: Validated review for listing {listing_id} (Title: '{listing.title}') with rating {data['rating']}.")

    # TODO: Условие для оставления отзыва (проверить, что пользователь бронировал и бронирование завершилось)

    new_review = Review(
        listing_id=listing_id,
        user_id=g.current_user_id,
        rating=data['rating'],
        comment=data.get('comment')
    )

    try:
        db.session.add(new_review)
        db.session.commit()
        REVIEWS_CREATED_COUNTER.inc()
        current_app.logger.info(
            f"Review ID {new_review.id} for listing {listing_id} (Rating: {data['rating']}) created successfully by user {g.current_user_id}.")

        refreshed_review_result = db.session.execute(
            db.select(Review).where(Review.id == new_review.id)
            .options(joinedload(Review.reviewer), joinedload(Review.listing))
            # listing здесь для полноты, но может быть исключен схемой
        )
        return jsonify(review_schema.dump(refreshed_review_result.scalar_one())), 201
    except IntegrityError:  # Это сработает из-за UniqueConstraint('user_id', 'listing_id')
        db.session.rollback()
        current_app.logger.warning(
            f"User {g.current_user_id}: Create review for listing {listing_id} failed. Already reviewed or integrity error.")
        return jsonify({"msg": "You have already reviewed this listing or another integrity error occurred."}), 409
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"User {g.current_user_id}: Error creating review for listing {listing_id}: {e}",
                                 exc_info=True)
        return jsonify({"msg": "Could not create review"}), 500


@bp.route('/listings/<int:listing_id>/reviews', methods=['GET'])
def get_listing_reviews(listing_id):
    current_app.logger.info(f"Fetching reviews for listing ID: {listing_id}.")
    listing_exists_check = db.session.get(Listing, listing_id)
    if not listing_exists_check:
        current_app.logger.warning(f"Fetching reviews failed. Listing ID {listing_id} not found.")
        return jsonify({"msg": "Listing not found"}), 404

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 5, type=int)
    current_app.logger.debug(f"Fetching reviews for listing {listing_id}. Page: {page}, PerPage: {per_page}")

    reviews_query = db.select(Review).where(Review.listing_id == listing_id) \
        .options(joinedload(Review.reviewer).load_only(User.id, User.username)) \
        .order_by(Review.created_at.desc())

    try:
        paginated_reviews_result = db.paginate(reviews_query, page=page, per_page=per_page, error_out=False)
        current_app.logger.debug(
            f"Fetched {len(paginated_reviews_result.items)} reviews for listing {listing_id}, page {page}. Total: {paginated_reviews_result.total}")
        return jsonify({
            "items": reviews_schema.dump(paginated_reviews_result.items),
            "total": paginated_reviews_result.total,
            "page": paginated_reviews_result.page,
            "per_page": paginated_reviews_result.per_page,
            "pages": paginated_reviews_result.pages
        }), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching reviews for listing {listing_id}: {e}", exc_info=True)
        return jsonify({"msg": "Could not fetch reviews"}), 500


@bp.route('/my-reviews', methods=['GET'])
@jwt_required
async def get_my_reviews():  # Используем async, т.к. в оригинале был, хотя для SQLAlchemy это не обязательно без async-драйвера
    current_app.logger.info(f"User {g.current_user_id} fetching their reviews.")
    try:
        reviews_query = db.select(Review).where(Review.user_id == g.current_user_id) \
            .options(joinedload(Review.listing).load_only(Listing.id, Listing.title)) \
            .order_by(Review.created_at.desc())

        # Если используете Flask-SQLAlchemy < 3.1 с асинхронным контекстом Flask, execute может быть не awaitable напрямую
        # Для стандартной синхронной SQLAlchemy с Flask, await не нужен.
        # Оставляем await, если планируется переход на async SQLAlchemy драйвер.
        # Если нет, можно убрать await и сделать функцию синхронной.
        # Для текущей конфигурации (синхронной), await здесь не нужен и может вызвать ошибку если db.session.execute не async.
        # Убираем await для совместимости с текущей синхронной настройкой.
        user_reviews_result = db.session.execute(reviews_query)  # Убрано await
        reviews_list = user_reviews_result.scalars().all()
        current_app.logger.debug(f"User {g.current_user_id} fetched {len(reviews_list)} reviews written by them.")
        return jsonify(reviews_schema.dump(reviews_list)), 200
    except Exception as e:
        current_app.logger.error(f"User {g.current_user_id}: Error fetching their reviews: {e}", exc_info=True)
        return jsonify({"msg": "Could not fetch your reviews"}), 500