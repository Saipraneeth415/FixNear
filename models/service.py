"""Service catalogue models: ServiceCategory and Service.

One category has many services; every service belongs to exactly one category.
"""
from sqlalchemy import true

from extensions import db
from models.mixins import TimestampMixin
from models.provider import provider_services


class ServiceCategory(TimestampMixin, db.Model):
    """A group of services, such as Plumbing or Home Cleaning."""

    __tablename__ = "service_categories"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(60), nullable=False, unique=True)  # used in URLs: ?category=plumbing
    name = db.Column(db.String(100), nullable=False)
    icon = db.Column(db.String(30), nullable=False, default="wrench")  # key in services/icons.py
    blurb = db.Column(db.String(255), nullable=False, default="")
    sort_order = db.Column(db.Integer, nullable=False, default=0)  # lower numbers appear first

    services = db.relationship("Service", back_populates="category", order_by="Service.id")

    def __repr__(self):
        return f"<ServiceCategory {self.slug}>"


class Service(TimestampMixin, db.Model):
    """A bookable service. In Stage 6 the provider_* text moves to a provider profile table."""

    __tablename__ = "services"
    __table_args__ = (db.CheckConstraint("price_from >= 0", name="price_nonnegative"),)

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(100), nullable=False, unique=True)  # used in URLs: /services/<slug>
    name = db.Column(db.String(150), nullable=False)
    category_id = db.Column(
        db.Integer,
        db.ForeignKey("service_categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    summary = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price_from = db.Column(db.Integer, nullable=False)  # starting price in rupees
    duration = db.Column(db.String(50), nullable=False)
    includes = db.Column(db.JSON, nullable=False, default=list)  # list of strings

    provider_name = db.Column(db.String(120), nullable=False)
    provider_area = db.Column(db.String(120), nullable=False)
    provider_bio = db.Column(db.Text, nullable=False, default="")

    # True for development sample data. Real services will set this to False.
    is_sample = db.Column(db.Boolean, nullable=False, default=True)

    # False hides the service from the site and blocks new bookings. The
    # server_default fills in "true" for services that already exist.
    is_available = db.Column(db.Boolean, nullable=False, default=True, server_default=true())

    category = db.relationship("ServiceCategory", back_populates="services")
    bookings = db.relationship("Booking", back_populates="service")
    providers = db.relationship("User", secondary=provider_services, back_populates="offered_services")

    @property
    def category_slug(self):
        return self.category.slug

    def __repr__(self):
        return f"<Service {self.slug}>"
