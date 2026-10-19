"""Admin forms: categories and services.

The server re-checks every value in services/catalog_admin.py, so these forms are
for clear messages, not for security.
"""
from flask_wtf import FlaskForm
from wtforms import BooleanField, IntegerField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional, ValidationError

from services import admin_rules, catalog
from services import booking_rules as rules
from services import catalog_admin as limits
from services.icons import ICON_NAMES
from services.providers import get_service_by_slug


def _line(value):
    return rules.clean_line(value) if isinstance(value, str) else value


def _text(value):
    return rules.clean_multiline(value) if isinstance(value, str) else value


def _slug(value):
    # Only trim spaces. Upper-case or odd characters are refused (with a message) rather than silently changed.
    return value.strip() if isinstance(value, str) else value


class CategoryForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired("Enter a name."), Length(*limits.CATEGORY_NAME, message="The name must be 2 to 100 characters.")], filters=[_line])
    slug = StringField("Address (slug)", validators=[DataRequired("Enter an address."), Length(max=60, message="Use at most 60 characters.")], filters=[_slug])
    icon = SelectField("Icon", choices=[(name, name.title()) for name in ICON_NAMES])
    blurb = StringField("Short description", validators=[DataRequired("Enter a short description."), Length(max=limits.MAX_BLURB, message="Use at most 255 characters.")], filters=[_line])
    sort_order = IntegerField("Display order", validators=[InputRequired("Enter a number."), NumberRange(0, limits.MAX_SORT_ORDER, "Use a number from 0 to 999.")], default=0)

    def validate_slug(self, field):
        if not admin_rules.is_valid_slug(field.data):
            raise ValidationError("Use lower-case letters, digits and single hyphens, for example ac-repair.")
        if catalog.get_category(field.data) is not None:
            raise ValidationError("A category with that address already exists.")


class ServiceForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired("Enter a name."), Length(*limits.SERVICE_NAME, message="The name must be 3 to 150 characters.")], filters=[_line])
    slug = StringField("Address (slug)", validators=[DataRequired("Enter an address."), Length(max=100, message="Use at most 100 characters.")], filters=[_slug])
    category_id = SelectField("Category", coerce=int, choices=[])
    summary = StringField("Summary", validators=[DataRequired("Enter a summary."), Length(max=limits.MAX_SUMMARY, message="Use at most 255 characters.")], filters=[_line])
    description = TextAreaField("Description", validators=[DataRequired("Enter a description."), Length(max=limits.MAX_DESCRIPTION, message="Use at most 5000 characters.")], filters=[_text])
    price_from = IntegerField("Starting price (rupees)", validators=[InputRequired("Enter a price."), NumberRange(0, limits.MAX_PRICE, "Use a price from 0 to 1,000,000.")])
    duration = StringField("Usual time", validators=[DataRequired("Enter the usual time."), Length(max=limits.MAX_DURATION, message="Use at most 50 characters.")], filters=[_line])
    includes = TextAreaField("What is included (one item per line)", validators=[Optional()], filters=[_text])
    provider_name = StringField("Provider name shown on the page", validators=[DataRequired("Enter a provider name."), Length(max=limits.MAX_PROVIDER_FIELD)], filters=[_line])
    provider_area = StringField("Provider area shown on the page", validators=[DataRequired("Enter an area."), Length(max=limits.MAX_PROVIDER_FIELD)], filters=[_line])
    provider_bio = TextAreaField("Provider bio", validators=[Optional(), Length(max=limits.MAX_BIO, message="Use at most 2000 characters.")], filters=[_text])
    is_available = BooleanField("Available (visible and bookable)", default=True)
    is_sample = BooleanField("This is sample data (shows a Sample badge)", default=False)

    def validate_slug(self, field):
        if not admin_rules.is_valid_slug(field.data):
            raise ValidationError("Use lower-case letters, digits and single hyphens, for example ac-servicing.")
        if get_service_by_slug(field.data) is not None:
            raise ValidationError("A service with that address already exists.")

    def validate_includes(self, field):
        problem = admin_rules.includes_problem(admin_rules.parse_includes(field.data))
        if problem:
            raise ValidationError(problem)
