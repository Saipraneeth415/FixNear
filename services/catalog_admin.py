"""Admin: create, edit and delete service categories and services - safely.

The safety rules:
  * A SERVICE with bookings is never deleted (history must stay intact). Hide it instead.
  * A CATEGORY that still has services is never deleted.
  * Deleting an unused service also removes its provider links, so no provider is left
    "offering" something that no longer exists.
  * Addresses (slugs) are fixed once created, so saved links and bookmarks keep working.
All of this is enforced here, on the server, whatever the form sent.
"""
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from extensions import db
from models.booking import Booking
from models.service import Service, ServiceCategory
from services import admin_rules
from services import booking_rules as rules
from services.admin import require_admin
from services.errors import AdminRuleError
from services.icons import ICON_NAMES

CATEGORY_NAME = (2, 100)
SERVICE_NAME = (3, 150)
MAX_BLURB = 255
MAX_SUMMARY = 255
MAX_DESCRIPTION = 5000
MAX_DURATION = 50
MAX_PROVIDER_FIELD = 120
MAX_BIO = 2000
MAX_PRICE = 1_000_000
MAX_SORT_ORDER = 999


def _line(value):
    return rules.clean_line(value)


def _in_range(label, value, low, high):
    if not low <= len(value) <= high:
        raise AdminRuleError(f"{label} must be between {low} and {high} characters.")


def _commit():
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise AdminRuleError("Those details clash with an existing record. Check that the address (slug) is unique.") from None


def _whole_number(label, value, low, high):
    try:
        if isinstance(value, bool):
            raise ValueError
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise AdminRuleError(f"{label} must be a whole number.") from None
    if not low <= number <= high:
        raise AdminRuleError(f"{label} must be between {low} and {high}.")
    return number


# ---------------------------------------------------------------- listings
def categories_with_counts():
    """[(category, number_of_services)] in display order. Hidden services are counted too."""
    counts = {}
    for category_id, number in db.session.execute(select(Service.category_id, func.count(Service.id)).group_by(Service.category_id)):
        counts[category_id] = number
    categories = db.session.scalars(select(ServiceCategory).order_by(ServiceCategory.sort_order, ServiceCategory.id))
    return [(category, counts.get(category.id, 0)) for category in categories]


def services_with_counts():
    """[(service, number_of_bookings)] including hidden services, in display order."""
    counts = {}
    for service_id, number in db.session.execute(select(Booking.service_id, func.count(Booking.id)).group_by(Booking.service_id)):
        counts[service_id] = number
    stmt = select(Service).join(Service.category).order_by(ServiceCategory.sort_order, ServiceCategory.id, Service.id)
    return [(service, counts.get(service.id, 0)) for service in db.session.scalars(stmt)]


def booking_count(service):
    return db.session.scalar(select(func.count(Booking.id)).where(Booking.service_id == service.id)) or 0


def active_booking_count(service):
    return db.session.scalar(
        select(func.count(Booking.id)).where(Booking.service_id == service.id, Booking.status.in_(rules.ACTIVE_STATUSES))
    ) or 0


def service_count(category):
    return db.session.scalar(select(func.count(Service.id)).where(Service.category_id == category.id)) or 0


# -------------------------------------------------------------- categories
def _category_values(name, icon, blurb, sort_order):
    name, blurb = _line(name), _line(blurb)
    _in_range("The name", name, *CATEGORY_NAME)
    if icon not in ICON_NAMES:
        raise AdminRuleError("Choose one of the listed icons.")
    if not 1 <= len(blurb) <= MAX_BLURB:
        raise AdminRuleError(f"The description must be between 1 and {MAX_BLURB} characters.")
    return {"name": name, "icon": icon, "blurb": blurb, "sort_order": _whole_number("The display order", sort_order, 0, MAX_SORT_ORDER)}


def create_category(actor, *, slug, name, icon, blurb, sort_order):
    require_admin(actor)
    slug = (slug or "").strip()
    if not admin_rules.is_valid_slug(slug) or len(slug) > 60:
        raise AdminRuleError("The address must be lower-case letters, digits and single hyphens (up to 60 characters).")
    if db.session.scalar(select(ServiceCategory.id).where(ServiceCategory.slug == slug)) is not None:
        raise AdminRuleError("A category with that address already exists.")
    category = ServiceCategory(slug=slug, **_category_values(name, icon, blurb, sort_order))
    db.session.add(category)
    _commit()
    return category


