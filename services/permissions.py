"""Server-side access control. Hiding a button is never enough; every protected
route is wrapped with one of these checks."""
from functools import wraps

from flask import abort, current_app, url_for
from flask_login import current_user

from models.user import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_PROVIDER

ROLE_HOME_ENDPOINTS = {
    ROLE_CUSTOMER: "dashboard.customer",
    ROLE_PROVIDER: "dashboard.provider",
    ROLE_ADMIN: "dashboard.admin",
}


def role_home_url(user):
    """The dashboard that belongs to this user's role."""
    return url_for(ROLE_HOME_ENDPOINTS.get(user.role, "main.index"))


def can_manage_booking(user, booking):
    """True only for the ACTIVE provider account this booking is assigned to.

    Customers, admins, visitors, other providers and bookings with no provider all
    get False. Templates use this to decide whether to draw the Accept / Reject /
    Start / Complete buttons. It is only a display check: the routes and
    services/provider_bookings.py enforce the same rule on the server.
    """
    return bool(
        user is not None
        and getattr(user, "is_authenticated", False)
        and getattr(user, "role", None) == ROLE_PROVIDER
        and getattr(user, "is_active", False)
        and booking is not None
        and booking.provider_id is not None
        and booking.provider_id == user.id
    )


def role_required(*roles):
    """Allow only logged-in users whose role is in roles.

    Not logged in  -> redirected to the login page (and back afterwards).
    Wrong role     -> 403 Access denied.
    """

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator
