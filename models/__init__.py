"""Database models. Importing them here registers their tables with SQLAlchemy.

Stage 3: ServiceCategory and Service.   Stage 4: User.   Stage 5: Booking.   Stage 6: provider_services (which provider offers which service).
Later stages add provider profiles, working-hours availability and Review.
"""
from models.booking import Booking
from models.provider import provider_services
from models.service import Service, ServiceCategory
from models.user import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_PROVIDER, ROLES, User

__all__ = ["Booking", "provider_services", "ROLE_ADMIN", "ROLE_CUSTOMER", "ROLE_PROVIDER", "ROLES", "Service", "ServiceCategory", "User"]
