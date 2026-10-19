"""The User model: one table for customers, providers and administrators."""
from flask_login import UserMixin
from sqlalchemy.exc import SQLAlchemyError

from extensions import db, login_manager
from models.mixins import TimestampMixin
from models.provider import provider_services
from services.passwords import hash_password, verify_password

ROLE_CUSTOMER = "customer"
ROLE_PROVIDER = "provider"
ROLE_ADMIN = "admin"
ROLES = (ROLE_CUSTOMER, ROLE_PROVIDER, ROLE_ADMIN)


class User(UserMixin, TimestampMixin, db.Model):
    """An account. Only a password HASH is stored, never the password itself."""

    __tablename__ = "users"
    __table_args__ = (
        # The database itself refuses unknown roles and mixed-case emails.
        db.CheckConstraint("role IN ('customer', 'provider', 'admin')", name="role_valid"),
        db.CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), nullable=False, unique=True)
    full_name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_CUSTOMER, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)  # False = suspended
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Bookings this user made as a customer.
    bookings = db.relationship("Booking", back_populates="customer", foreign_keys="Booking.customer_id")

    # Services this user offers when their role is provider.
    offered_services = db.relationship("Service", secondary=provider_services, back_populates="providers", order_by="Service.id")

    def set_password(self, password):
        self.password_hash = hash_password(password)

    def check_password(self, password):
        return verify_password(self.password_hash, password)

    @property
    def is_customer(self):
        return self.role == ROLE_CUSTOMER

    @property
    def is_provider(self):
        return self.role == ROLE_PROVIDER

    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    def __repr__(self):  # never include the password hash
        return f"<User {self.email} ({self.role})>"


@login_manager.user_loader
def load_user(user_id):
    """Called on every request that carries a login session cookie."""
    try:
        user = db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
    except SQLAlchemyError:
        # If the database is down, treat the visitor as logged out so that
        # error pages can still be shown.
        db.session.rollback()
        return None
    if user is None or not user.is_active:  # deleted or suspended accounts are logged out
        return None
    return user
