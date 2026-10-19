"""Customer booking pages: book, confirmation, history, details and cancel.

Every route requires a CUSTOMER account. Bookings are always looked up through
the logged-in customer, so nobody can open another customer's booking.
"""
import secrets
from datetime import timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from forms.booking import BookingForm, CancelForm
from models.user import ROLE_CUSTOMER
from services import booking_rules as rules
from services import bookings, catalog
from services.permissions import role_required

bp = Blueprint("bookings", __name__)


@bp.after_request
def no_cache(response):
    """Booking pages are private: the browser must not keep them."""
    response.headers["Cache-Control"] = "no-store"
    return response


def _own_booking_or_404(reference):
    booking = bookings.get_customer_booking(current_user, reference)
    if booking is None:  # missing, malformed, or somebody else's: all look the same
        abort(404)
    return booking


@bp.route("/services/<slug>/book", methods=["GET", "POST"])
@role_required(ROLE_CUSTOMER)
def new(slug):
    service = catalog.get_service(slug)  # only available services are found
    if service is None:
        abort(404)

    form = BookingForm()
    if request.method == "GET":
        form.contact_name.data = current_user.full_name
        form.submission_token.data = secrets.token_hex(16)

    form_error = None
    if form.validate_on_submit():
        try:
            booking, created = bookings.create_booking(
                current_user,
                service,
                contact_name=form.contact_name.data,
                contact_phone=form.contact_phone.data,
                address=form.address.data,
                appointment_date=form.appointment_date.data,
                appointment_time=form.appointment_time.data,
                problem_description=form.problem_description.data,
                submission_token=form.submission_token.data,
            )
        except bookings.BookingPermissionError:
            abort(403)
        except bookings.BookingRuleError as error:
            form_error = str(error)
        except bookings.BookingReferenceError as error:
            form_error = str(error)
        else:
            if created:
                flash("Your booking request has been saved.", "success")
            else:
                flash("This booking was already saved. Here are its details.", "info")
            return redirect(url_for("bookings.confirmation", reference=booking.reference))

    today = bookings.now_local().date()
    return render_template(
        "bookings/new.html",
        form=form,
        service=service,
        category=service.category,
        form_error=form_error,
        min_date=today.isoformat(),
        max_date=(today + timedelta(days=rules.MAX_DAYS_AHEAD)).isoformat(),
    )


@bp.route("/bookings")
@role_required(ROLE_CUSTOMER)
def history():
    status = request.args.get("status", "").strip().lower()
    if status not in rules.STATUSES:
        status = ""  # unknown filter values are ignored
    return render_template(
        "bookings/list.html",
        items=bookings.list_customer_bookings(current_user, status or None),
        counts=bookings.status_counts(current_user),
        active_status=status,
        statuses=rules.STATUSES,
        labels=rules.STATUS_LABELS,
    )


@bp.route("/bookings/<reference>/confirmation")
@role_required(ROLE_CUSTOMER)
def confirmation(reference):
    return render_template("bookings/confirmation.html", booking=_own_booking_or_404(reference))


@bp.route("/bookings/<reference>")
@role_required(ROLE_CUSTOMER)
def detail(reference):
    booking = _own_booking_or_404(reference)
    return render_template(
        "bookings/detail.html",
        booking=booking,
        steps=rules.tracking_steps(booking.status),
        cancel_block=rules.cancellation_block_reason(booking.status, booking.appointment_start, bookings.now_local()),
    )


@bp.route("/bookings/<reference>/cancel", methods=["GET", "POST"])
@role_required(ROLE_CUSTOMER)
def cancel(reference):
    booking = _own_booking_or_404(reference)

    block = rules.cancellation_block_reason(booking.status, booking.appointment_start, bookings.now_local())
    if block:
        flash(block, "error")
        return redirect(url_for("bookings.detail", reference=booking.reference))

    form = CancelForm()
    if form.validate_on_submit():
        try:
            bookings.cancel_booking(booking, current_user, form.reason.data)
        except bookings.BookingPermissionError:
            abort(403)
        except bookings.BookingRuleError as error:
            flash(str(error), "error")
        else:
            flash("Your booking has been cancelled.", "success")
        return redirect(url_for("bookings.detail", reference=booking.reference))
    return render_template("bookings/cancel.html", booking=booking, form=form)
