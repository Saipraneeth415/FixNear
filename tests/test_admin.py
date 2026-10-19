"""Stage 7 tests: admin authorization, dashboard numbers, user management,
service and category management, and the all-bookings view.

Every test uses its own temporary SQLite database. CSRF protection stays ON.
"""
from sqlalchemy import func, select

from extensions import db
from models import ROLE_ADMIN, ROLE_CUSTOMER, Booking, Service, ServiceCategory, User, provider_services
from services import accounts, catalog, providers
from services import admin as admin_service
from services import booking_rules as rules
from services import catalog_admin
from services.errors import AdminPermissionError, AdminRuleError
from tests.test_auth import PASSWORD, TOKEN_RE
from tests.test_bookings import OTHER_SLUG, SLUG
from tests.test_provider import THIRD_SLUG, ProviderTestCase

SERVICE_FORM = {
    "name": "Brand New Service", "slug": "brand-new-service", "summary": "A short summary.", "description": "A longer description of the service.",
    "price_from": "250", "duration": "1 to 2 hours", "includes": "First thing\nSecond thing\n\n  Third   thing ", "provider_name": "Sample Provider Z",
    "provider_area": "Central zone", "provider_bio": "", "is_available": "y", "is_sample": "",
}
CATEGORY_FORM = {"name": "Gardening", "slug": "gardening", "icon": "sparkles", "blurb": "Lawns and plants.", "sort_order": "7"}


class AdminTestCase(ProviderTestCase):
    """Helpers for admin tests. The catalogue is seeded; one active admin exists but is not logged in."""

    def setUp(self):
        super().setUp()
        self.admin_email = "boss@example.com"
        self.make_user(self.admin_email, role=ROLE_ADMIN, full_name="Boss Admin")

    def as_admin(self):
        self.login(email=self.admin_email)

    def client_for(self, email):
        """A separate browser logged in as someone else."""
        client = self.app.test_client()
        token = TOKEN_RE.search(client.get("/login").get_data(as_text=True)).group(1)
        client.post("/login", data={"email": email, "password": PASSWORD, "csrf_token": token})
        return client

    def category_id(self, slug="plumbing"):
        with self.app.app_context():
            return catalog.get_category(slug).id

    def service_form(self, **overrides):
        data = dict(SERVICE_FORM, category_id=str(self.category_id()))
        data.update(overrides)
        return {key: value for key, value in data.items() if value is not None}

    def admin_post(self, url, data=None, token_url="/admin/dashboard", **extra):
        payload = {"csrf_token": self.token(token_url), **(data or {}), **extra}
        return self.client.post(url, data=payload)

    def user_id_of(self, email):
        return self.user_id(email)

    def db_state(self):
        """Everything an admin action could change, so 'nothing changed' can be proven."""
        with self.app.app_context():
            return (
                [(u.id, u.email, u.role, u.is_active, u.password_hash) for u in db.session.scalars(select(User).order_by(User.id))],
                [(s.id, s.slug, s.name, s.price_from, s.is_available, s.category_id, s.summary, tuple(s.includes)) for s in db.session.scalars(select(Service).order_by(Service.id))],
                [(c.id, c.slug, c.name, c.icon, c.blurb, c.sort_order) for c in db.session.scalars(select(ServiceCategory).order_by(ServiceCategory.id))],
                sorted(tuple(row) for row in db.session.execute(select(provider_services.c.provider_id, provider_services.c.service_id))),
                [(b.id, b.reference, b.status, b.provider_id, b.price_from_at_booking) for b in db.session.scalars(select(Booking).order_by(Booking.id))],
            )

    def bulk_users(self, count, prefix="bulk"):
        with self.app.app_context():
            for n in range(count):
                db.session.add(User(email=f"{prefix}{n:03d}@example.com", full_name=f"{prefix.title()} Person {n:03d}", password_hash="x", role=ROLE_CUSTOMER))
            db.session.commit()

    def bulk_bookings(self, count, customer_email="cust@example.com"):
        with self.app.app_context():
            customer_id = accounts.get_user_by_email(customer_email).id
            service_id = db.session.scalar(select(Service.id).where(Service.slug == THIRD_SLUG))
            for n in range(count):
                db.session.add(Booking(
                    reference=rules.generate_reference(), customer_id=customer_id, service_id=service_id, contact_name="Test User",
                    contact_phone="9876543210", address="12 Main Road, Test Area", appointment_date=self.day(3), appointment_time=rules.parse_time_slot("10:00"),
                    problem_description="The tap leaks badly.", price_from_at_booking=399,
                ))
            db.session.commit()

    def rows_in(self, html, emails):
        return [email for email in emails if email in html]


