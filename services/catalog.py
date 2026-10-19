"""Read-only access to services and categories, backed by the database.

These functions keep the same names and results they had in Stage 1, so the
routes and templates barely changed. They must be called inside a Flask
request or app context.

Note: the category filter runs in SQL. Matching the typed search words runs
in Python over the (small) result so the rules stay exactly as in Stage 1.
When the catalogue grows large this can move into SQL.
"""
from sqlalchemy import and_, func, select
from sqlalchemy.orm import contains_eager

from extensions import db
from models import Service, ServiceCategory
from services.search import matches_terms, tokenize


def _service_query():
    """Available services with their category loaded, in a stable display order."""
    return (
        select(Service)
        .join(Service.category)
        .options(contains_eager(Service.category))
        .where(Service.is_available.is_(True))
        .order_by(ServiceCategory.sort_order, ServiceCategory.id, Service.id)
    )


def list_categories():
    stmt = select(ServiceCategory).order_by(ServiceCategory.sort_order, ServiceCategory.id)
    return list(db.session.scalars(stmt))


def get_category(slug):
    if not slug:
        return None
    return db.session.scalar(select(ServiceCategory).where(ServiceCategory.slug == slug))


def list_services():
    return list(db.session.scalars(_service_query()))


def get_service(slug):
    if not slug:
        return None
    return db.session.scalar(_service_query().where(Service.slug == slug))


def featured_services():
    """The first service of each category, used on the homepage."""
    seen, featured = set(), []
    for service in list_services():
        if service.category_id not in seen:
            seen.add(service.category_id)
            featured.append(service)
    return featured


def related_services(service, limit=3):
    """Other services in the same category."""
    stmt = _service_query().where(Service.category_id == service.category_id, Service.id != service.id).limit(limit)
    return list(db.session.scalars(stmt))


def count_by_category():
    """Return {category_slug: number_of_services}, including categories with zero."""
    stmt = (
        select(ServiceCategory.slug, func.count(Service.id))
        .outerjoin(Service, and_(Service.category_id == ServiceCategory.id, Service.is_available.is_(True)))
        .group_by(ServiceCategory.id, ServiceCategory.slug)
    )
    return {slug: count for slug, count in db.session.execute(stmt)}


def _searchable_words(service):
    text = " ".join([service.name, service.summary, service.description, service.category.name, service.provider_name])
    return tokenize(text)


def search_services(query="", category_slug=""):
    """Filter services by free-text query and/or category. Unknown categories are ignored."""
    stmt = _service_query()
    category = get_category(category_slug)
    if category is not None:
        stmt = stmt.where(Service.category_id == category.id)
    results = list(db.session.scalars(stmt))

    query = (query or "").strip()
    if not query:
        return results

    terms = tokenize(query)
    if not terms:  # the query was only punctuation
        return []
    return [s for s in results if matches_terms(_searchable_words(s), terms)]
