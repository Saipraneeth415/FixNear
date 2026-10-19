"""Stage 3 tests: database tables, seeding, models, catalogue queries,
persistence and database error handling.

Every test uses its own temporary SQLite file (see tests/helpers.py).
"""
import unittest

from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from app import create_app
from extensions import db
from models import Service, ServiceCategory
from services import catalog, sample_data
from services.seed import seed_database, tables_exist
from tests.helpers import DatabaseTestCase, make_config

SLUG = "leak-detection-pipe-repair"


def new_service(category, slug="custom-sample-service", **overrides):
    values = dict(
        slug=slug, name="Custom Test Service", category=category, summary="A short summary.",
        description="A longer description.", price_from=100, duration="1 hour", includes=["One thing"],
        provider_name="Sample Provider Z", provider_area="Test zone", provider_bio="Bio.", is_sample=True,
    )
    values.update(overrides)
    return Service(**values)


def count(model):
    return db.session.scalar(select(func.count(model.id)))


class DatabaseSetupTests(DatabaseTestCase):
    seed = False

    def test_tests_use_a_temporary_database_not_the_real_one(self):
        uri = self.app.config["SQLALCHEMY_DATABASE_URI"]
        self.assertIn("fixnear-test-", uri)
        self.assertNotIn("fixnear.db", uri)
        self.assertNotIn("instance", uri)

    def test_expected_tables_exist(self):
        with self.app.app_context():
            tables = inspect(db.engine).get_table_names()
        self.assertIn("service_categories", tables)
        self.assertIn("services", tables)

    def test_service_table_has_expected_columns(self):
        with self.app.app_context():
            columns = {c["name"] for c in inspect(db.engine).get_columns("services")}
        for name in ("id", "slug", "name", "category_id", "price_from", "includes", "is_sample", "created_at", "updated_at"):
            self.assertIn(name, columns)

    def test_slug_is_unique_and_category_id_is_indexed(self):
        with self.app.app_context():
            inspector = inspect(db.engine)
            unique_columns = [u["column_names"] for u in inspector.get_unique_constraints("services")]
            index_columns = [i["column_names"] for i in inspector.get_indexes("services")]
        self.assertIn(["slug"], unique_columns)
        self.assertIn(["category_id"], index_columns)

    def test_starting_the_app_does_not_seed_or_delete_anything(self):
        with self.app.app_context():
            self.assertTrue(tables_exist())
            self.assertEqual(count(Service), 0)
            self.assertEqual(count(ServiceCategory), 0)

    def test_tables_exist_is_false_for_an_empty_database_file(self):
        app = create_app(make_config(self.tmpdir / "empty.db"))
        self.addCleanup(self.dispose, app)
        with app.app_context():
            self.assertFalse(tables_exist())