# ===================================================== 1. who can get in
class AdminAuthorizationTests(AdminTestCase):
    def setUp(self):
        super().setUp()
        self.make_user("cust@example.com")
        self.make_provider("prov@example.com", services=(SLUG,))
        self.customer_ref = self.make_booking("cust@example.com")
        self.target = self.user_id_of("cust@example.com")
        self.get_urls = [
            "/admin/dashboard", "/admin/users", "/admin/bookings", "/admin/services", "/admin/services/new", f"/admin/services/{SLUG}/edit",
            f"/admin/services/{SLUG}/delete", "/admin/categories/new", "/admin/categories/plumbing/edit", "/admin/categories/plumbing/delete",
        ]
        cat = str(self.category_id())
        self.post_cases = [
            (f"/admin/users/{self.target}/deactivate", {}), (f"/admin/users/{self.target}/activate", {}),
            (f"/admin/services/{SLUG}/hide", {}), (f"/admin/services/{SLUG}/show", {}), (f"/admin/services/{OTHER_SLUG}/delete", {}),
            ("/admin/services/new", dict(SERVICE_FORM, category_id=cat)), (f"/admin/services/{SLUG}/edit", dict(SERVICE_FORM, category_id=cat, name="Hacked")),
            ("/admin/categories/new", CATEGORY_FORM), ("/admin/categories/plumbing/edit", dict(CATEGORY_FORM, name="Hacked")),
            ("/admin/categories/plumbing/delete", {}),
        ]

    def attempt_everything(self, expected_get, expected_post, token_url):
        before = self.db_state()
        for url in self.get_urls:
            self.assertEqual(self.client.get(url).status_code, expected_get, f"GET {url}")
        for url, data in self.post_cases:
            response = self.client.post(url, data={**data, "csrf_token": self.token(token_url)})
            self.assertEqual(response.status_code, expected_post, f"POST {url}")
        self.assertEqual(self.db_state(), before, "an unauthorized request changed the database")

    def test_visitors_are_sent_to_login_and_nothing_changes(self):
        self.attempt_everything(302, 302, "/login")
        self.assertIn("/login", self.location(self.client.get("/admin/users")))

    def test_visitors_posting_without_a_csrf_token_are_refused(self):
        before = self.db_state()
        for url, data in self.post_cases:
            self.assertEqual(self.client.post(url, data=data).status_code, 400, url)
        self.assertEqual(self.db_state(), before)

    def test_customers_are_refused_and_nothing_changes(self):
        self.login(email="cust@example.com")
        self.attempt_everything(403, 403, "/")

    def test_providers_are_refused_and_nothing_changes(self):
        self.login(email="prov@example.com")
        self.attempt_everything(403, 403, "/")

    def test_an_inactive_admin_cannot_log_in(self):
        self.make_user("old@example.com", role=ROLE_ADMIN, active=False)
        response = self.login(email="old@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Invalid email or password.", self.text(response))
        self.attempt_everything(302, 302, "/login")

    def test_an_admin_deactivated_while_logged_in_loses_access_immediately(self):
        other_admin = self.make_user("second@example.com", role=ROLE_ADMIN)
        self.login(email="second@example.com")
        self.assertEqual(self.client.get("/admin/users").status_code, 200)
        with self.app.app_context():
            db.session.get(User, other_admin).is_active = False
            db.session.commit()
        self.attempt_everything(302, 302, "/login")

    def test_an_active_admin_can_open_every_admin_page(self):
        self.as_admin()
        for url in self.get_urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_admin_pages_are_not_cached_and_changes_need_post(self):
        self.as_admin()
        for url in ("/admin/dashboard", "/admin/users", "/admin/bookings", "/admin/services"):
            self.assertEqual(self.client.get(url).headers["Cache-Control"], "no-store", url)
        for url in (f"/admin/users/{self.target}/deactivate", f"/admin/services/{SLUG}/hide"):
            self.assertEqual(self.client.get(url).status_code, 405, url)
        self.assertEqual(self.client.post("/admin/bookings", data={"csrf_token": self.token("/admin/dashboard")}).status_code, 405)

    def test_customer_pages_contain_no_links_to_admin_pages(self):
        self.login(email="cust@example.com")
        self.assertNotIn("/admin/", self.text(self.client.get("/customer/dashboard")))

    def test_service_layer_refuses_anyone_who_is_not_an_active_admin(self):
        with self.app.app_context():
            customer = accounts.get_user_by_email("cust@example.com")
            provider = accounts.get_user_by_email("prov@example.com")
            admin = accounts.get_user_by_email(self.admin_email)
            admin.is_active = False
            db.session.commit()
            for actor in (customer, provider, admin, None):
                with self.assertRaises(AdminPermissionError):
                    admin_service.set_user_active(actor, customer, False)
                with self.assertRaises(AdminPermissionError):
                    catalog_admin.create_category(actor, slug="x-cat", name="X Cat", icon="zap", blurb="b", sort_order=1)
                with self.assertRaises(AdminPermissionError):
                    catalog_admin.set_service_available(actor, catalog.get_service(SLUG), False)
                with self.assertRaises(AdminPermissionError):
                    catalog_admin.delete_service(actor, providers.get_service_by_slug(OTHER_SLUG))
            self.assertTrue(db.session.get(User, customer.id).is_active)
            self.assertTrue(providers.get_service_by_slug(SLUG).is_available)


