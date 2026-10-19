"""Provider pages: the jobs assigned to the logged-in provider, and what they can do with them.

Every route requires a PROVIDER account. Bookings are always looked up through
the logged-in provider, so another provider's booking looks like it does not exist.
"""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from models.user import ROLE_PROVIDER
from services import booking_rules as rules
from services import provider_bookings
from services.errors import BookingPermissionError, BookingRuleError
from services.permissions import role_required

bp = Blueprint("provider", __name__, url_prefix="/provider")


@bp.after_request
def no_cache(response):
    """Job pages hold customer contact details: the browser must not keep them."""
    response.headers["Cache-Control"] = "no-store"
    return response


def _own_job_or_404(reference):
    booking = provider_bookings.get_provider_booking(current_user, reference)
    if booking is None:  # missing, malformed, assigned to someone else, or unassigned: all look the same
        abort(404)
    return booking


@bp.route("/bookings")
@role_required(ROLE_PROVIDER)
def jobs():
    status = request.args.get("status", "").strip().lower()
    if status not in rules.STATUSES:
        status = ""  # unknown filter values are ignored
    return render_template(
        "provider/jobs.html",
        items=provider_bookings.list_provider_bookings(current_user, statuses=[status] if status else None),
        counts=provider_bookings.status_counts(current_user),
        active_status=status,
        statuses=rules.STATUSES,
        labels=rules.STATUS_LABELS,
    )


@bp.route("/bookings/<reference>")
@role_required(ROLE_PROVIDER)
def detail(reference):
    booking = _own_job_or_404(reference)
    return render_template("provider/detail.html", booking=booking, steps=rules.tracking_steps(booking.status))


@bp.post("/bookings/<reference>/<action>")
@role_required(ROLE_PROVIDER)
def act(reference, action):
    """accept, reject, start or complete. POST only, and CSRF-protected."""
    if action not in rules.PROVIDER_ACTIONS:
        abort(404)
    booking = _own_job_or_404(reference)
    try:
        changed = provider_bookings.perform_action(booking, current_user, action)
    except BookingPermissionError:
        abort(403)
    except BookingRuleError as error:  # invalid transition, scheduling conflict, ...
        flash(str(error), "error")
    else:
        if changed:
            flash(rules.PROVIDER_ACTION_MESSAGES[action], "success")
        else:
            flash(f"This booking is already {rules.STATUS_LABELS[rules.PROVIDER_ACTIONS[action]].lower()}.", "info")
    return redirect(url_for("provider.detail", reference=booking.reference))
