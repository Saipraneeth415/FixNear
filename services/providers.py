"""Linking provider accounts to the services they offer."""
from sqlalchemy import select

from extensions import db
from models.service import Service
from models.user import ROLE_PROVIDER, User
from services.security import normalize_email


def get_provider_by_email(email):
    """The provider account with this email, or None (customers and admins are not providers)."""
    email = normalize_email(email)
    if not email:
        return None
    return db.session.scalar(select(User).where(User.email == email, User.role == ROLE_PROVIDER))


def get_service_by_slug(slug):
    """Any service by slug, including ones hidden from the public site."""
    if not slug:
        return None
    return db.session.scalar(select(Service).where(Service.slug == slug))


def offered_services(provider):
    return list(provider.offered_services)


def grant_service(provider, service):
    """Let this provider offer this service. Returns False if they already did."""
    if provider is None or provider.role != ROLE_PROVIDER:
        raise ValueError("Only provider accounts can offer services.")
    if service is None:
        raise ValueError("Unknown service.")
    if service in provider.offered_services:
        return False
    provider.offered_services.append(service)
    db.session.commit()
    return True


def revoke_service(provider, service):
    """Stop this provider offering this service. Existing bookings are not changed."""
    if provider is None or service is None or service not in provider.offered_services:
        return False
    provider.offered_services.remove(service)
    db.session.commit()
    return True
