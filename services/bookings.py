"""Creating, reading and cancelling bookings. All booking rules are enforced HERE,
on the server, no matter what the browser sends."""
from datetime import datetime, timezone

from flask import current_app
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from extensions import db
from models.booking import Booking
from models.user import ROLE_CUSTOMER
from services import booking_rules as rules
from services import scheduling
from services.errors import (  # noqa: F401  (re-exported for existing callers)
    BookingPermissionError,
    BookingReferenceError,
    BookingRuleError,
    InvalidTransitionError,
    NoProviderAvailableError,
    SchedulingConflictError,
)

MAX_REFERENCE_ATTEMPTS = 5
NAME_LIMITS = (2, 100)
ADDRESS_LIMITS = (10, 300)
DESCRIPTION_LIMITS = (10, 1000)
REASON_MAX_LENGTH = 300


def now_local():
    return rules.local_now(current_app.config.get("BOOKING_UTC_OFFSET_MINUTES", 330))


# ------------------------------------------------------------------ reading
def get_customer_booking(customer, reference):
    """The customer's OWN booking with this reference, or None.

    Someone else's booking is treated exactly like a missing one, so the site
    never confirms that another customer's reference exists.
    """
    reference = (reference or "").strip().upper()
    if not rules.is_valid_reference(reference):
        return None
    stmt = (
        select(Booking)
        .options(joinedload(Booking.service))
        .where(Booking.reference == reference, Booking.customer_id == customer.id)
    )
    return db.session.scalar(stmt)


def list_customer_bookings(customer, status=None, limit=None):
    stmt = (
        select(Booking)
        .options(joinedload(Booking.service))
        .where(Booking.customer_id == customer.id)
        .order_by(Booking.created_at.desc(), Booking.id.desc())
    )
    if status in rules.STATUSES:
        stmt = stmt.where(Booking.status == status)
    if limit:
        stmt = stmt.limit(limit)
    return list(db.session.scalars(stmt))


def status_counts(customer):
    """{status: number} for this customer, with a zero for every status."""
    counts = {status: 0 for status in rules.STATUSES}
    rows = db.session.execute(
        select(Booking.status, func.count(Booking.id)).where(Booking.customer_id == customer.id).group_by(Booking.status)
    )
    for status, number in rows:
        counts[status] = number
    return counts


def booking_stats(customer):
    counts = status_counts(customer)
    return {
        "total": sum(counts.values()),
        "pending": counts[rules.STATUS_PENDING],
        "accepted": counts[rules.STATUS_ACCEPTED],
        "completed": counts[rules.STATUS_COMPLETED],
    }


def _find_by_token(customer_id, token):
    if not token:
        return None
    return db.session.scalar(select(Booking).where(Booking.customer_id == customer_id, Booking.submission_token == token))


# ----------------------------------------------------------------- creating
def _check_length(label, value, limits):
    low, high = limits
    if not low <= len(value) <= high:
        raise BookingRuleError(f"{label} must be between {low} and {high} characters.")


