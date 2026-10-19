"""Creating users and checking logins. All account rules live here."""
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models.user import ROLE_CUSTOMER, ROLES, User
from services.passwords import password_problems
from services.security import normalize_email


class DuplicateEmailError(Exception):
    """An account with this email already exists."""


class InvalidEmailError(ValueError):
    """The email address is not valid."""


class WeakPasswordError(ValueError):
    """The password breaks the password rules."""

    def __init__(self, problems):
        super().__init__(" ".join(problems))
        self.problems = problems


_dummy_hash = None


def get_user_by_email(email):
    email = normalize_email(email)
    if not email:
        return None
    return db.session.scalar(select(User).where(User.email == email))


def users_table_exists():
    return inspect(db.engine).has_table(User.__tablename__)


def create_user(email, full_name, password, role=ROLE_CUSTOMER):
    """Create and save a user. Raises a clear error instead of saving bad data.

    The role is always chosen by CODE (registration passes "customer"); it is
    never taken from a web form.
    """
    if role not in ROLES:
        raise ValueError(f"Unknown role: {role!r}")

    email = normalize_email(email)
    try:
        validate_email(email, check_deliverability=False)  # no network lookup
    except EmailNotValidError as error:
        raise InvalidEmailError(str(error)) from None
    if len(email) > 254:
        raise InvalidEmailError("The email address is too long.")

    full_name = " ".join((full_name or "").split())
    if not 2 <= len(full_name) <= 100:
        raise ValueError("Enter a name between 2 and 100 characters.")

    problems = password_problems(password, email=email, full_name=full_name)
    if problems:
        raise WeakPasswordError(problems)

    user = User(email=email, full_name=full_name, role=role)
    user.set_password(password)
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if get_user_by_email(email) is not None:  # two people registered at the same moment
            raise DuplicateEmailError(email) from None
        raise
    return user


def authenticate(email, password):
    """Return the User for a correct email and password, otherwise None.

    "Unknown email" and "wrong password" behave the same (same result, similar
    time), so an attacker cannot use the login form to discover which emails exist.
    """
    global _dummy_hash
    user = get_user_by_email(email)
    if user is None:
        if _dummy_hash is None:
            _dummy_hash = generate_password_hash("not-a-real-password")
        check_password_hash(_dummy_hash, password or "")  # spend the same time
        return None
    if not user.check_password(password or ""):
        return None
    if not user.is_active:
        return None
    return user