# ===================================================== 2. dashboard numbers
class AdminDashboardTests(AdminTestCase):
    def build_world(self):
        for email in ("c1@example.com", "c2@example.com", "c3@example.com"):
            self.make_user(email)
        self.make_provider("p1@example.com", services=(SLUG,))
        self.make_booking("c1@example.com", slug=SLUG, slot="08:00")  # pending, assigned
        self.make_booking("c2@example.com", slug=THIRD_SLUG, slot="08:00")  # pending, unassigned
        accepted = self.make_booking("c1@example.com", slug=OTHER_SLUG, slot="10:00")
        done1 = self.make_booking("c2@example.com", slug=THIRD_SLUG, slot="12:00")
        done2 = self.make_booking("c3@example.com", slug=THIRD_SLUG, slot="14:00")
        self.set_status(accepted, "accepted")
        self.set_status(done1, "completed")
        self.set_status(done2, "completed")
        with self.app.app_context():
            db.session.get(User, self.user_id_of("c3@example.com")).is_active = False
            providers.get_service_by_slug("full-home-deep-cleaning").is_available = False
            db.session.commit()

    def test_every_number_is_correct(self):
        self.build_world()
        self.as_admin()
        html = self.text(self.client.get("/admin/dashboard"))
        expected = {"users": 5, "customers": 3, "providers": 1, "admins": 1, "inactive_users": 1, "services": 12, "bookings": 5,
                    "pending": 2, "accepted": 1, "in_progress": 0, "completed": 2}
        for name, value in expected.items():
            self.assertEqual(self.stat(html, name), value, name)
        self.assertIn("(11 available)", html)

    def test_numbers_are_read_live_not_cached(self):
        self.build_world()
        self.as_admin()
        before = self.text(self.client.get("/admin/dashboard"))
        self.make_user("c4@example.com")
        self.make_booking("c4@example.com", slug=THIRD_SLUG, slot="16:00")
        after = self.text(self.client.get("/admin/dashboard"))
        self.assertEqual(self.stat(after, "users"), self.stat(before, "users") + 1)
        self.assertEqual(self.stat(after, "bookings"), self.stat(before, "bookings") + 1)
        self.assertEqual(self.stat(after, "pending"), self.stat(before, "pending") + 1)

    def test_counts_agree_with_the_service_layer_and_with_raw_database_totals(self):
        self.build_world()
        with self.app.app_context():
            counts = admin_service.dashboard_counts()
            self.assertEqual(counts["users"], db.session.scalar(select(func.count(User.id))))
            self.assertEqual(counts["bookings"], db.session.scalar(select(func.count(Booking.id))))
            self.assertEqual(counts["services"], db.session.scalar(select(func.count(Service.id))))
            self.assertEqual(counts["pending"] + counts["accepted"] + counts["in_progress"] + counts["completed"], counts["bookings"])
            self.assertEqual(counts["customers"] + counts["providers"] + counts["admins"], counts["users"])

    def test_an_empty_system_shows_zeros_and_an_honest_empty_state(self):
        self.as_admin()
        html = self.text(self.client.get("/admin/dashboard"))
        self.assertEqual((self.stat(html, "bookings"), self.stat(html, "pending"), self.stat(html, "completed"), self.stat(html, "customers")), (0, 0, 0, 0))
        self.assertEqual((self.stat(html, "users"), self.stat(html, "admins")), (1, 1))
        self.assertIn("No bookings have been made yet.", html)

    def test_the_newest_bookings_are_listed_but_no_private_details(self):
        self.make_user("cust@example.com")
        refs = [self.make_booking("cust@example.com", slug=THIRD_SLUG, slot=rules.TIME_SLOTS[i * 4]) for i in range(6)]
        self.as_admin()
        html = self.text(self.client.get("/admin/dashboard"))
        self.assertEqual(sum(ref in html for ref in refs), 5)
        self.assertNotIn(refs[0], html)
        self.assertNotIn("12 Main Road", html)
        self.assertNotIn("9876543210", html)


