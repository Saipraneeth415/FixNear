"""Safe, repeatable seeding of the sample catalogue.

Rules:
  * Never deletes anything.
  * Never overwrites a record that already exists (so edits are kept).
  * Running it again adds nothing new, so no duplicates.
"""
from dataclasses import dataclass

from sqlalchemy import inspect, select

from extensions import db
from models import Service, ServiceCategory
from services import sample_data

REQUIRED_TABLES = ("service_categories", "services")


@dataclass
class SeedResult:
    categories_created: int = 0
    categories_existing: int = 0
    services_created: int = 0
    services_skipped: int = 0


def tables_exist():
    """True when the database already has the tables the catalogue needs."""
    inspector = inspect(db.engine)
    return all(inspector.has_table(name) for name in REQUIRED_TABLES)


def seed_database():
    """Insert missing sample categories and services. Returns a SeedResult."""
    result = SeedResult()
    categories = {c.slug: c for c in db.session.scalars(select(ServiceCategory))}
    known_service_slugs = set(db.session.scalars(select(Service.slug)))

    try:
        for position, sample in enumerate(sample_data.CATEGORIES):
            if sample.slug in categories:
                result.categories_existing += 1
                continue
            category = ServiceCategory(
                slug=sample.slug,
                name=sample.name,
                icon=sample.icon,
                blurb=sample.blurb,
                sort_order=position,
            )
            db.session.add(category)
            categories[sample.slug] = category
            result.categories_created += 1

        for sample in sample_data.SERVICES:
            if sample.slug in known_service_slugs:
                result.services_skipped += 1
                continue
            db.session.add(
                Service(
                    slug=sample.slug,
                    name=sample.name,
                    category=categories[sample.category_slug],
                    summary=sample.summary,
                    description=sample.description,
                    price_from=sample.price_from,
                    duration=sample.duration,
                    includes=list(sample.includes),
                    provider_name=sample.provider_name,
                    provider_area=sample.provider_area,
                    provider_bio=sample.provider_bio,
                    is_sample=True,
                )
            )
            known_service_slugs.add(sample.slug)
            result.services_created += 1

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return result
