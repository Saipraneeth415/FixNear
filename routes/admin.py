"""Admin pages: users, services and categories, and all bookings.

EVERY route requires an active administrator (role_required). Anything that changes
data is a POST with a CSRF token and is re-checked in services/admin.py and
services/catalog_admin.py. Customers, providers and visitors never get in.
"""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from forms.admin import CategoryForm, ServiceForm
from models.user import ROLE_ADMIN, ROLES
from services import admin as admin_service
from services import admin_rules, catalog, catalog_admin
from services import booking_rules as rules
from services.errors import AdminPermissionError, AdminRuleError
from services.permissions import role_required
from services.providers import get_service_by_slug
from services.security import safe_redirect_target

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.after_request
def no_cache(response):
    """Admin pages show private data: the browser must not keep them."""
    response.headers["Cache-Control"] = "no-store"
    return response


def _back(default_endpoint):
    """Where to go after an action: the page the admin came from, but only inside /admin/."""
    target = safe_redirect_target(request.form.get("next"), url_for(default_endpoint))
    return target if target.startswith("/admin/") else url_for(default_endpoint)


def _page():
    return admin_rules.parse_page(request.args.get("page"))


def _params(**values):
    """Only the filters that are actually set, for building page links."""
    return {key: value for key, value in values.items() if value}


# --------------------------------------------------------------------- users
@bp.route("/users")
@role_required(ROLE_ADMIN)
def users():
    role = request.args.get("role", "").strip().lower()
    status = request.args.get("status", "").strip().lower()
    q = request.args.get("q", "").strip()[: admin_service.MAX_SEARCH_LENGTH]
    role = role if role in ROLES else ""
    status = status if status in ("active", "inactive") else ""
    items, info = admin_service.list_users(role, status, q, _page())
    return render_template(
        "admin/users.html", items=items, page_info=info, roles=ROLES,
        filters={"role": role, "status": status, "q": q}, params=_params(role=role, status=status, q=q),
    )


@bp.post("/users/<int:user_id>/<action>")
@role_required(ROLE_ADMIN)
def user_status(user_id, action):
    """activate or deactivate an account."""
    if action not in ("activate", "deactivate"):
        abort(404)
    target = admin_service.get_user(user_id)
    if target is None:
        abort(404)
    try:
        still_assigned = admin_service.set_user_active(current_user, target, action == "activate")
    except AdminPermissionError:
        abort(403)
    except AdminRuleError as error:
        flash(str(error), "error")
    else:
        flash(f"{target.email} has been {'activated' if action == 'activate' else 'deactivated'}.", "success")
        if still_assigned:
            flash(f"Note: {still_assigned} active booking(s) are still assigned to this provider.", "info")
    return redirect(_back("admin.users"))


# ------------------------------------------------------------------ bookings
@bp.route("/bookings")
@role_required(ROLE_ADMIN)
def bookings():
    status = request.args.get("status", "").strip().lower()
    service_slug = request.args.get("service", "").strip().lower()
    provider = request.args.get("provider", "").strip().lower()
    q = request.args.get("q", "").strip()[: admin_service.MAX_SEARCH_LENGTH]
    status = status if status in rules.STATUSES else ""
    items, info = admin_service.list_bookings(status, service_slug, provider, q, _page())
    return render_template(
        "admin/bookings.html", items=items, page_info=info, statuses=rules.STATUSES, labels=rules.STATUS_LABELS,
        services=admin_service.services_for_filter(), providers=admin_service.providers_for_filter(),
        filters={"status": status, "service": service_slug, "provider": provider, "q": q},
        params=_params(status=status, service=service_slug, provider=provider, q=q),
    )


# ------------------------------------------------- services and categories
@bp.route("/services")
@role_required(ROLE_ADMIN)
def services():
    return render_template(
        "admin/services.html",
        categories=catalog_admin.categories_with_counts(),
        services=catalog_admin.services_with_counts(),
    )


def _category_choices():
    return [(category.id, category.name) for category in catalog.list_categories()]


def _service_fields(form):
    return dict(
        name=form.name.data, category_id=form.category_id.data, summary=form.summary.data, description=form.description.data,
        price_from=form.price_from.data, duration=form.duration.data, includes=form.includes.data or "",
        provider_name=form.provider_name.data, provider_area=form.provider_area.data, provider_bio=form.provider_bio.data or "",
        is_available=form.is_available.data, is_sample=form.is_sample.data,
    )


@bp.route("/services/new", methods=["GET", "POST"])
@role_required(ROLE_ADMIN)
def service_new():
    form = ServiceForm()
    form.category_id.choices = _category_choices()
    form_error = None
    if form.validate_on_submit():
        try:
            service = catalog_admin.create_service(current_user, slug=form.slug.data, **_service_fields(form))
        except AdminPermissionError:
            abort(403)
        except AdminRuleError as error:
            form_error = str(error)
        else:
            flash(f"Service “{service.name}” created.", "success")
            return redirect(url_for("admin.services"))
    return render_template("admin/service_form.html", form=form, mode="create", service=None, form_error=form_error)


