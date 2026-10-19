"""Register, log in and log out."""
from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from extensions import db
from forms.auth import LoginForm, RegistrationForm
from models.user import ROLE_CUSTOMER
from services import accounts
from services.permissions import role_home_url
from services.security import safe_redirect_target

bp = Blueprint("auth", __name__)


@bp.after_request
def no_cache(response):
    """Do not let the browser keep these pages (they can hold private details)."""
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(role_home_url(current_user))

    form = RegistrationForm()
    if request.method == "GET":
        form.next_url.data = request.args.get("next", "")
    if form.validate_on_submit():
        try:
            # The role is fixed in code. It is never read from the form or request.
            user = accounts.create_user(
                email=form.email.data,
                full_name=form.full_name.data,
                password=form.password.data,
                role=ROLE_CUSTOMER,
            )
        except accounts.DuplicateEmailError:
            form.email.errors = list(form.email.errors) + ["An account with this email already exists. Try logging in instead."]
        except (accounts.InvalidEmailError, accounts.WeakPasswordError, ValueError) as error:
            form.email.errors = list(form.email.errors) + [str(error)]
        else:
            session.clear()
            login_user(user)
            flash("Welcome to FixNear! Your account has been created.", "success")
            return redirect(safe_redirect_target(form.next_url.data, role_home_url(user)))
    form.next_url.data = safe_redirect_target(form.next_url.data, "")
    return render_template("auth/register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(role_home_url(current_user))

    form = LoginForm()
    if request.method == "GET":
        form.next_url.data = request.args.get("next", "")

    credentials_rejected = False
    if form.validate_on_submit():
        user = accounts.authenticate(form.email.data, form.password.data)
        if user is None:
            credentials_rejected = True  # one message for every kind of failure
        else:
            session.clear()  # start from a clean session at login
            login_user(user)
            user.last_login_at = datetime.now(timezone.utc)
            db.session.commit()
            return redirect(safe_redirect_target(form.next_url.data, role_home_url(user)))

    # Whatever was submitted, only ever write a safe local path back into the page.
    form.next_url.data = safe_redirect_target(form.next_url.data, "")
    return render_template("auth/login.html", form=form, credentials_rejected=credentials_rejected)


@bp.post("/logout")
@login_required
def logout():
    """POST only (with a CSRF token), so another site cannot log you out."""
    logout_user()
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.index"))
