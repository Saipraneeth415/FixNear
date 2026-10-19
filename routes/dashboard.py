"""Role-specific dashboards. All three show real data."""
from flask import Blueprint, redirect, render_template
from flask_login import current_user, login_required

from models.user import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_PROVIDER
from services import booking_rules as rules
from services import admin as admin_service
from services import bookings, provider_bookings, providers
from services.permissions import role_home_url, role_required

bp = Blueprint("dashboard", __name__)


@bp.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/dashboard")
@login_required
def home():
    """Send each user to the dashboard for their own role."""
    return redirect(role_home_url(current_user))


@bp.route("/customer/dashboard")
@role_required(ROLE_CUSTOMER)
def customer():
    """Real numbers and bookings for the signed-in customer only."""
    return render_template(
        "dashboard/customer.html",
        stats=bookings.booking_stats(current_user),
        recent=bookings.list_customer_bookings(current_user, limit=5),
    )


@bp.route("/provider/dashboard")
@role_required(ROLE_PROVIDER)
def provider():
    """Only bookings assigned to the signed-in provider."""
    return render_template(
        "dashboard/provider.html",
        stats=provider_bookings.provider_stats(current_user),
        awaiting=provider_bookings.list_provider_bookings(current_user, statuses=[rules.STATUS_PENDING]),
        active=provider_bookings.list_provider_bookings(current_user, statuses=rules.COMMITTED_STATUSES),
        recent=provider_bookings.list_provider_bookings(current_user, statuses=[rules.STATUS_COMPLETED], newest_first=True, limit=5),
        offered=providers.offered_services(current_user),
    )


@bp.route("/admin/dashboard")
@role_required(ROLE_ADMIN)
def admin():
    """Live numbers from the database, plus the five newest bookings."""
    return render_template(
        "dashboard/admin.html",
        counts=admin_service.dashboard_counts(),
        recent=admin_service.list_bookings(per_page=5)[0],
    )