class SeedingTests(DatabaseTestCase):
    seed = False

    def test_first_run_creates_everything(self):
        with self.app.app_context():
            result = seed_database()
            self.assertEqual(result.categories_created, 6)
            self.assertEqual(result.services_created, 12)
            self.assertEqual(result.services_skipped, 0)
            self.assertEqual(count(ServiceCategory), 6)
            self.assertEqual(count(Service), 12)

    def test_second_run_adds_nothing(self):
        with self.app.app_context():
            seed_database()
            result = seed_database()
            self.assertEqual(result.categories_created, 0)
            self.assertEqual(result.categories_existing, 6)
            self.assertEqual(result.services_created, 0)
            self.assertEqual(result.services_skipped, 12)
            self.assertEqual(count(Service), 12)

    def test_running_three_times_creates_no_duplicate_slugs(self):
        with self.app.app_context():
            for _ in range(3):
                seed_database()
            slugs = list(db.session.scalars(select(Service.slug)))
            self.assertEqual(len(slugs), len(set(slugs)))
            self.assertEqual(len(slugs), 12)

    def test_existing_edits_are_preserved(self):
        with self.app.app_context():
            seed_database()
            service = db.session.scalar(select(Service).where(Service.slug == SLUG))
            service.price_from = 12345
            service.name = "Edited Name"
            db.session.commit()
            seed_database()
            service = db.session.scalar(select(Service).where(Service.slug == SLUG))
            self.assertEqual(service.price_from, 12345)
            self.assertEqual(service.name, "Edited Name")

    def test_extra_records_are_preserved(self):
        with self.app.app_context():
            seed_database()
            category = db.session.scalar(select(ServiceCategory).where(ServiceCategory.slug == "plumbing"))
            db.session.add(new_service(category))
            db.session.commit()
            seed_database()
            self.assertEqual(count(Service), 13)
            self.assertIsNotNone(db.session.scalar(select(Service).where(Service.slug == "custom-sample-service")))

    def test_a_deleted_sample_service_is_restored_without_touching_others(self):
        with self.app.app_context():
            seed_database()
            db.session.delete(db.session.scalar(select(Service).where(Service.slug == SLUG)))
            db.session.commit()
            result = seed_database()
            self.assertEqual(result.services_created, 1)
            self.assertEqual(result.services_skipped, 11)
            self.assertEqual(count(Service), 12)

    def test_seeded_content_matches_the_sample_data_exactly(self):
        with self.app.app_context():
            seed_database()
            for sample in sample_data.SERVICES:
                row = db.session.scalar(select(Service).where(Service.slug == sample.slug))
                self.assertIsNotNone(row, sample.slug)
                self.assertEqual(row.name, sample.name)
                self.assertEqual(row.summary, sample.summary)
                self.assertEqual(row.description, sample.description)
                self.assertEqual(row.price_from, sample.price_from)
                self.assertEqual(row.duration, sample.duration)
                self.assertEqual(row.includes, list(sample.includes))
                self.assertEqual(row.provider_name, sample.provider_name)
                self.assertEqual(row.provider_area, sample.provider_area)
                self.assertEqual(row.provider_bio, sample.provider_bio)
                self.assertEqual(row.category.slug, sample.category_slug)

    def test_seeded_categories_keep_name_icon_blurb_and_order(self):
        with self.app.app_context():
            seed_database()
            categories = catalog.list_categories()
            self.assertEqual([c.slug for c in categories], [c.slug for c in sample_data.CATEGORIES])
            for row, sample in zip(categories, sample_data.CATEGORIES):
                self.assertEqual((row.name, row.icon, row.blurb), (sample.name, sample.icon, sample.blurb))

    def test_everything_seeded_is_marked_as_sample(self):
        with self.app.app_context():
            seed_database()
            for service in db.session.scalars(select(Service)):
                self.assertTrue(service.is_sample)
                self.assertIn("Sample", service.provider_name)


class ModelTests(DatabaseTestCase):
    def test_category_has_many_services_and_service_has_one_category(self):
        with self.app.app_context():
            plumbing = db.session.scalar(select(ServiceCategory).where(ServiceCategory.slug == "plumbing"))
            self.assertEqual(len(plumbing.services), 2)
            self.assertEqual(plumbing.services[0].category.slug, "plumbing")
            self.assertEqual(plumbing.services[0].category_slug, "plumbing")

    def test_includes_list_round_trips(self):
        with self.app.app_context():
            service = db.session.scalar(select(Service).where(Service.slug == SLUG))
            self.assertEqual(service.includes[0], "Inspection of the affected area")
            self.assertIsInstance(service.includes, list)

    def test_timestamps_are_set_and_updated_at_moves_forward(self):
        with self.app.app_context():
            service = db.session.scalar(select(Service).where(Service.slug == SLUG))
            self.assertIsNotNone(service.created_at)
            self.assertIsNotNone(service.updated_at)
            service.price_from = 555
            db.session.commit()
            db.session.refresh(service)
            self.assertGreaterEqual(service.updated_at, service.created_at)

    def test_duplicate_slug_is_rejected(self):
        with self.app.app_context():
            category = db.session.scalar(select(ServiceCategory))
            db.session.add(new_service(category, slug=SLUG))
            with self.assertRaises(IntegrityError):
                db.session.commit()
            db.session.rollback()
            self.assertEqual(count(Service), 12)  # the session still works afterwards

    def test_negative_price_is_rejected(self):
        with self.app.app_context():
            category = db.session.scalar(select(ServiceCategory))
            db.session.add(new_service(category, price_from=-5))
            with self.assertRaises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_service_must_belong_to_an_existing_category(self):
        with self.app.app_context():
            orphan = new_service(None)
            orphan.category_id = 99999
            db.session.add(orphan)
            with self.assertRaises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_category_with_services_cannot_be_deleted(self):
        with self.app.app_context():
            category = db.session.scalar(select(ServiceCategory).where(ServiceCategory.slug == "plumbing"))
            db.session.delete(category)
            with self.assertRaises(IntegrityError):
                db.session.commit()
            db.session.rollback()
            self.assertEqual(count(ServiceCategory), 6)


