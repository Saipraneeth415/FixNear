"""Public pages: home, service search, service details, about, contact."""
from flask import Blueprint, abort, render_template, request

from services import catalog

bp = Blueprint("main", __name__)

MAX_QUERY_LENGTH = 100


@bp.route("/")
def index():
    return render_template(
        "index.html",
        featured=catalog.featured_services(),
        counts=catalog.count_by_category(),
    )


@bp.route("/services")
def services():
    query = request.args.get("q", "").strip()[:MAX_QUERY_LENGTH]
    category_slug = request.args.get("category", "").strip().lower()
    category = catalog.get_category(category_slug)  # None if missing or invalid

    results = catalog.search_services(query, category.slug if category else "")
    counts = catalog.count_by_category()
    return render_template(
        "services.html",
        results=results,
        query=query,
        active_category=category,
        counts=counts,
        total=sum(counts.values()),
    )


@bp.route("/services/<slug>")
def service_detail(slug):
    service = catalog.get_service(slug)
    if service is None:
        abort(404)
    return render_template(
        "service_detail.html",
        service=service,
        category=service.category,
        related=catalog.related_services(service),
    )


@bp.route("/about")
def about():
    return render_template("about.html")


@bp.route("/contact")
def contact():
    return render_template("contact.html")