# ===================================================== 3. user management
class AdminUserManagementTests(AdminTestCase):
    def setUp(self):
        super().setUp()
        self.make_user("cust@example.com", full_name="Carol Customer")
        self.make_user("other@example.com", full_name="Oscar Other")
        self.make_provider("prov@example.com", services=(SLUG,), full_name="Pat Provider")
        self.cust = self.user_id_of("cust@example.com")
        self.prov = self.user_id_of("prov@example.com")
        self.me = self.user_id_of(self.admin_email)

    def is_active(self, email):
        with self.app.app_context():
            return accounts.get_user_by_email(email).is_active

    def test_the_list_shows_everyone_with_role_and_status_but_no_secrets(self):
        with self.app.app_context():
            accounts.get_user_by_email("other@example.com").is_active = False
            db.session.commit()
        self.as_admin()
        html = self.text(self.client.get("/admin/users"))
        for email in ("cust@example.com", "other@example.com", "prov@example.com", self.admin_email):
            self.assertIn(email, html)
        for word in ("Customer", "Provider", "Admin", "Active", "Deactivated"):
            self.assertIn(word, html)
        for secret in ("scrypt", "pbkdf2", "password_hash"):
            self.assertNotIn(secret, html)

    def test_filters(self):
        self.as_admin()
        by_role = self.text(self.client.get("/admin/users?role=provider"))
        self.assertEqual(self.rows_in(by_role, ["cust@example.com", "prov@example.com", self.admin_email]), ["prov@example.com"])
        with self.app.app_context():
            accounts.get_user_by_email("other@example.com").is_active = False
            db.session.commit()
        inactive = self.text(self.client.get("/admin/users?status=inactive"))
        self.assertEqual(self.rows_in(inactive, ["cust@example.com", "other@example.com"]), ["other@example.com"])
        active = self.text(self.client.get("/admin/users?status=active"))
        self.assertNotIn("other@example.com", active)
        by_text = self.text(self.client.get("/admin/users?q=CAROL"))
        self.assertEqual(self.rows_in(by_text, ["cust@example.com", "other@example.com"]), ["cust@example.com"])
        self.assertEqual(self.rows_in(self.text(self.client.get("/admin/users?q=oscar%40example")), ["cust@example.com", "other@example.com"]), [])
        self.assertEqual(self.rows_in(self.text(self.client.get("/admin/users?q=other%40exam")), ["cust@example.com", "other@example.com"]), ["other@example.com"])

    def test_unknown_filter_values_are_ignored_and_wildcards_are_literal(self):
        self.make_user("under_score@example.com")
        self.as_admin()
        everything = self.text(self.client.get("/admin/users?role=hacker&status=maybe"))
        for email in ("cust@example.com", "prov@example.com", self.admin_email):
            self.assertIn(email, everything)
        underscore = self.text(self.client.get("/admin/users?q=_"))
        self.assertEqual(self.rows_in(underscore, ["under_score@example.com", "cust@example.com", "prov@example.com"]), ["under_score@example.com"])
        self.assertEqual(self.rows_in(self.text(self.client.get("/admin/users?q=%25")), ["cust@example.com", "prov@example.com"]), [])
        self.assertEqual(self.client.get("/admin/users?q=" + "x" * 5000).status_code, 200)

    def test_pagination(self):
        self.bulk_users(25)
        self.as_admin()
        first = self.text(self.client.get("/admin/users"))
        self.assertIn("Page 1 of 2", first)
        self.assertIn("Showing 1 to 20 of 29", first)
        second = self.text(self.client.get("/admin/users?page=2"))
        self.assertIn("Showing 21 to 29 of 29", second)
        self.assertNotEqual(first.count("@example.com"), 0)
        self.assertIn("Page 2 of 2", self.text(self.client.get("/admin/users?page=99")))  # clamped
        for bad in ("abc", "0", "-3", "2.5", "%E0%A5%AF"):
            self.assertIn("Page 1 of 2", self.text(self.client.get(f"/admin/users?page={bad}")), bad)

    def test_pagination_keeps_the_filters(self):
        self.bulk_users(25)
        self.as_admin()
        html = self.text(self.client.get("/admin/users?role=customer&q=bulk"))
        self.assertIn("role=customer", html.split('class="pagination"')[1])
        self.assertIn("page=2", html)

    def test_deactivating_and_reactivating_a_customer(self):
        customer = self.client_for("cust@example.com")
        self.assertEqual(customer.get("/customer/dashboard").status_code, 200)
        self.as_admin()
        response = self.admin_post(f"/admin/users/{self.cust}/deactivate", token_url="/admin/users")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.is_active("cust@example.com"))
        self.assertIn("cust@example.com has been deactivated.", self.follow(response))
        self.assertEqual(customer.get("/customer/dashboard").status_code, 302)  # their open session ends at once
        self.assertEqual(self.client_for("cust@example.com").get("/customer/dashboard").status_code, 302)  # and they cannot log in
        self.admin_post(f"/admin/users/{self.cust}/activate", token_url="/admin/users")
        self.assertTrue(self.is_active("cust@example.com"))
        self.assertEqual(self.client_for("cust@example.com").get("/customer/dashboard").status_code, 200)

    def test_deactivating_a_provider_keeps_their_bookings_and_warns(self):
        self.make_booking("cust@example.com")  # assigned to prov
        self.as_admin()
        before = self.db_state()
        response = self.admin_post(f"/admin/users/{self.prov}/deactivate", token_url="/admin/users")
        page = self.follow(response)
        self.assertIn("1 active booking(s) are still assigned", page)
        after = self.db_state()
        self.assertEqual(after[4], before[4])  # bookings untouched
        self.assertEqual(after[3], before[3])  # provider links untouched
        self.make_user("late@example.com")
        late_ref = self.make_booking("late@example.com", slot="16:00")
        self.assertIsNone(self.snap(late_ref).provider_id)  # new bookings skip the deactivated provider

    def test_an_admin_cannot_deactivate_themselves(self):
        self.as_admin()
        before = self.db_state()
        response = self.admin_post(f"/admin/users/{self.me}/deactivate", token_url="/admin/users")
        self.assertEqual(response.status_code, 302)
        self.assertIn("cannot deactivate your own account", self.follow(response))
        self.assertEqual(self.db_state(), before)
        self.assertEqual(self.client.get("/admin/users").status_code, 200)

    def test_the_users_page_offers_no_button_for_your_own_row(self):
        self.as_admin()
        html = self.text(self.client.get("/admin/users"))
        self.assertIn("This is you", html)
        self.assertNotIn(f"/admin/users/{self.me}/", html)
        self.assertIn(f"/admin/users/{self.cust}/deactivate", html)

    def test_activating_an_active_account_is_reported_and_changes_nothing(self):
        self.as_admin()
        before = self.db_state()
        self.assertIn("already active", self.follow(self.admin_post(f"/admin/users/{self.cust}/activate", token_url="/admin/users")))
        self.assertEqual(self.db_state(), before)

    def test_another_admin_can_be_deactivated_while_one_remains(self):
        other = self.make_user("second@example.com", role=ROLE_ADMIN)
        self.as_admin()
        self.admin_post(f"/admin/users/{other}/deactivate", token_url="/admin/users")
        self.assertFalse(self.is_active("second@example.com"))
        self.assertTrue(self.is_active(self.admin_email))

    def test_unknown_users_and_actions_are_a_404(self):
        self.as_admin()
        before = self.db_state()
        for url in ("/admin/users/99999/deactivate", "/admin/users/abc/deactivate", f"/admin/users/{self.cust}/delete", f"/admin/users/{self.cust}/promote", "/admin/users/-1/activate"):
            self.assertEqual(self.admin_post(url, token_url="/admin/users").status_code, 404, url)
        self.assertEqual(self.db_state(), before)

    def test_roles_and_passwords_can_never_be_changed_from_here(self):
        self.as_admin()
        before = self.db_state()
        self.admin_post(f"/admin/users/{self.cust}/deactivate", token_url="/admin/users", role="admin", password_hash="x", email="evil@example.com", is_active="1")
        after = self.db_state()
        customer_row = next(row for row in after[0] if row[0] == self.cust)
        original_row = next(row for row in before[0] if row[0] == self.cust)
        self.assertEqual((customer_row[1], customer_row[2], customer_row[4]), (original_row[1], original_row[2], original_row[4]))
        self.assertFalse(customer_row[3])  # only the status changed

    def test_user_changes_without_a_csrf_token_are_refused(self):
        self.as_admin()
        before = self.db_state()
        self.assertEqual(self.client.post(f"/admin/users/{self.cust}/deactivate").status_code, 400)
        self.assertEqual(self.db_state(), before)

    def test_the_return_address_is_safe(self):
        self.as_admin()
        for target, expected in [("https://evil.example/x", "/admin/users"), ("//evil.example", "/admin/users"), ("/customer/dashboard", "/admin/users"),
                                 ("/admin/users?role=provider", "/admin/users?role=provider"), ("/admin/bookings?status=pending", "/admin/bookings?status=pending")]:
            with self.subTest(target):
                response = self.admin_post(f"/admin/users/{self.cust}/deactivate", token_url="/admin/users", next=target)
                self.assertEqual(self.location(response), expected)
                self.admin_post(f"/admin/users/{self.cust}/activate", token_url="/admin/users")

    def test_service_layer_user_rules(self):
        with self.app.app_context():
            admin = accounts.get_user_by_email(self.admin_email)
            with self.assertRaises(AdminRuleError):
                admin_service.set_user_active(admin, admin, False)
            with self.assertRaises(AdminRuleError):
                admin_service.set_user_active(admin, None, False)
            self.assertEqual(admin_service.set_user_active(admin, accounts.get_user_by_email("cust@example.com"), False), 0)


