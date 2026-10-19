"""FixNear - Local Service Booking Platform (application entry point)."""
import os
from datetime import datetime

from flask import Flask, render_template
from flask_login import current_user
from flask_wtf.csrf import CSRFError
from sqlalchemy.exc import SQLAlchemyError

import models  # noqa: F401  (importing registers the tables with SQLAlchemy)
from cli import register_account_commands, register_commands, register_provider_commands
from config import get_config
from extensions import csrf, db, login_manager, migrate
from routes.admin import bp as admin_bp
from routes.auth import bp as auth_bp
from routes.bookings import bp as bookings_bp
from routes.dashboard import bp as dashboard_bp
from routes.main import bp as main_bp
from routes.provider import bp as provider_bp
from services import booking_rules, catalog
from services.permissions import can_manage_booking
from services.icons import icon


def create_app(config_object=None):
    """Application factory: builds a configured Flask app.

    Using a factory lets the tests create their own isolated app.
    Starting the app NEVER creates, resets or deletes database data.
    """
    app = Flask(__name__)
    app.config.from_object(config_object or get_config())

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    csrf.init_app(app)
    login_manager.init_app(app)

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(provider_bp)
    app.register_blueprint(admin_bp)
    register_commands(app)
    register_account_commands(app)
    register_provider_commands(app)
    _register_template_helpers(app)
    _register_error_handlers(app)
    _register_security_headers(app)
    return app


def _register_template_helpers(app):
    app.jinja_env.globals["icon"] = icon
    app.jinja_env.globals["provider_actions"] = booking_rules.provider_actions_for
    app.jinja_env.globals["can_manage_booking"] = lambda booking: can_manage_booking(current_user, booking)
    app.jinja_env.globals["provider_action_labels"] = booking_rules.PROVIDER_ACTION_LABELS
    app.jinja_env.filters["inr"] = lambda amount: f"\u20b9{int(amount):,}"
    app.jinja_env.filters["date_long"] = lambda d: f"{d:%A}, {d.day} {d:%B %Y}"
    app.jinja_env.filters["time_12h"] = lambda t: f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"

    @app.context_processor
    def inject_globals():
        # This runs for every page, including error pages. If the database is
        # unavailable it must not crash, so fall back to an empty menu list.
        try:
            nav_categories = catalog.list_categories()
        except SQLAlchemyError:
            db.session.rollback()
            nav_categories = []
        return {
            "nav_categories": nav_categories,
            "current_year": datetime.now().year,
        }


def _register_error_handlers(app):
    def render_error(code, title, message):
        return render_template("errors/error.html", code=code, title=title, message=message), code

    @app.errorhandler(CSRFError)
    def csrf_failed(_error):
        # Missing, wrong or expired form token. Nothing was changed.
        return render_error(400, "Request could not be verified", "Your form expired or could not be verified. Go back, reload the page and try again.")

    @app.errorhandler(400)
    def bad_request(_error):
        return render_error(400, "Bad request", "The request could not be understood. Please go back and try again.")

    @app.errorhandler(403)
    def forbidden(_error):
        return render_error(403, "Access denied", "You do not have permission to open this page.")

    @app.errorhandler(404)
    def not_found(_error):
        return render_error(404, "Page not found", "The page you are looking for does not exist or has moved.")

    @app.errorhandler(500)
    def server_error(_error):
        # Never show stack traces or internal details to visitors.
        return render_error(500, "Something went wrong", "An unexpected error occurred on our side. Please try again in a moment.")

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        # Log the details for the developer; show visitors only a safe message.
        app.logger.error("Database error: %s", error, exc_info=error)
        db.session.rollback()
        return render_error(500, "Something went wrong", "We could not load this page right now. Please try again in a moment.")


def _register_security_headers(app):
    @app.after_request
    def add_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response


app = create_app()

if __name__ == "__main__":
    # Debug mode is only on when you explicitly set FLASK_DEBUG=1 (never in production).
    app.run(host="127.0.0.1", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
