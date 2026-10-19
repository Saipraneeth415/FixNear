"""Stage 1 tests: homepage, search, category filters, details, errors, links.

Written with unittest so they run with no extra packages:
    python -m unittest discover -s tests -v
They also work unchanged with pytest once it is installed.
"""
import unittest
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

from services import sample_data
from tests.helpers import DatabaseTestCase


class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.add(attrs["href"])
        if tag in ("link", "script") and (attrs.get("href") or attrs.get("src")):
            self.links.add(attrs.get("href") or attrs.get("src"))


class BaseTest(DatabaseTestCase):
    """Each test gets a temporary database that already holds the sample data."""

    def get_text(self, url, status=200):
        response = self.client.get(url)
        self.assertEqual(response.status_code, status, f"{url} returned {response.status_code}")
        return response.get_data(as_text=True)


class CatalogDataTests(unittest.TestCase):
    """Checks the sample data used to seed the database."""

    def test_unique_slugs(self):
        slugs = [s.slug for s in sample_data.SERVICES]
        self.assertEqual(len(slugs), len(set(slugs)))
        cat_slugs = [c.slug for c in sample_data.CATEGORIES]
        self.assertEqual(len(cat_slugs), len(set(cat_slugs)))

    def test_every_service_has_a_valid_category(self):
        for service in sample_data.SERVICES:
            self.assertIn(service.category_slug, {c.slug for c in sample_data.CATEGORIES}, service.slug)

    def test_six_required_categories_exist(self):
        self.assertEqual(len(sample_data.CATEGORIES), 6)

    def test_all_sample_providers_are_labelled_sample(self):
        for service in sample_data.SERVICES:
            self.assertIn("Sample", service.provider_name)


class HomepageTests(BaseTest):
    def test_homepage_loads_with_key_sections(self):
        html = self.get_text("/")
        self.assertIn("FixNear", html)
        self.assertIn("Search services", html)
        self.assertIn("How it works", html)
        self.assertIn("Popular services", html)
        self.assertIn("Why use FixNear", html)
        self.assertIn("<footer", html)

    def test_homepage_lists_all_categories(self):
        html = self.get_text("/")
        for category in sample_data.CATEGORIES:
            self.assertIn(category.name.replace("&", "&amp;"), html)

    def test_homepage_labels_sample_data(self):
        self.assertIn("sample data", self.get_text("/").lower())

    def test_homepage_shows_one_featured_service_per_category(self):
        html = self.get_text("/")
        seen = set()
        for service in sample_data.SERVICES:
            if service.category_slug in seen:
                continue
            seen.add(service.category_slug)
            self.assertIn(f"/services/{service.slug}", html)

    def test_page_has_lang_title_and_viewport(self):
        html = self.get_text("/")
        self.assertIn('<html lang="en">', html)
        self.assertIn("<title>", html)
        self.assertIn('name="viewport"', html)
        self.assertIn('class="skip-link"', html)


class SearchTests(BaseTest):
    def test_services_page_lists_all_services(self):
        html = self.get_text("/services")
        self.assertIn(f"{len(sample_data.SERVICES)} services found", html)

    def test_search_finds_matching_service(self):
        html = self.get_text("/services?q=leak")
        self.assertIn("Leak Detection &amp; Pipe Repair", html)
        self.assertNotIn("Laptop Screen", html)

    def test_search_is_case_insensitive_and_trims_spaces(self):
        a = self.get_text("/services?q=LAPTOP")
        b = self.get_text("/services?q=%20%20laptop%20%20")
        self.assertIn("Laptop Screen &amp; Battery Replacement", a)
        self.assertIn("Laptop Screen &amp; Battery Replacement", b)

    def test_search_matches_word_starts(self):
        self.assertIn("Leak Detection", self.get_text("/services?q=plumb"))

    def test_search_requires_every_word_to_match(self):
        html = self.get_text("/services?q=laptop+cleaning")
        self.assertIn("0 services found", html)

    def test_search_no_results_shows_empty_state(self):
        html = self.get_text("/services?q=spaceship")
        self.assertIn("No services match your search", html)
        self.assertIn("Clear filters", html)

    def test_punctuation_only_query_is_safe(self):
        html = self.get_text("/services?q=%21%21%21")
        self.assertIn("0 services found", html)

    def test_search_input_is_escaped(self):
        payload = "<script>alert(1)</script>"
        html = self.get_text("/services?q=" + payload)
        self.assertNotIn(payload, html)
        self.assertIn("&lt;script&gt;", html)

    def test_very_long_query_is_handled(self):
        self.get_text("/services?q=" + "a" * 5000)

    def test_search_form_only_accepts_get(self):
        self.assertEqual(self.client.post("/services").status_code, 405)


