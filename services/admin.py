"""Admin: dashboard numbers, user management and the all-bookings view.

Every function that CHANGES something starts by checking that the actor is an
active administrator, so these rules hold no matter which page or request calls them.
"""
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from extensions import db
from models.booking import Booking
from models.service import Service
from models.user import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_PROVIDER, ROLES, User
from services import admin_rules
from services import booking_rules as rules
from services.errors import AdminPermissionError, AdminRuleError

MAX_SEARCH_LENGTH = 100


def require_admin(actor):
    """Raise AdminPermissionError unless actor is a logged-in, active administrator."""
    if (
        actor is None
        or not getattr(actor, "is_authenticated", False)
        or getattr(actor, "role", None) != ROLE_ADMIN
        or not getattr(actor, "is_active", False)
    ):
        raise AdminPermissionError("Administrator access is required.")


def _clean_search(value):
    return " ".join(str(value or "").split())[:MAX_SEARCH_LENGTH]


# ---------------------------------------------------------------- dashboard
def dashboard_counts():
    """Live numbers straight from the database. Nothing is cached or typed in."""
    role_totals = {role: 0 for role in ROLES}
    for role, number in db.session.execute(select(User.role, func.count(User.id)).group_by(User.role)):
        role_totals[role] = number

    status_totals = {status: 0 for status in rules.STATUSES}
    for status, number in db.session.execute(select(Booking.status, func.count(Booking.id)).group_by(Booking.status)):
        status_totals[status] = number

    def count(stmt):
        return db.session.scalar(stmt) or 0

    return {
        "users": sum(role_totals.values()),
        "customers": role_totals[ROLE_CUSTOMER],
        "providers": role_totals[ROLE_PROVIDER],
        "admins": role_totals[ROLE_ADMIN],
        "inactive_users": count(select(func.count(User.id)).where(User.is_active.is_(False))),
        "services": count(select(func.count(Service.id))),
        "services_available": count(select(func.count(Service.id)).where(Service.is_available.is_(True))),
        "bookings": sum(status_totals.values()),
        "pending": status_totals[rules.STATUS_PENDING],
        "accepted": status_totals[rules.STATUS_ACCEPTED],
        "in_progress": status_totals[rules.STATUS_IN_PROGRESS],
        "completed": status_totals[rules.STATUS_COMPLETED],
    }


# -------------------------------------------------------------------- users
def get_user(user_id):
    return db.session.get(User, user_id)


def list_users(role="", status="", q="", page=1, per_page=admin_rules.PAGE_SIZE):
    """Users, filtered and paginated. Unknown filter values are ignored. Returns (users, page_info)."""
    conditions = []
    if role in ROLES:
        conditions.append(User.role == role)
    if status == "active":
        conditions.append(User.is_active.is_(True))
    elif status == "inactive":
        conditions.append(User.is_active.is_(False))
    q = _clean_search(q).lower()
    if q:
        conditions.append(or_(func.lower(User.email).contains(q, autoescape=True), func.lower(User.full_name).contains(q, autoescape=True)))

    total = db.session.scalar(select(func.count(User.id)).where(*conditions)) or 0
    info = admin_rules.paginate(total, page, per_page)
    stmt = select(User).where(*conditions).order_by(User.id).limit(info["per_page"]).offset(info["offset"])
    return list(db.session.scalars(stmt)), info


def _active_assigned_bookings(provider_id):
    return db.session.scalar(
        select(func.count(Booking.id)).where(Booking.provider_id == provider_id, Booking.status.in_(rules.ACTIVE_STATUSES))
    ) or 0


def set_user_active(actor, target, new_is_active):
    """Activate or deactivate an account. Returns the number of active bookings still assigned
    to a provider who was just deactivated (0 in every other case), so the page can warn.

    Refused: deactivating yourself, deactivating the last active administrator, or
    changing nothing. Roles are never changed here.
    """
    require_admin(actor)
    if target is None:
        raise AdminRuleError("That user does not exist.")

    other_active_admins = db.session.scalar(
        select(func.count(User.id)).where(User.role == ROLE_ADMIN, User.is_active.is_(True), User.id != target.id)
    ) or 0
    problem = admin_rules.user_status_problem(
        actor.id, target.id, target.role, target.is_active, bool(new_is_active), other_active_admins
    )
    if problem:
        raise AdminRuleError(problem)

    target.is_active = bool(new_is_active)
    db.session.commit()
    if not new_is_active and target.role == ROLE_PROVIDER:
        return _active_assigned_bookings(target.id)
    return 0


# ----------------------------------------------------------------- bookings
def providers_for_filter():
    return list(db.session.scalars(select(User).where(User.role == ROLE_PROVIDER).order_by(User.full_name, User.id)))


def services_for_filter():
    """Every service, including hidden ones, so old bookings can still be found."""
    return list(db.session.scalars(select(Service).order_by(Service.name, Service.id)))


def list_bookings(status="", service_slug="", provider="", q="", page=1, per_page=admin_rules.PAGE_SIZE):
    """All bookings, newest first, filtered and paginated. Returns (bookings, page_info).

    status      one of the booking statuses
    service_slug  a service's address name
    provider    "unassigned", or a provider's account number
    q           part of a reference, or part of the customer's name or email
    Unknown or malformed filter values are ignored.
    """
    conditions = []
    if status in rules.STATUSES:
        conditions.append(Booking.status == status)
    if admin_rules.is_valid_slug(service_slug):
        conditions.append(Booking.service_id.in_(select(Service.id).where(Service.slug == service_slug)))
    provider = str(provider or "").strip()
    if provider == "unassigned":
        conditions.append(Booking.provider_id.is_(None))
    elif provider.isascii() and provider.isdigit() and len(provider) < 10:
        conditions.append(Booking.provider_id == int(provider))
    q = _clean_search(q)
    if q:
        lowered = q.lower()
        customer_ids = select(User.id).where(
            or_(func.lower(User.email).contains(lowered, autoescape=True), func.lower(User.full_name).contains(lowered, autoescape=True))
        )
        conditions.append(or_(Booking.reference.startswith(q.upper(), autoescape=True), Booking.customer_id.in_(customer_ids)))

    total = db.session.scalar(select(func.count(Booking.id)).where(*conditions)) or 0
    info = admin_rules.paginate(total, page, per_page)
    stmt = (
        select(Booking)
        .options(joinedload(Booking.customer), joinedload(Booking.provider), joinedload(Booking.service))
        .where(*conditions)
        .order_by(Booking.created_at.desc(), Booking.id.desc())
        .limit(info["per_page"])
        .offset(info["offset"])
    )
    return list(db.session.scalars(stmt)), info
