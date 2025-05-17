from .extensions import db
from datetime import datetime, timezone
import bcrypt


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Связи
    listings = db.relationship('Listing', backref='owner', lazy=True, cascade="all, delete-orphan")
    bookings = db.relationship('Booking', backref='renter', lazy=True, cascade="all, delete-orphan")
    favorites = db.relationship('Favorite', backref='user', lazy=True, cascade="all, delete-orphan")
    reviews_given = db.relationship('Review', foreign_keys='Review.user_id', backref='reviewer', lazy=True,
                                    cascade="all, delete-orphan")

    def set_password(self, password):
        salt = bcrypt.gensalt()
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    def check_password(self, password):
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))

    def __repr__(self):
        return f'<User {self.username}>'


class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)

    parent = db.relationship('Category', remote_side=[id], backref=db.backref('subcategories'))
    listings = db.relationship('Listing', backref='category', lazy=True)

    def __repr__(self):
        return f'<Category {self.name}>'


class Listing(db.Model):
    __tablename__ = 'listings'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    price_per_day = db.Column(db.Numeric(10, 2), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)  # Покажем при бронировании
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    # Связи
    images = db.relationship('ListingImage', backref='listing', lazy=True, cascade="all, delete-orphan")
    bookings = db.relationship('Booking', backref='listing', lazy=True, cascade="all, delete-orphan")
    favorites = db.relationship('Favorite', backref='listing', lazy=True, cascade="all, delete-orphan")
    reviews = db.relationship('Review', backref='listing', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Listing {self.title}>'


class ListingImage(db.Model):
    __tablename__ = 'listing_images'
    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey('listings.id'), nullable=False)
    image_url = db.Column(db.String(255), nullable=False)  # URL или путь в Minio
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<ListingImage {self.image_url} for listing {self.listing_id}>'


class Booking(db.Model):
    __tablename__ = 'bookings'
    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey('listings.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # Кто бронирует
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # status (e.g., pending, confirmed, cancelled) - можно добавить позже

    def __repr__(self):
        return f'<Booking {self.id} for listing {self.listing_id} by user {self.user_id}>'


class Favorite(db.Model):  # Many-to-Many через ассоциативную таблицу
    __tablename__ = 'favorites'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    listing_id = db.Column(db.Integer, db.ForeignKey('listings.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.UniqueConstraint('user_id', 'listing_id', name='_user_listing_uc'),)

    def __repr__(self):
        return f'<Favorite by user {self.user_id} for listing {self.listing_id}>'


class Review(db.Model):
    __tablename__ = 'reviews'
    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey('listings.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # Кто оставил отзыв
    rating = db.Column(db.Integer, nullable=False)  # e.g., 1-5
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Ограничение: один пользователь - один отзыв на объявление
    __table_args__ = (db.UniqueConstraint('user_id', 'listing_id', name='_user_listing_review_uc'),
                      db.CheckConstraint('rating >= 1 AND rating <= 5', name='rating_check'))

    def __repr__(self):
        return f'<Review {self.id} for listing {self.listing_id} by user {self.user_id}>'


class RefreshToken(db.Model):
    __tablename__ = 'refresh_tokens'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token_jti = db.Column(db.String(36), unique=True, nullable=False)  # JTI (JWT ID) для токена
    revoked = db.Column(db.Boolean, default=False, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)

    user = db.relationship('User', backref=db.backref('refresh_tokens_assc', lazy=True, cascade="all, delete-orphan"))

    def __repr__(self):
        return f'<RefreshToken {self.token_jti} for user {self.user_id}>'