def update_category(actor, category, *, name, icon, blurb, sort_order):
    require_admin(actor)
    for key, value in _category_values(name, icon, blurb, sort_order).items():
        setattr(category, key, value)
    _commit()
    return category


def delete_category(actor, category):
    require_admin(actor)
    in_use = service_count(category)
    if in_use:
        raise AdminRuleError(f"This category still has {in_use} service(s). Move or delete them first.")
    db.session.delete(category)
    _commit()


# ---------------------------------------------------------------- services
def _service_values(*, name, category_id, summary, description, price_from, duration, includes, provider_name,
                    provider_area, provider_bio, is_available, is_sample):
    name, summary, duration = _line(name), _line(summary), _line(duration)
    provider_name, provider_area = _line(provider_name), _line(provider_area)
    description, provider_bio = rules.clean_multiline(description), rules.clean_multiline(provider_bio)
    _in_range("The name", name, *SERVICE_NAME)
    if not 1 <= len(summary) <= MAX_SUMMARY:
        raise AdminRuleError(f"The summary must be between 1 and {MAX_SUMMARY} characters.")
    if not 1 <= len(description) <= MAX_DESCRIPTION:
        raise AdminRuleError(f"The description must be between 1 and {MAX_DESCRIPTION} characters.")
    if not 1 <= len(duration) <= MAX_DURATION:
        raise AdminRuleError(f"The usual time must be between 1 and {MAX_DURATION} characters.")
    for label, value in (("The provider name", provider_name), ("The provider area", provider_area)):
        if not 1 <= len(value) <= MAX_PROVIDER_FIELD:
            raise AdminRuleError(f"{label} must be between 1 and {MAX_PROVIDER_FIELD} characters.")
    if len(provider_bio) > MAX_BIO:
        raise AdminRuleError(f"The provider bio must be at most {MAX_BIO} characters.")

    items = admin_rules.parse_includes(includes) if isinstance(includes, str) else [_line(item) for item in includes if _line(item)]
    problem = admin_rules.includes_problem(items)
    if problem:
        raise AdminRuleError(problem)

    try:
        category = db.session.get(ServiceCategory, int(category_id))
    except (TypeError, ValueError):
        category = None
    if category is None:
        raise AdminRuleError("Choose a category.")

    return {
        "name": name, "category": category, "summary": summary, "description": description,
        "price_from": _whole_number("The starting price", price_from, 0, MAX_PRICE), "duration": duration,
        "includes": items, "provider_name": provider_name, "provider_area": provider_area, "provider_bio": provider_bio,
        "is_available": bool(is_available), "is_sample": bool(is_sample),
    }


def create_service(actor, *, slug, **fields):
    require_admin(actor)
    slug = (slug or "").strip()
    if not admin_rules.is_valid_slug(slug):
        raise AdminRuleError("The address must be lower-case letters, digits and single hyphens (up to 100 characters).")
    if db.session.scalar(select(Service.id).where(Service.slug == slug)) is not None:
        raise AdminRuleError("A service with that address already exists.")
    service = Service(slug=slug, **_service_values(**fields))
    db.session.add(service)
    _commit()
    return service


def update_service(actor, service, **fields):
    """Edit a service. Its address (slug) cannot change. Existing bookings keep the price they were made at."""
    require_admin(actor)
    for key, value in _service_values(**fields).items():
        setattr(service, key, value)
    _commit()
    return service


def set_service_available(actor, service, available):
    """Show or hide a service. Hidden services take no new bookings; existing bookings are untouched.

    Returns how many active bookings the service has (so the page can mention them).
    """
    require_admin(actor)
    service.is_available = bool(available)
    _commit()
    return active_booking_count(service)


def delete_service(actor, service):
    require_admin(actor)
    used = booking_count(service)
    if used:
        raise AdminRuleError(f"This service has {used} booking(s), so it cannot be deleted. Hide it instead to stop new bookings.")
    service.providers.clear()  # no provider is left offering a service that no longer exists
    db.session.delete(service)
    _commit()