# ===================================================== 4. service management
class AdminServiceManagementTests(AdminTestCase):
    def setUp(self):
        super().setUp()
        self.make_user("cust@example.com")
        self.as_admin()

    def service(self, slug):
        with self.app.app_context():
            s = providers.get_service_by_slug(slug)
            return None if s is None else {"name": s.name, "price": s.price_from, "available": s.is_available, "category": s.category.slug, "includes": list(s.includes), "sample": s.is_sample, "slug": s.slug}

    def test_the_services_page_lists_everything_with_counts(self):
        self.make_booking("cust@example.com", slug=SLUG)
        with self.app.app_context():
            providers.get_service_by_slug(OTHER_SLUG).is_available = False
            db.session.commit()
        html = self.text(self.client.get("/admin/services"))
        for slug in (SLUG, OTHER_SLUG, THIRD_SLUG):
            self.assertIn(slug, html)
        for name in ("Plumbing", "Electrical Repairs", "Home Cleaning"):
            self.assertIn(name, html)
        self.assertIn("Hidden", html)
        self.assertIn("Visible", html)

    # ---- hide / show
    def test_hiding_a_service_removes_it_from_the_site_but_keeps_bookings(self):
        reference = self.make_booking("cust@example.com", slug=SLUG)
        response = self.admin_post(f"/admin/services/{SLUG}/hide", token_url="/admin/services")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.service(SLUG)["available"])
        self.assertIn("Note: it still has 1 active booking(s)", self.follow(response))
        self.assertEqual(self.snap(reference).status, "pending")
        public = self.app.test_client()
        self.assertEqual(public.get(f"/services/{SLUG}").status_code, 404)
        self.assertNotIn(f"/services/{SLUG}", self.text(public.get("/services")))
        self.assertEqual(public.get(f"/services/{SLUG}/book").status_code, 302)  # visitors are sent to login first; customers get a 404
        customer = self.client_for("cust@example.com")
        self.assertEqual(customer.get(f"/services/{SLUG}/book").status_code, 404)
        self.assertEqual(customer.get(f"/bookings/{reference}").status_code, 200)  # their existing booking is still theirs to see

    def test_showing_a_hidden_service_restores_it(self):
        self.admin_post(f"/admin/services/{SLUG}/hide", token_url="/admin/services")
        self.admin_post(f"/admin/services/{SLUG}/show", token_url="/admin/services")
        self.assertTrue(self.service(SLUG)["available"])
        self.assertEqual(self.app.test_client().get(f"/services/{SLUG}").status_code, 200)

    def test_unknown_services_and_actions_are_a_404(self):
        before = self.db_state()
        for url in ("/admin/services/nope/hide", f"/admin/services/{SLUG}/explode", "/admin/services/nope/edit", "/admin/services/nope/delete", "/admin/services/..%2Fx/hide"):
            self.assertEqual(self.admin_post(url, token_url="/admin/services").status_code, 404, url)
        for url in ("/admin/services/nope/edit", "/admin/services/nope/delete", "/admin/categories/nope/edit", "/admin/categories/nope/delete"):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertEqual(self.db_state(), before)

    # ---- create service
    def test_creating_a_service(self):
        response = self.admin_post("/admin/services/new", self.service_form(), token_url="/admin/services/new")
        self.assertEqual(response.status_code, 302)
        created = self.service("brand-new-service")
        self.assertEqual((created["name"], created["price"], created["category"], created["available"], created["sample"]), ("Brand New Service", 250, "plumbing", True, False))
        self.assertEqual(created["includes"], ["First thing", "Second thing", "Third thing"])
        public = self.text(self.app.test_client().get("/services/brand-new-service"))
        self.assertIn("Brand New Service", public)
        self.assertNotIn("badge-sample", public)  # not marked as sample data
        self.assertIn("Brand New Service", self.text(self.app.test_client().get("/services?category=plumbing")))

    def test_invalid_service_input_is_refused_and_nothing_is_saved(self):
        cases = {
            "duplicate address": {"slug": SLUG}, "bad address": {"slug": "Bad Slug"}, "address with slash": {"slug": "a/b"}, "upper-case address": {"slug": "UPPER"},
            "empty name": {"name": ""}, "short name": {"name": "ab"}, "negative price": {"price_from": "-1"}, "price too high": {"price_from": "1000001"},
            "text price": {"price_from": "cheap"}, "empty price": {"price_from": ""}, "no category": {"category_id": "999999"}, "text category": {"category_id": "abc"},
            "missing description": {"description": ""}, "missing summary": {"summary": ""}, "missing duration": {"duration": ""}, "missing provider": {"provider_name": ""},
            "too many includes": {"includes": "\n".join(f"item {n}" for n in range(11))}, "huge name": {"name": "x" * 151},
        }
        before = self.db_state()
        for label, overrides in cases.items():
            with self.subTest(label):
                response = self.admin_post("/admin/services/new", self.service_form(**overrides), token_url="/admin/services/new")
                self.assertEqual(response.status_code, 200, label)
        self.assertEqual(self.db_state(), before)

    def test_hostile_text_is_escaped_on_the_public_page(self):
        form = self.service_form(name="Tap <script>alert(1)</script> Fix", description="Fix <b>everything</b> now.")
        self.admin_post("/admin/services/new", form, token_url="/admin/services/new")
        html = self.text(self.app.test_client().get("/services/brand-new-service"))
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    # ---- edit service
    def test_editing_a_service_keeps_its_address_and_old_booking_prices(self):
        reference = self.make_booking("cust@example.com", slug=SLUG)
        original_price = self.snap(reference).price
        form = self.service_form(name="Renamed Leak Service", price_from="555", slug="new-address-ignored", category_id=str(self.category_id("electrical")))
        response = self.admin_post(f"/admin/services/{SLUG}/edit", form, token_url=f"/admin/services/{SLUG}/edit")
        self.assertEqual(response.status_code, 302)
        edited = self.service(SLUG)
        self.assertEqual((edited["name"], edited["price"], edited["category"], edited["slug"]), ("Renamed Leak Service", 555, "electrical", SLUG))
        self.assertIsNone(self.service("new-address-ignored"))
        self.assertEqual(self.snap(reference).price, original_price)  # the customer's booking keeps the price it was made at

    def test_the_edit_page_is_prefilled_and_has_no_address_field(self):
        html = self.text(self.client.get(f"/admin/services/{SLUG}/edit"))
        self.assertIn("Leak Detection", html)
        self.assertIn("Inspection of the affected area", html)  # the includes list
        self.assertNotIn('name="slug"', html)

    def test_an_invalid_edit_changes_nothing(self):
        before = self.db_state()
        for overrides in ({"price_from": "-5"}, {"name": ""}, {"category_id": "9999"}):
            response = self.admin_post(f"/admin/services/{SLUG}/edit", self.service_form(**overrides), token_url=f"/admin/services/{SLUG}/edit")
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.db_state(), before)

    # ---- delete service
    def test_a_service_with_bookings_cannot_be_deleted(self):
        self.make_booking("cust@example.com", slug=SLUG)
        page = self.text(self.client.get(f"/admin/services/{SLUG}/delete"))
        self.assertIn("1 booking(s), so it cannot be deleted", page)
        self.assertNotIn("Yes, delete this service", page)
        before = self.db_state()
        response = self.admin_post(f"/admin/services/{SLUG}/delete", token_url="/admin/services")
        self.assertEqual(response.status_code, 302)
        self.assertIn("cannot be deleted", self.follow(response))
        self.assertEqual(self.db_state(), before)

    def test_deleting_an_unused_service_also_removes_its_provider_links_only(self):
        provider_id = self.make_provider("prov@example.com", services=(SLUG, OTHER_SLUG))
        with self.app.app_context():
            links_before = db.session.scalar(select(func.count()).select_from(provider_services))
        self.assertIn("Yes, delete this service", self.text(self.client.get(f"/admin/services/{OTHER_SLUG}/delete")))
        self.admin_post(f"/admin/services/{OTHER_SLUG}/delete", token_url="/admin/services")
        self.assertIsNone(self.service(OTHER_SLUG))
        with self.app.app_context():
            self.assertEqual(db.session.scalar(select(func.count()).select_from(provider_services)), links_before - 1)
            self.assertEqual([s.slug for s in providers.offered_services(db.session.get(User, provider_id))], [SLUG])  # the other link survives
            self.assertIsNotNone(db.session.get(User, provider_id))

    def test_a_newly_created_service_can_be_deleted_before_it_is_used(self):
        self.admin_post("/admin/services/new", self.service_form(), token_url="/admin/services/new")
        self.admin_post("/admin/services/brand-new-service/delete", token_url="/admin/services")
        self.assertIsNone(self.service("brand-new-service"))

    # ---- categories
    def test_creating_and_editing_a_category(self):
        self.assertEqual(self.admin_post("/admin/categories/new", CATEGORY_FORM, token_url="/admin/categories/new").status_code, 302)
        with self.app.app_context():
            category = catalog.get_category("gardening")
            self.assertEqual((category.name, category.icon, category.sort_order), ("Gardening", "sparkles", 7))
        self.assertIn("Gardening", self.text(self.app.test_client().get("/")))
        self.admin_post("/admin/categories/gardening/edit", dict(CATEGORY_FORM, name="Garden Care", slug="ignored", sort_order="3"), token_url="/admin/categories/gardening/edit")
        with self.app.app_context():
            category = catalog.get_category("gardening")
            self.assertEqual((category.name, category.sort_order), ("Garden Care", 3))
            self.assertIsNone(catalog.get_category("ignored"))

    def test_invalid_category_input_is_refused(self):
        before = self.db_state()
        for label, overrides in {"duplicate": {"slug": "plumbing"}, "bad address": {"slug": "Bad Address"}, "empty name": {"name": ""}, "bad icon": {"icon": "rocket"},
                                 "order too high": {"sort_order": "1000"}, "negative order": {"sort_order": "-1"}, "text order": {"sort_order": "x"}, "no blurb": {"blurb": ""}}.items():
            with self.subTest(label):
                response = self.admin_post("/admin/categories/new", dict(CATEGORY_FORM, **overrides), token_url="/admin/categories/new")
                self.assertEqual(response.status_code, 200, label)
        self.assertEqual(self.db_state(), before)

    def test_a_category_with_services_cannot_be_deleted_but_an_empty_one_can(self):
        before = self.db_state()
        page = self.text(self.client.get("/admin/categories/plumbing/delete"))
        self.assertIn("still has 2 service(s)", page)
        self.admin_post("/admin/categories/plumbing/delete", token_url="/admin/services")
        self.assertEqual(self.db_state(), before)
        self.admin_post("/admin/categories/new", CATEGORY_FORM, token_url="/admin/categories/new")
        self.admin_post("/admin/categories/gardening/delete", token_url="/admin/services")
        with self.app.app_context():
            self.assertIsNone(catalog.get_category("gardening"))
            self.assertEqual(len(catalog.list_categories()), 6)

    def test_hidden_services_still_block_deleting_their_category(self):
        for slug in ("leak-detection-pipe-repair", "bathroom-fixture-installation"):
            self.admin_post(f"/admin/services/{slug}/hide", token_url="/admin/services")
        before = self.db_state()
        self.admin_post("/admin/categories/plumbing/delete", token_url="/admin/services")
        self.assertEqual(self.db_state(), before)

    def test_changes_without_a_csrf_token_are_refused(self):
        before = self.db_state()
        for url, data in [(f"/admin/services/{SLUG}/hide", {}), (f"/admin/services/{OTHER_SLUG}/delete", {}), ("/admin/services/new", self.service_form()),
                          ("/admin/categories/new", CATEGORY_FORM), ("/admin/categories/plumbing/delete", {})]:
            self.assertEqual(self.client.post(url, data=data).status_code, 400, url)
        self.assertEqual(self.db_state(), before)

    def test_existing_customer_and_provider_workflows_still_work_after_admin_changes(self):
        provider_id = self.make_provider("prov@example.com", services=(SLUG,))
        self.admin_post(f"/admin/services/{OTHER_SLUG}/hide", token_url="/admin/services")
        reference = self.make_booking("cust@example.com", slug=SLUG)
        self.assertEqual(self.snap(reference).provider_id, provider_id)
        provider = self.client_for("prov@example.com")
        token = TOKEN_RE.search(provider.get("/provider/dashboard").get_data(as_text=True)).group(1)
        self.assertEqual(provider.post(f"/provider/bookings/{reference}/accept", data={"csrf_token": token}).status_code, 302)
        self.assertEqual(self.snap(reference).status, "accepted")


