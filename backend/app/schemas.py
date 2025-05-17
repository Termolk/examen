from .extensions import ma
from .models import User, Category, Listing, ListingImage, Booking, Favorite, Review


class UserSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = User
        load_instance = True
        exclude = ("password_hash", "refresh_tokens_assc")  # Не отправляем хеш пароля и токены
        load_only = ("password",)  # Поле "password" только для загрузки (при регистрации)

    # Добавляем поле password для регистрации (не из модели)
    password = ma.String(required=True, load_only=True)


class CategorySchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = Category
        load_instance = True
        include_relationships = True  # Для отображения subcategories

    subcategories = ma.List(ma.Nested('self', exclude=('parent',)))  # Рекурсивная схема для подкатегорий


class ListingImageSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = ListingImage
        load_instance = True
        # exclude = ("listing_id",) # Можно исключить, если всегда в контексте Listing


class ReviewSchema(ma.SQLAlchemyAutoSchema):
    user = ma.Nested(UserSchema, only=("id", "username"))

    class Meta:
        model = Review
        load_instance = True
        include_fk = True
        exclude = ("listing",) # <--- ДОБАВЬТЕ ЭТУ СТРОКУ


class ListingSchema(ma.SQLAlchemyAutoSchema):
    owner = ma.Nested(UserSchema, only=("id", "username"))  # Показываем только id и username владельца
    category = ma.Nested(CategorySchema, only=("id", "name"))
    images = ma.List(ma.Nested(ListingImageSchema, only=("id", "image_url")))
    reviews = ma.List(
        ma.Nested(ReviewSchema, exclude=("listing",)))  # Исключаем обратную ссылку на listing чтобы не было цикла

    class Meta:
        model = Listing
        load_instance = True
        include_relationships = True
        # exclude = ("user_id", "category_id") # Уже есть вложенные owner и category


class BookingSchema(ma.SQLAlchemyAutoSchema):
    renter = ma.Nested(UserSchema, only=("id", "username"))
    listing = ma.Nested(ListingSchema,
                        only=("id", "title", "phone_number"))  # При получении бронирования показываем телефон

    class Meta:
        model = Booking
        load_instance = True
        include_relationships = True
        include_fk = True  # Включаем user_id, listing_id для создания


class FavoriteSchema(ma.SQLAlchemyAutoSchema):
    user = ma.Nested(UserSchema, only=("id", "username"))
    listing = ma.Nested(ListingSchema, only=("id", "title"))

    class Meta:
        model = Favorite
        load_instance = True
        include_relationships = True


# Схемы для запросов (могут отличаться от схем ответа)
class RegisterSchema(ma.Schema):
    username = ma.String(required=True)
    password = ma.String(required=True)
    confirm_password = ma.String(required=True)


class LoginSchema(ma.Schema):
    username = ma.String(required=True)
    password = ma.String(required=True)


class CreateListingSchema(ma.Schema):
    title = ma.String(required=True)
    description = ma.String()
    category_id = ma.Integer(required=True)
    price_per_day = ma.Decimal(required=True, places=2)
    phone_number = ma.String(required=True)  # Владелец сам указывает свой номер
    is_active = ma.Boolean()


class CreateBookingSchema(ma.Schema):
    start_date = ma.Date(required=True)
    end_date = ma.Date(required=True)


class CreateReviewSchema(ma.Schema):
    rating = ma.Integer(required=True, validate=lambda n: 1 <= n <= 5)
    comment = ma.String()


class CreateCategorySchema(ma.Schema):
    name = ma.String(required=True)
    parent_id = ma.Integer(allow_none=True)