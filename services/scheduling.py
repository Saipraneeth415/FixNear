"""Provider availability, conflict checks and automatic assignment.

Availability here means "not already booked": a provider is free for a new
booking if none of their ACTIVE bookings on that day starts less than 2 hours
before or after it (see JOB_BLOCK_MINUTES in booking_rules.py).

Not covered yet: working hours and days off. That needs its own table and is
left for a later stage.
"""
from sqlalchemy import func, select

from extensions import db
from models.booking import Booking
from models.provider import provider_services
from models.user import ROLE_PROVIDER, User
from services import booking_rules as rules
from services.errors import NoProviderAvailableError


def find_conflict(provider_id, appointment_date, appointment_time, *, exclude_booking_id=None, statuses=rules.ACTIVE_STATUSES):
    """Another booking of this provider that clashes with the given time, or None.

    statuses decides which bookings count. By default every active booking
    (pending, accepted, in progress) blocks the time.
    """
    stmt = select(Booking).where(
        Booking.provider_id == provider_id,
        Booking.appointment_date == appointment_date,
        Booking.status.in_(statuses),
    )
    if exclude_booking_id is not None:
        stmt = stmt.where(Booking.id != exclude_booking_id)
    for other in db.session.scalars(stmt):
        if rules.times_conflict(other.appointment_time, appointment_time):
            return other
    return None


def providers_offering(service):
    """Active provider accounts that offer this service, oldest account first."""
    stmt = (
        select(User)
        .join(provider_services, provider_services.c.provider_id == User.id)
        .where(
            provider_services.c.service_id == service.id,
            User.role == ROLE_PROVIDER,
            User.is_active.is_(True),
        )
        .order_by(User.id)
    )
    return list(db.session.scalars(stmt))


def active_job_counts(provider_ids, appointment_date):
    """{provider_id: number of active jobs on that day}. Providers with no jobs are left out."""
    if not provider_ids:
        return {}
    rows = db.session.execute(
        select(Booking.provider_id, func.count(Booking.id))
        .where(
            Booking.provider_id.in_(list(provider_ids)),
            Booking.appointment_date == appointment_date,
            Booking.status.in_(rules.ACTIVE_STATUSES),
        )
        .group_by(Booking.provider_id)
    )
    # Build the dictionary row by row. Do NOT write dict(rows): a query Result has a
    # keys() method, so dict() would treat it like a mapping and fail with
    # "'ChunkedIteratorResult' object is not subscriptable".
    return {provider_id: job_count for provider_id, job_count in rows}


def choose_provider(service, appointment_date, appointment_time):
    """Pick the provider for a new booking.

    * No provider offers the service  -> None (the booking stays unassigned).
    * Providers offer it but all are busy -> NoProviderAvailableError.
    * Otherwise the free provider with the fewest active jobs that day
      (the lowest account number breaks ties), so work is spread out.

    Customers never choose; this runs on the server only.
    """
    offering = providers_offering(service)
    if not offering:
        return None

    free = [p for p in offering if find_conflict(p.id, appointment_date, appointment_time) is None]
    if not free:
        raise NoProviderAvailableError("No provider is available for that date and time. Please choose another time.")

    loads = active_job_counts([p.id for p in free], appointment_date)
    return min(free, key=lambda p: (loads.get(p.id, 0), p.id))


def assign_existing(booking):
    """Try to give an unassigned Pending booking a provider. Returns the provider or None.

    Used by `flask assign-pending` for bookings made before any provider
    offered the service. It never touches a booking that already has a provider
    or has left Pending.
    """
    if booking.provider_id is not None or booking.status != rules.STATUS_PENDING:
        return None
    try:
        provider = choose_provider(booking.service, booking.appointment_date, booking.appointment_time)
    except NoProviderAvailableError:
        return None
    if provider is None:
        return None
    booking.provider_id = provider.id
    db.session.commit()
    return provider