def create_booking(customer, service, *, contact_name, contact_phone, address, appointment_date,
                   appointment_time, problem_description, submission_token=None, now=None):
    """Save a new booking. Returns (booking, created).

    created is False when this exact form submission was already saved (for
    example a double click), in which case the existing booking is returned.

    The status is always Pending, the provider is chosen by the server (or left
    empty if no provider offers the service), the price comes from the service
    and the customer is the logged-in user. Nothing about those is read from
    the request.
    """
    if customer is None or customer.role != ROLE_CUSTOMER or not customer.is_active:
        raise BookingPermissionError("Only customer accounts can make bookings.")
    if service is None or not service.is_available:
        raise BookingRuleError("This service is not available for booking right now.")

    now = now or now_local()
    problems = rules.appointment_problems(appointment_date, appointment_time, now)
    if problems:
        raise BookingRuleError(problems[0])
    slot = rules.parse_time_slot(appointment_time)

    contact_name = rules.clean_line(contact_name)
    address = rules.clean_line(address)
    problem_description = rules.clean_multiline(problem_description)
    phone = rules.normalize_phone(contact_phone)
    _check_length("Your name", contact_name, NAME_LIMITS)
    _check_length("The address", address, ADDRESS_LIMITS)
    _check_length("The problem description", problem_description, DESCRIPTION_LIMITS)
    if phone is None:
        raise BookingRuleError("Enter a valid phone number.")

    existing = _find_by_token(customer.id, submission_token)
    if existing is not None:  # the same form was already submitted
        return existing, False

    clash = db.session.scalar(
        select(Booking.id).where(
            Booking.customer_id == customer.id,
            Booking.service_id == service.id,
            Booking.appointment_date == appointment_date,
            Booking.appointment_time == slot,
            Booking.status.in_(rules.ACTIVE_STATUSES),
        )
    )
    if clash is not None:
        raise BookingRuleError("You already have an active booking for this service at that date and time.")

    # The server (never the customer) picks the provider: one who offers this
    # service and is free at that time. None if no provider offers it yet.
    provider = scheduling.choose_provider(service, appointment_date, slot)

    for _attempt in range(MAX_REFERENCE_ATTEMPTS):
        reference = rules.generate_reference()
        if db.session.scalar(select(Booking.id).where(Booking.reference == reference)) is not None:
            continue  # already used: try another
        booking = Booking(
            reference=reference,
            customer_id=customer.id,
            service_id=service.id,
            provider_id=provider.id if provider is not None else None,
            contact_name=contact_name,
            contact_phone=phone,
            address=address,
            appointment_date=appointment_date,
            appointment_time=slot,
            problem_description=problem_description,
            status=rules.STATUS_PENDING,
            price_from_at_booking=service.price_from,
            submission_token=submission_token or None,
        )
        db.session.add(booking)
        try:
            db.session.commit()
            return booking, True
        except IntegrityError:
            db.session.rollback()
            duplicate = _find_by_token(customer.id, submission_token)
            if duplicate is not None:  # a double click: the other request won
                return duplicate, False
            if db.session.scalar(select(Booking.id).where(Booking.reference == reference)) is not None:
                continue  # someone took this reference a moment ago: try another
            raise
    raise BookingReferenceError("We could not create a booking reference. Please try again.")


# ------------------------------------------------------------ status changes
def check_transition(booking, new_status):
    """Raise InvalidTransitionError unless the workflow allows this change."""
    if not rules.can_transition(booking.status, new_status):
        raise InvalidTransitionError(
            f"A {rules.STATUS_LABELS.get(booking.status, booking.status).lower()} booking cannot be changed to "
            f"{rules.STATUS_LABELS.get(new_status, new_status).lower()}."
        )


def transition_status(booking, new_status):
    """Move a booking to new_status if the workflow allows it, otherwise refuse.

    The caller must already have checked WHO may make this change (providers
    use services/provider_bookings.py; customers use cancel_booking).
    """
    check_transition(booking, new_status)
    booking.status = new_status
    db.session.commit()
    return booking


def cancel_booking(booking, customer, reason=None, now=None):
    """Cancel the customer's own booking if the cancellation rules allow it."""
    if customer is None or customer.role != ROLE_CUSTOMER or booking.customer_id != customer.id:
        raise BookingPermissionError("You can only cancel your own bookings.")

    block = rules.cancellation_block_reason(booking.status, booking.appointment_start, now or now_local())
    if block:
        raise BookingRuleError(block)

    reason = rules.clean_line(reason)[:REASON_MAX_LENGTH] or None
    transition_status_value = rules.STATUS_CANCELLED
    if not rules.can_transition(booking.status, transition_status_value):  # second safety check
        raise InvalidTransitionError("This booking cannot be cancelled.")
    booking.status = transition_status_value
    booking.cancellation_reason = reason
    booking.cancelled_at = datetime.now(timezone.utc)
    db.session.commit()
    return booking
