"""Booking and cancellation forms.

There are deliberately NO fields for status, provider, price, customer or role.
Anything extra in a request is ignored; the server decides those values.
"""
import re

from flask import current_app
from flask_wtf import FlaskForm
from wtforms import DateField, HiddenField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, ValidationError

from services import booking_rules as rules
from services.bookings import ADDRESS_LIMITS, DESCRIPTION_LIMITS, NAME_LIMITS, REASON_MAX_LENGTH

TOKEN_PATTERN = re.compile(r"[0-9a-f]{32}")


def _now():
    return rules.local_now(current_app.config.get("BOOKING_UTC_OFFSET_MINUTES", 330))


def _tidy_line(value):
    return rules.clean_line(value) if isinstance(value, str) else value


def _tidy_text(value):
    return rules.clean_multiline(value) if isinstance(value, str) else value


class BookingForm(FlaskForm):
    contact_name = StringField(
        "Your name",
        validators=[DataRequired("Enter your name."), Length(*NAME_LIMITS, message="Your name must be 2 to 100 characters.")],
        filters=[_tidy_line],
    )
    contact_phone = StringField(
        "Phone number",
        validators=[DataRequired("Enter a phone number.")],
        filters=[_tidy_line],
    )
    address = TextAreaField(
        "Service address",
        validators=[DataRequired("Enter the address where the work is needed."), Length(*ADDRESS_LIMITS, message="The address must be 10 to 300 characters.")],
        filters=[_tidy_line],
    )
    appointment_date = DateField("Preferred date", format="%Y-%m-%d", validators=[DataRequired("Choose a date.")])
    appointment_time = SelectField(
        "Preferred time",
        choices=rules.time_slot_choices(),
        validators=[DataRequired("Choose a time.")],
    )
    problem_description = TextAreaField(
        "What needs fixing?",
        validators=[DataRequired("Describe the problem."), Length(*DESCRIPTION_LIMITS, message="The description must be 10 to 1000 characters.")],
        filters=[_tidy_text],
    )
    submission_token = HiddenField()  # lets the server ignore an accidental second submit

    def validate_contact_phone(self, field):
        if rules.normalize_phone(field.data) is None:
            raise ValidationError("Enter a valid phone number with 10 to 15 digits, for example +91 98765 43210.")

    def validate_appointment_date(self, field):
        problem = rules.date_problem(field.data, _now())
        if problem:
            raise ValidationError(problem)

    def validate_appointment_time(self, field):
        problem = rules.time_problem(self.appointment_date.data, field.data, _now())
        if problem:
            raise ValidationError(problem)

    def validate_submission_token(self, field):
        if not TOKEN_PATTERN.fullmatch(field.data or ""):
            raise ValidationError("This form has expired. Reload the page and try again.")


class CancelForm(FlaskForm):
    reason = TextAreaField(
        "Reason for cancelling (optional)",
        validators=[Optional(), Length(max=REASON_MAX_LENGTH, message=f"Use no more than {REASON_MAX_LENGTH} characters.")],
        filters=[_tidy_line],
    )