class CatalogFunctionTests(DatabaseTestCase):
    def test_services_come_back_in_the_original_order(self):
        with self.app.app_context():
            self.assertEqual([s.slug for s in catalog.list_services()], [s.slug for s in sample_data.SERVICES])

    def test_get_service(self):
        with self.app.app_context():
            self.assertEqual(catalog.get_service(SLUG).name, "Leak Detection & Pipe Repair")
            self.assertIsNone(catalog.get_service("nope"))
            self.assertIsNone(catalog.get_service(""))

    def test_get_category(self):
        with self.app.app_context():
            self.assertEqual(catalog.get_category("plumbing").name, "Plumbing")
            self.assertIsNone(catalog.get_category("nope"))
            self.assertIsNone(catalog.get_category(""))

    def test_featured_has_one_service_per_category(self):
        with self.app.app_context():
            featured = catalog.featured_services()
            self.assertEqual(len(featured), 6)
            self.assertEqual(len({s.category_id for s in featured}), 6)

    def test_related_services_share_the_category_and_exclude_the_service(self):
        with self.app.app_context():
            service = catalog.get_service(SLUG)
            related = catalog.related_services(service)
            self.assertEqual([s.slug for s in related], ["bathroom-fixture-installation"])

    def test_count_by_category(self):
        with self.app.app_context():
            counts = catalog.count_by_category()
            self.assertEqual(len(counts), 6)
            self.assertTrue(all(value == 2 for value in counts.values()))

    def test_search_and_filter_read_from_the_database(self):
        with self.app.app_context():
            self.assertIn(SLUG, [s.slug for s in catalog.search_services("leak")])
            self.assertEqual(len(catalog.search_services("", "plumbing")), 2)
            self.assertEqual(len(catalog.search_services("", "not-a-category")), 12)
            self.assertEqual(catalog.search_services("!!!"), [])
            self.assertEqual(catalog.search_services("laptop cleaning"), [])
            self.assertEqual([s.slug for s in catalog.search_services("repair", "plumbing")], [SLUG])


class WebPagesUseTheDatabaseTests(DatabaseTestCase):
    def add_service(self, **overrides):
        with self.app.app_context():
            category = db.session.scalar(select(ServiceCategory).where(ServiceCategory.slug == "plumbing"))
            db.session.add(new_service(category, **overrides))
            db.session.commit()

    def get(self, url, status=200):
        response = self.client.get(url)
        self.assertEqual(response.status_code, status, url)
        return response.get_data(as_text=True)

    def test_a_service_added_to_the_database_appears_on_the_site(self):
        self.add_service(name="Brand New Tap Fitting")
        self.assertIn("Brand New Tap Fitting", self.get("/services"))
        self.assertIn("Brand New Tap Fitting", self.get("/services?q=brand"))
        self.assertIn("Brand New Tap Fitting", self.get("/services?category=plumbing"))
        self.assertIn("Brand New Tap Fitting", self.get("/services/custom-sample-service"))
        self.assertIn("13 services found", self.get("/services"))

    def test_a_non_sample_service_has_no_sample_badge(self):
        self.add_service(is_sample=False)
        html = self.get("/services/custom-sample-service")
        self.assertNotIn("badge-sample", html)
        self.assertNotIn("Sample price for development", html)

    def test_a_sample_service_shows_the_sample_badge(self):
        self.assertIn("badge-sample", self.get(f"/services/{SLUG}"))

    def test_editing_a_service_in_the_database_changes_the_page(self):
        with self.app.app_context():
            service = db.session.scalar(select(Service).where(Service.slug == SLUG))
            service.price_from = 4321
            db.session.commit()
        self.assertIn("4,321", self.get(f"/services/{SLUG}"))

    def test_an_empty_category_is_listed_with_zero_services(self):
        with self.app.app_context():
            db.session.add(ServiceCategory(slug="gardening", name="Gardening", icon="sparkles", blurb="Lawns and plants.", sort_order=99))
            db.session.commit()
        html = self.get("/")
        self.assertIn("Gardening", html)
        self.assertIn("0 services", html)
        self.assertIn("0 services found", self.get("/services?category=gardening"))

    def test_the_all_chip_shows_the_total(self):
        self.assertRegex(self.get("/services"), r"All <span class=\"chip-count\">12</span>")