class CategoryFilterTests(BaseTest):
    def test_each_category_filter_shows_only_that_category(self):
        for category in sample_data.CATEGORIES:
            html = self.get_text(f"/services?category={category.slug}")
            expected = [s for s in sample_data.SERVICES if s.category_slug == category.slug]
            self.assertIn(f"{len(expected)} services found", html, category.slug)
            for service in sample_data.SERVICES:
                link = f"/services/{service.slug}"
                if service.category_slug == category.slug:
                    self.assertIn(link, html)
                else:
                    self.assertNotIn(link, html)

    def test_invalid_category_is_ignored(self):
        html = self.get_text("/services?category=not-a-real-category")
        self.assertIn(f"{len(sample_data.SERVICES)} services found", html)

    def test_search_and_category_combine(self):
        html = self.get_text("/services?q=repair&category=plumbing")
        self.assertIn("Leak Detection", html)
        self.assertNotIn("Switch, Socket", html)

    def test_active_category_chip_is_marked(self):
        html = self.get_text("/services?category=plumbing")
        self.assertIn('aria-current="true"', html)


class ServiceDetailTests(BaseTest):
    def test_every_service_has_a_working_detail_page(self):
        for service in sample_data.SERVICES:
            html = self.get_text(f"/services/{service.slug}")
            self.assertIn(service.name.replace("&", "&amp;"), html)
            self.assertIn("Sample data", html)
            self.assertIn("What is included", html)

    def test_service_cards_link_to_the_correct_detail_page(self):
        html = self.get_text("/services")
        for service in sample_data.SERVICES:
            self.assertIn(f'href="/services/{service.slug}"', html)

    def test_detail_page_shows_related_services(self):
        html = self.get_text("/services/leak-detection-pipe-repair")
        self.assertIn("Bathroom Fixture Installation", html)

    def test_unknown_service_returns_custom_404(self):
        html = self.get_text("/services/does-not-exist", status=404)
        self.assertIn("Page not found", html)

    def test_book_button_links_to_the_booking_flow(self):
        # Stage 5 replaced the disabled Stage 1 button. A visitor who is not
        # logged in is sent to log in first and then back to the booking form.
        html = self.get_text("/services/leak-detection-pipe-repair")
        self.assertIn("Book this service", html)
        collector = LinkCollector()
        collector.feed(html)
        next_targets = []
        for href in collector.links:
            parsed = urlparse(href)
            if parsed.path == "/login" and "next" in parse_qs(parsed.query):
                next_targets.extend(parse_qs(parsed.query)["next"])
        self.assertEqual(next_targets, ["/services/leak-detection-pipe-repair/book"])
        self.assertNotIn("disabled", html)


class NavigationAndStaticTests(BaseTest):
    def test_every_internal_link_resolves(self):
        checked = set()
        for page in ["/", "/services", "/services/split-ac-installation", "/about", "/contact"]:
            collector = LinkCollector()
            collector.feed(self.get_text(page))
            for href in collector.links:
                if href.startswith(("#", "http", "mailto:")):
                    continue
                if href in checked:
                    continue
                checked.add(href)
                response = self.client.get(href)
                status = response.status_code
                response.close()
                self.assertEqual(status, 200, f"{href} (linked from {page})")
        self.assertGreater(len(checked), 15)

    def test_static_files_are_served(self):
        for path in ["/static/css/style.css", "/static/js/main.js", "/static/images/favicon.svg"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            response.close()

    def test_about_and_contact_pages(self):
        self.assertIn("About FixNear", self.get_text("/about"))
        self.assertIn("Contact", self.get_text("/contact"))


class ErrorAndSecurityTests(DatabaseTestCase):
    def test_404_page_is_custom(self):
        response = self.client.get("/no-such-page")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Page not found", response.get_data(as_text=True))

    def test_403_page_is_custom(self):
        from flask import abort

        @self.app.route("/_forbidden")
        def _forbidden():
            abort(403)

        response = self.client.get("/_forbidden")
        self.assertEqual(response.status_code, 403)
        self.assertIn("Access denied", response.get_data(as_text=True))

    def test_500_page_hides_internal_details(self):
        self.app.config["PROPAGATE_EXCEPTIONS"] = False

        @self.app.route("/_boom")
        def _boom():
            raise RuntimeError("secret internal detail")

        response = self.client.get("/_boom")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 500)
        self.assertIn("Something went wrong", body)
        self.assertNotIn("secret internal detail", body)
        self.assertNotIn("Traceback", body)

    def test_security_headers_are_set(self):
        response = self.client.get("/")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("Referrer-Policy", response.headers)

    def test_debug_is_off_by_default(self):
        self.assertFalse(self.app.debug)


if __name__ == "__main__":
    unittest.main()