# ===================================================== 5. booking visibility
class AdminBookingVisibilityTests(AdminTestCase):
    def setUp(self):
        super().setUp()
        self.make_user("cust@example.com", full_name="Carol Customer")
        self.make_user("dave@example.com", full_name="Dave <b>Dee</b>")
        self.provider_id = self.make_provider("prov@example.com", services=(SLUG,), full_name="Pat Provider")
        self.assigned = self.make_booking("cust@example.com", slug=SLUG, slot="08:00")
        self.unassigned = self.make_booking("dave@example.com", slug=THIRD_SLUG, slot="10:00")
        self.accepted = self.make_booking("cust@example.com", slug=OTHER_SLUG, slot="12:00")
        self.set_status(self.accepted, "accepted")
        self.as_admin()

    def test_the_admin_sees_every_booking_with_who_what_and_status(self):
        html = self.text(self.client.get("/admin/bookings"))
        for reference in (self.assigned, self.unassigned, self.accepted):
            self.assertIn(reference, html)
        for expected in ("Carol Customer", "cust@example.com", "dave@example.com", "Pat Provider", "Unassigned", "Pending", "Accepted",
                         "Leak Detection &amp; Pipe Repair", "Split AC Installation"):
            self.assertIn(expected, html)

    def test_names_are_escaped_and_private_details_are_not_listed(self):
        html = self.text(self.client.get("/admin/bookings"))
        self.assertIn("Dave &lt;b&gt;Dee&lt;/b&gt;", html)
        self.assertNotIn("<b>Dee</b>", html)
        for private in ("12 Main Road", "9876543210", "The tap leaks badly."):
            self.assertNotIn(private, html)

    def test_filter_by_status_service_and_provider(self):
        by_status = self.text(self.client.get("/admin/bookings?status=accepted"))
        self.assertEqual([r for r in (self.assigned, self.unassigned, self.accepted) if r in by_status], [self.accepted])
        by_service = self.text(self.client.get(f"/admin/bookings?service={THIRD_SLUG}"))
        self.assertEqual([r for r in (self.assigned, self.unassigned, self.accepted) if r in by_service], [self.unassigned])
        by_provider = self.text(self.client.get(f"/admin/bookings?provider={self.provider_id}"))
        self.assertEqual([r for r in (self.assigned, self.unassigned, self.accepted) if r in by_provider], [self.assigned])
        no_provider = self.text(self.client.get("/admin/bookings?provider=unassigned"))
        self.assertEqual({r for r in (self.assigned, self.unassigned, self.accepted) if r in no_provider}, {self.unassigned, self.accepted})

    def test_search_by_reference_and_by_customer(self):
        by_reference = self.text(self.client.get(f"/admin/bookings?q={self.assigned[:7].lower()}"))
        self.assertIn(self.assigned, by_reference)
        by_email = self.text(self.client.get("/admin/bookings?q=DAVE%40example"))
        self.assertEqual([r for r in (self.assigned, self.unassigned) if r in by_email], [self.unassigned])
        by_name = self.text(self.client.get("/admin/bookings?q=carol"))
        self.assertEqual({r for r in (self.assigned, self.unassigned, self.accepted) if r in by_name}, {self.assigned, self.accepted})
        self.assertIn("No bookings match", self.text(self.client.get("/admin/bookings?q=nobody-at-all")))

    def test_filters_combine(self):
        html = self.text(self.client.get("/admin/bookings?status=pending&provider=unassigned"))
        self.assertEqual([r for r in (self.assigned, self.unassigned, self.accepted) if r in html], [self.unassigned])

    def test_malformed_filters_are_ignored_not_errors(self):
        for query in ("status=nonsense", "service=../etc/passwd", "service=NOPE", "provider=abc", "provider=99999999999999999999", "provider=-1", "q=%25", "q=_", f"q={'z' * 5000}", "page=abc"):
            response = self.client.get("/admin/bookings?" + query)
            self.assertEqual(response.status_code, 200, query)
            self.assertNotIn("Traceback", self.text(response))
        everything = self.text(self.client.get("/admin/bookings?status=nonsense&provider=abc&service=NOPE"))
        self.assertIn("No bookings match", everything)  # an unknown service filter matches nothing
        ignored = self.text(self.client.get("/admin/bookings?status=nonsense&provider=abc"))
        for reference in (self.assigned, self.unassigned, self.accepted):
            self.assertIn(reference, ignored)

    def test_pagination(self):
        self.bulk_bookings(25)
        first = self.text(self.client.get("/admin/bookings"))
        self.assertIn("Page 1 of 2", first)
        self.assertIn("Showing 1 to 20 of 28", first)
        self.assertEqual(first.count("FN-"), 20)
        second = self.text(self.client.get("/admin/bookings?page=2"))
        self.assertEqual(second.count("FN-"), 8)
        self.assertIn("Page 2 of 2", self.text(self.client.get("/admin/bookings?page=500")))
        filtered = self.text(self.client.get("/admin/bookings?status=pending"))
        self.assertIn("status=pending", filtered.split('class="pagination"')[1])  # page links keep the filter

    def test_the_newest_booking_comes_first(self):
        html = self.text(self.client.get("/admin/bookings"))
        self.assertLess(html.index(self.accepted), html.index(self.unassigned))
        self.assertLess(html.index(self.unassigned), html.index(self.assigned))

    def test_the_view_is_read_only(self):
        before = self.db_state()
        for method in ("post", "put", "delete", "patch"):
            response = getattr(self.client, method)("/admin/bookings", data={"csrf_token": self.token("/admin/dashboard"), "status": "completed"})
            self.assertIn(response.status_code, (400, 405), method)
        self.assertEqual(self.db_state(), before)

    def test_an_empty_booking_list_shows_an_honest_empty_state(self):
        with self.app.app_context():
            for booking in db.session.scalars(select(Booking)):
                db.session.delete(booking)
            db.session.commit()
        self.assertIn("No bookings match", self.text(self.client.get("/admin/bookings")))


if __name__ == "__main__":
    import unittest

    unittest.main()