class PersistenceTests(DatabaseTestCase):
    def test_data_survives_an_app_restart(self):
        self.dispose(self.app)  # close the first app completely
        restarted = create_app(make_config(self.db_path))  # same file, brand-new app
        self.addCleanup(self.dispose, restarted)
        with restarted.app_context():
            self.assertEqual(count(Service), 12)
            self.assertEqual(count(ServiceCategory), 6)
        response = restarted.test_client().get(f"/services/{SLUG}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Leak Detection &amp; Pipe Repair", response.get_data(as_text=True))

    def test_edits_survive_an_app_restart(self):
        with self.app.app_context():
            service = db.session.scalar(select(Service).where(Service.slug == SLUG))
            service.price_from = 999
            db.session.commit()
        self.dispose(self.app)
        restarted = create_app(make_config(self.db_path))
        self.addCleanup(self.dispose, restarted)
        with restarted.app_context():
            self.assertEqual(db.session.scalar(select(Service.price_from).where(Service.slug == SLUG)), 999)


class SeedCommandTests(DatabaseTestCase):
    seed = False

    def run_command(self, app, *args):
        return app.test_cli_runner().invoke(args=list(args))

    def test_seed_db_creates_then_skips(self):
        first = self.run_command(self.app, "seed-db")
        self.assertEqual(first.exit_code, 0, first.output)
        self.assertIn("Categories: 6 created", first.output)
        self.assertIn("Services: 12 created, 0 skipped", first.output)

        second = self.run_command(self.app, "seed-db")
        self.assertEqual(second.exit_code, 0, second.output)
        self.assertIn("Services: 0 created, 12 skipped", second.output)
        with self.app.app_context():
            self.assertEqual(count(Service), 12)

    def test_seed_db_explains_what_to_do_when_tables_are_missing(self):
        app = create_app(make_config(self.tmpdir / "no-tables.db"))
        self.addCleanup(self.dispose, app)
        result = self.run_command(app, "seed-db")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("db upgrade", result.output)

    def test_db_stats_reports_counts(self):
        self.run_command(self.app, "seed-db")
        result = self.run_command(self.app, "db-stats")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Services: 12", result.output)
        self.assertIn("Service categories: 6", result.output)


class DatabaseErrorHandlingTests(DatabaseTestCase):
    def drop_tables(self):
        with self.app.app_context():
            db.drop_all()

    def test_a_broken_database_shows_a_safe_500_page(self):
        self.drop_tables()
        with self.assertLogs(self.app.logger, level="ERROR"):
            response = self.client.get("/services")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 500)
        self.assertIn("Something went wrong", body)
        for secret in ("OperationalError", "no such table", "Traceback", "SELECT", "sqlite"):
            self.assertNotIn(secret, body)

    def test_the_homepage_also_fails_safely(self):
        self.drop_tables()
        with self.assertLogs(self.app.logger, level="ERROR"):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 500)
        self.assertIn("Something went wrong", response.get_data(as_text=True))

    def test_pages_that_need_no_data_still_work_without_tables(self):
        self.drop_tables()
        self.assertEqual(self.client.get("/about").status_code, 200)
        self.assertEqual(self.client.get("/no-such-page").status_code, 404)


if __name__ == "__main__":
    unittest.main()