@bp.route("/services/<slug>/edit", methods=["GET", "POST"])
@role_required(ROLE_ADMIN)
def service_edit(slug):
    service = get_service_by_slug(slug)
    if service is None:
        abort(404)
    form = ServiceForm(obj=service)
    del form.slug  # the address never changes after creation
    form.category_id.choices = _category_choices()
    form_error = None
    if request.method == "GET":
        form.includes.data = "\n".join(service.includes or [])
    if form.validate_on_submit():
        try:
            catalog_admin.update_service(current_user, service, **_service_fields(form))
        except AdminPermissionError:
            abort(403)
        except AdminRuleError as error:
            form_error = str(error)
        else:
            flash(f"Service “{service.name}” saved.", "success")
            return redirect(url_for("admin.services"))
    return render_template("admin/service_form.html", form=form, mode="edit", service=service, form_error=form_error)


@bp.post("/services/<slug>/<action>")
@role_required(ROLE_ADMIN)
def service_visibility(slug, action):
    """show or hide a service."""
    if action not in ("show", "hide"):
        abort(404)
    service = get_service_by_slug(slug)
    if service is None:
        abort(404)
    try:
        active = catalog_admin.set_service_available(current_user, service, action == "show")
    except AdminPermissionError:
        abort(403)
    except AdminRuleError as error:
        flash(str(error), "error")
    else:
        flash(f"“{service.name}” is now {'visible and bookable' if action == 'show' else 'hidden. No new bookings can be made'}.", "success")
        if action == "hide" and active:
            flash(f"Note: it still has {active} active booking(s). They are not changed.", "info")
    return redirect(url_for("admin.services"))


@bp.route("/services/<slug>/delete", methods=["GET", "POST"])
@role_required(ROLE_ADMIN)
def service_delete(slug):
    service = get_service_by_slug(slug)
    if service is None:
        abort(404)
    used = catalog_admin.booking_count(service)
    if request.method == "POST":
        try:
            catalog_admin.delete_service(current_user, service)
        except AdminPermissionError:
            abort(403)
        except AdminRuleError as error:
            flash(str(error), "error")
        else:
            flash(f"Service “{service.name}” deleted.", "success")
        return redirect(url_for("admin.services"))
    blocked = f"This service has {used} booking(s), so it cannot be deleted. Hide it instead to stop new bookings." if used else None
    return render_template(
        "admin/confirm_delete.html", kind="service", name=service.name, blocked=blocked,
        action_url=url_for("admin.service_delete", slug=service.slug), back_url=url_for("admin.services"),
        note="Any provider links to this service will be removed.",
    )


@bp.route("/categories/new", methods=["GET", "POST"])
@role_required(ROLE_ADMIN)
def category_new():
    form = CategoryForm()
    form_error = None
    if form.validate_on_submit():
        try:
            category = catalog_admin.create_category(
                current_user, slug=form.slug.data, name=form.name.data, icon=form.icon.data, blurb=form.blurb.data, sort_order=form.sort_order.data
            )
        except AdminPermissionError:
            abort(403)
        except AdminRuleError as error:
            form_error = str(error)
        else:
            flash(f"Category “{category.name}” created.", "success")
            return redirect(url_for("admin.services"))
    return render_template("admin/category_form.html", form=form, mode="create", category=None, form_error=form_error)


@bp.route("/categories/<slug>/edit", methods=["GET", "POST"])
@role_required(ROLE_ADMIN)
def category_edit(slug):
    category = catalog.get_category(slug)
    if category is None:
        abort(404)
    form = CategoryForm(obj=category)
    del form.slug
    form_error = None
    if form.validate_on_submit():
        try:
            catalog_admin.update_category(current_user, category, name=form.name.data, icon=form.icon.data, blurb=form.blurb.data, sort_order=form.sort_order.data)
        except AdminPermissionError:
            abort(403)
        except AdminRuleError as error:
            form_error = str(error)
        else:
            flash(f"Category “{category.name}” saved.", "success")
            return redirect(url_for("admin.services"))
    return render_template("admin/category_form.html", form=form, mode="edit", category=category, form_error=form_error)


@bp.route("/categories/<slug>/delete", methods=["GET", "POST"])
@role_required(ROLE_ADMIN)
def category_delete(slug):
    category = catalog.get_category(slug)
    if category is None:
        abort(404)
    in_use = catalog_admin.service_count(category)
    if request.method == "POST":
        try:
            catalog_admin.delete_category(current_user, category)
        except AdminPermissionError:
            abort(403)
        except AdminRuleError as error:
            flash(str(error), "error")
        else:
            flash(f"Category “{category.name}” deleted.", "success")
        return redirect(url_for("admin.services"))
    blocked = f"This category still has {in_use} service(s). Move or delete them first." if in_use else None
    return render_template(
        "admin/confirm_delete.html", kind="category", name=category.name, blocked=blocked,
        action_url=url_for("admin.category_delete", slug=category.slug), back_url=url_for("admin.services"), note="",
    )
