"""What a provider can see and do with bookings assigned to them.

Every lookup is filtered by the logged-in provider, so another provider's
booking (or an unassigned one) looks exactly like a booking that does not exist.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from extensions import db
from models.booking import Booking
from models.user import ROLE_PROVIDER
from services import booking_rules as rules
from services import bookings, scheduling
from services.errors import BookingPermissionError, BookingRuleError, SchedulingConflictError


def get_provider_booking(provider, reference):
    """The booking with this reference IF it is assigned to this provider, else None."""
    reference = (reference or "").strip().upper()
    if not rules.is_valid_reference(reference):
        return None
    stmt = (
        select(Booking)
        .options(joinedload(Booking.service))
        .where(Booking.reference == reference, Booking.provider_id == provider.id)
    )
    return db.session.scalar(stmt)


def list_provider_bookings(provider, statuses=None, newest_first=False, limit=None):
    """This provider's bookings. Soonest appointment first, unless newest_first."""
    stmt = select(Booking).options(joinedload(Booking.service)).where(Booking.provider_id == provider.id)
    if statuses:
        stmt = stmt.where(Booking.status.in_(list(statuses)))
    if newest_first:
        stmt = stmt.order_by(Booking.appointment_date.desc(), Booking.appointment_time.desc(), Booking.id.desc())
    else:
        stmt = stmt.order_by(Booking.appointment_date, Booking.appointment_time, Booking.id)
    if limit:
        stmt = stmt.limit(limit)
    return list(db.session.scalars(stmt))


def status_counts(provider):
    counts = {status: 0 for status in rules.STATUSES}
    rows = db.session.execute(
        select(Booking.status, func.count(Booking.id)).where(Booking.provider_id == provider.id).group_by(Booking.status)
    )
    for status, number in rows:
        counts[status] = number
    return counts


def provider_stats(provider):
    counts = status_counts(provider)
    return {
        "total": sum(counts.values()),
        "pending": counts[rules.STATUS_PENDING],
        "accepted": counts[rules.STATUS_ACCEPTED],
        "in_progress": counts[rules.STATUS_IN_PROGRESS],
        "completed": counts[rules.STATUS_COMPLETED],
    }


def perform_action(booking, provider, action):
    """Accept, reject, start or complete one of the provider's own bookings.

    Returns True if the status changed, False if the booking was already in the
    requested status (so a double click is harmless). Raises:
      BookingPermissionError  not a provider, or the booking is someone else's
      InvalidTransitionError  the workflow does not allow this change
      SchedulingConflictError accepting would clash with another committed job
    """
    if provider is None or provider.role != ROLE_PROVIDER or not provider.is_active:
        raise BookingPermissionError("Only provider accounts can do this.")
    if booking.provider_id != provider.id:
        raise BookingPermissionError("This booking is not assigned to you.")

    target = rules.PROVIDER_ACTIONS.get(action)
    if target is None:
        raise BookingRuleError("Unknown action.")
    if booking.status == target:
        return False

    bookings.check_transition(booking, target)  # re-checked against the CURRENT status in the database

    if target == rules.STATUS_ACCEPTED:
        clash = scheduling.find_conflict(
            provider.id, booking.appointment_date, booking.appointment_time,
            exclude_booking_id=booking.id, statuses=rules.COMMITTED_STATUSES,
        )
        if clash is not None:
            raise SchedulingConflictError("You already have a job around that time, so you cannot accept this one.")

    bookings.transition_status(booking, target)
    return True
