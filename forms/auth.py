"""Registration and login forms.

Note what is NOT here: there is no "role" field. Public registration can only
create customers, and the route sets that in code. Extra values that someone
adds to the request (such as role=admin) are ignored.
"""
from flask_wtf import FlaskForm
from wtforms import HiddenField, PasswordField, StringField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError

from services import accounts
from services.passwords import MAX_PASSWORD_LENGTH, password_problems
from services.security import normalize_email


def _clean_name(value):
    return " ".join(value.split()) if isinstance(value, str) else value


class RegistrationForm(FlaskForm):
    full_name = StringField(
        "Full name",
        validators=[DataRequired("Enter your name."), Length(min=2, max=100, message="Your name must be 2 to 100 characters.")],
        filters=[_clean_name],
    )
    email = StringField(
        "Email address",
        validators=[DataRequired("Enter your email address."), Length(max=254, message="That email address is too long."), Email("Enter a valid email address.")],
        filters=[normalize_email],
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired("Choose a password."), Length(max=MAX_PASSWORD_LENGTH, message=f"Use no more than {MAX_PASSWORD_LENGTH} characters.")],
    )
    confirm_password = PasswordField(
        "Confirm password",
        validators=[DataRequired("Enter your password again."), EqualTo("password", message="The passwords do not match.")],
    )

    next_url = HiddenField()  # where to go after signing up (checked with safe_redirect_target)

    def validate_email(self, field):
        if accounts.get_user_by_email(field.data) is not None:
            raise ValidationError("An account with this email already exists. Try logging in instead.")

    def validate_password(self, field):
        problems = password_problems(field.data, email=self.email.data or "", full_name=self.full_name.data or "")
        if problems:
            raise ValidationError(problems[0])


class LoginForm(FlaskForm):
    email = StringField(
        "Email address",
        validators=[DataRequired("Enter your email address."), Length(max=254)],
        filters=[normalize_email],
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired("Enter your password."), Length(max=MAX_PASSWORD_LENGTH)],
    )
    next_url = HiddenField()  # where to go after login; checked with safe_redirect_target
