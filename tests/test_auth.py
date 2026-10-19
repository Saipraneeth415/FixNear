"""Stage 4 tests: registration, login, logout, CSRF, roles and the admin command.

Every test uses its own temporary SQLite database (see tests/helpers.py).
CSRF protection stays ON in these tests, exactly like the real site: each
form post first reads the token from the page, like a browser does.
"""
import re
from types import SimpleNamespace
from urllib.parse import urlsplit

from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from config import ProductionConfig
from extensions import db
from models import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_PROVIDER, User
from services import accounts
from tests.helpers import DatabaseTestCase

PASSWORD = "Correct-Horse-9"
TOKEN_RE = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"')


class AuthTestCase(DatabaseTestCase):
    """Helpers shared by the tests below."""

    def token(self, url="/register"):
        html = self.client.get(url).get_data(as_text=True)
        match = TOKEN_RE.search(html)
        self.assertIsNotNone(match, f"no CSRF token found on {url}")
        return match.group(1)

    def post(self, url, data, token_url=None):
        data = dict(data)
        data["csrf_token"] = self.token(token_url or url)
        return self.client.post(url, data=data)

    def make_user(self, email="user@example.com", password=PASSWORD, role=ROLE_CUSTOMER, full_name="Test User", active=True):
        with self.app.app_context():
            user = accounts.create_user(email, full_name, password, role=role)
            if not active:
                user.is_active = False
                db.session.commit()
            return user.id

    def snapshot(self, email):
        """Read a user's fields into a plain object (safe to use after the session closes)."""
        with self.app.app_context():
            user = accounts.get_user_by_email(email)
            if user is None:
                return None
            return SimpleNamespace(
                id=user.id, email=user.email, role=user.role, full_name=user.full_name,
                password_hash=user.password_hash, is_active=user.is_active, last_login_at=user.last_login_at,
            )

    def user_count(self):
        with self.app.app_context():
            return db.session.scalar(select(func.count(User.id)))

    def register(self, **overrides):
        data = {"full_name": "Jane Doe", "email": "jane@example.com", "password": PASSWORD, "confirm_password": PASSWORD}
        data.update(overrides)
        return self.post("/register", data)

    def login(self, email="user@example.com", password=PASSWORD, next_url=None):
        data = {"email": email, "password": password}
        if next_url is not None:
            data["next_url"] = next_url
        return self.post("/login", data)

    def location(self, response):
        parts = urlsplit(response.headers["Location"])
        self.assertEqual(parts.netloc, "", "redirect must stay on this site")
        return parts.path + (f"?{parts.query}" if parts.query else "")

    def text(self, response):
        return response.get_data(as_text=True)


class RegistrationTests(AuthTestCase):
    def test_register_page_loads_with_a_csrf_token(self):
        response = self.client.get("/register")
        html = self.text(response)
        self.assertEqual(response.status_code, 200)
        for name in ("full_name", "email", "password", "confirm_password", "csrf_token"):
            self.assertIn(f'name="{name}"', html)
        self.assertNotIn('name="role"', html)

    def test_successful_registration_creates_a_customer_and_logs_in(self):
        response = self.register()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.location(response), "/customer/dashboard")
        user = self.snapshot("jane@example.com")
        self.assertEqual(user.role, ROLE_CUSTOMER)
        self.assertEqual(user.full_name, "Jane Doe")
        self.assertTrue(user.is_active)
        self.assertEqual(self.client.get("/customer/dashboard").status_code, 200)

    def test_email_is_trimmed_and_stored_lowercase(self):
        self.register(email="  New.Person@Example.COM ")
        self.assertIsNotNone(self.snapshot("new.person@example.com"))
        self.assertEqual(self.user_count(), 1)

    def test_name_whitespace_is_tidied(self):
        self.register(full_name="  Jane    Q   Doe ")
        self.assertEqual(self.snapshot("jane@example.com").full_name, "Jane Q Doe")

    def test_password_is_stored_as_a_hash_never_plaintext(self):
        self.register()
        stored = self.snapshot("jane@example.com").password_hash
        self.assertNotEqual(stored, PASSWORD)
        self.assertNotIn(PASSWORD, stored)
        self.assertTrue(stored.startswith(("scrypt:", "pbkdf2:")))
        with self.app.app_context():
            user = accounts.get_user_by_email("jane@example.com")
            self.assertTrue(user.check_password(PASSWORD))
            self.assertFalse(user.check_password("wrong-password-1"))

    def test_the_users_table_has_no_plaintext_password_column(self):
        with self.app.app_context():
            columns = {c["name"] for c in inspect(db.engine).get_columns("users")}
        self.assertIn("password_hash", columns)
        self.assertNotIn("password", columns)

    def test_same_password_for_two_users_gives_different_hashes(self):
        self.register(email="a@example.com")
        self.client.post("/logout", data={"csrf_token": self.token("/customer/dashboard")})
        self.register(email="b@example.com")
        self.assertNotEqual(self.snapshot("a@example.com").password_hash, self.snapshot("b@example.com").password_hash)

    def test_duplicate_email_is_rejected(self):
        self.make_user("taken@example.com")
        response = self.register(email="taken@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertIn("already exists", self.text(response))
        self.assertEqual(self.user_count(), 1)

    def test_duplicate_email_is_rejected_in_any_letter_case(self):
        self.make_user("taken@example.com")
        response = self.register(email="TAKEN@Example.com")
        self.assertIn("already exists", self.text(response))
        self.assertEqual(self.user_count(), 1)

    def test_invalid_input_is_rejected_and_nothing_is_saved(self):
        cases = {
            "missing name": ({"full_name": ""}, "Enter your name"),
            "one-letter name": ({"full_name": "J"}, "2 to 100"),
            "missing email": ({"email": ""}, "Enter your email"),
            "malformed email": ({"email": "not-an-email"}, "valid email"),
            "short password": ({"password": "Ab1", "confirm_password": "Ab1"}, "at least 10"),
            "no number": ({"password": "onlyletterspassword", "confirm_password": "onlyletterspassword"}, "letter and one number"),
            "common password": ({"password": "Password123", "confirm_password": "Password123"}, "too common"),
            "too long": ({"password": "a1" * 70, "confirm_password": "a1" * 70}, "no more than"),
            "mismatch": ({"confirm_password": "Different-Pass-1"}, "do not match"),
            "email as password": ({"email": "me.myself9@example.com", "password": "me.myself9@example.com", "confirm_password": "me.myself9@example.com"}, "email address as your password"),
        }
        for label, (overrides, expected) in cases.items():
            with self.subTest(label):
                response = self.register(**overrides)
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected, self.text(response))
        self.assertEqual(self.user_count(), 0)

    def test_the_password_is_never_sent_back_in_the_page(self):
        html = self.text(self.register(confirm_password="Different-Pass-1"))
        self.assertNotIn(PASSWORD, html)

    def test_public_registration_can_only_create_customers(self):
        response = self.register(role="admin", is_admin="1", is_active="0", user_role="provider")
        self.assertEqual(response.status_code, 302)
        user = self.snapshot("jane@example.com")
        self.assertEqual(user.role, ROLE_CUSTOMER)
        self.assertTrue(user.is_active)
        self.assertEqual(self.client.get("/admin/dashboard").status_code, 403)

    def test_logged_in_users_are_redirected_away_from_register(self):
        self.register()
        self.assertEqual(self.location(self.client.get("/register")), "/customer/dashboard")


class LoginTests(AuthTestCase):
    def test_login_page_loads(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="csrf_token"', self.text(response))

    def test_valid_login_goes_to_the_customer_dashboard(self):
        self.make_user()
        response = self.login()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.location(response), "/customer/dashboard")
        self.assertEqual(self.client.get("/customer/dashboard").status_code, 200)

    def test_login_is_case_insensitive_for_email(self):
        self.make_user("user@example.com")
        self.assertEqual(self.login(email="  USER@Example.com ").status_code, 302)

    def test_wrong_password_is_rejected(self):
        self.make_user()
        response = self.login(password="Wrong-Password-1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Invalid email or password.", self.text(response))
        self.assertEqual(self.client.get("/customer/dashboard").status_code, 302)  # still logged out

    def test_unknown_email_gives_the_same_message_as_a_wrong_password(self):
        self.make_user()
        wrong_password = self.text(self.login(password="Wrong-Password-1"))
        unknown_email = self.text(self.login(email="nobody@example.com"))
        self.assertIn("Invalid email or password.", unknown_email)
        self.assertNotIn("not found", unknown_email.lower())
        self.assertNotIn("no account", unknown_email.lower())
        self.assertEqual(wrong_password.count("Invalid email or password."), unknown_email.count("Invalid email or password."))

    def test_empty_login_is_rejected(self):
        response = self.login(email="", password="")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Enter your email", self.text(response))

    def test_a_suspended_account_cannot_log_in(self):
        self.make_user(active=False)
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Invalid email or password.", self.text(response))
        self.assertEqual(self.client.get("/customer/dashboard").status_code, 302)

    def test_login_records_the_last_login_time(self):
        self.make_user()
        self.assertIsNone(self.snapshot("user@example.com").last_login_at)
        self.login()
        self.assertIsNotNone(self.snapshot("user@example.com").last_login_at)

    def test_each_role_lands_on_its_own_dashboard(self):
        for role, path in [(ROLE_CUSTOMER, "/customer/dashboard"), (ROLE_PROVIDER, "/provider/dashboard"), (ROLE_ADMIN, "/admin/dashboard")]:
            with self.subTest(role):
                client_user = f"{role}@example.com"
                self.make_user(client_user, role=role)
                self.assertEqual(self.location(self.login(email=client_user)), path)
                self.client.post("/logout", data={"csrf_token": self.token(path)})

    def test_logged_in_users_are_redirected_away_from_login(self):
        self.make_user()
        self.login()
        self.assertEqual(self.location(self.client.get("/login")), "/customer/dashboard")

    def test_session_cookie_is_http_only_and_same_site(self):
        self.make_user()
        cookie = self.login().headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertTrue(ProductionConfig.SESSION_COOKIE_SECURE)


class SafeRedirectTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.make_user()

    def test_protected_page_sends_you_to_login_and_back_afterwards(self):
        response = self.client.get("/customer/dashboard")
        self.assertEqual(response.status_code, 302)
        login_url = self.location(response)
        self.assertTrue(login_url.startswith("/login?next="))
        page = self.text(self.client.get(login_url))
        self.assertIn('name="next_url"', page)
        self.assertIn("Please log in to continue.", page)  # the message flashed by the redirect
        self.assertEqual(self.location(self.login(next_url="/customer/dashboard")), "/customer/dashboard")

    def test_a_local_next_page_is_followed(self):
        self.assertEqual(self.location(self.login(next_url="/services?q=tap")), "/services?q=tap")

    def test_external_next_targets_are_ignored(self):
        for target in ["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", "evil.example"]:
            with self.subTest(target):
                response = self.login(next_url=target)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(self.location(response), "/customer/dashboard")
                self.client.post("/logout", data={"csrf_token": self.token("/customer/dashboard")})

    def test_unsafe_next_values_are_not_written_back_into_the_login_form(self):
        html = self.text(self.client.get("/login?next=https://evil.example"))
        self.assertNotIn("evil.example", html)


class LogoutTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.make_user()
        self.login()

    def test_logout_requires_post(self):
        self.assertEqual(self.client.get("/logout").status_code, 405)
        self.assertEqual(self.client.get("/customer/dashboard").status_code, 200)  # still logged in

    def test_logout_ends_the_session(self):
        response = self.client.post("/logout", data={"csrf_token": self.token("/customer/dashboard")})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.location(response), "/")
        self.assertEqual(self.client.get("/customer/dashboard").status_code, 302)

    def test_logout_without_a_csrf_token_is_refused(self):
        self.assertEqual(self.client.post("/logout").status_code, 400)
        self.assertEqual(self.client.get("/customer/dashboard").status_code, 200)  # still logged in

    def test_logout_when_not_logged_in_goes_to_login(self):
        self.client.post("/logout", data={"csrf_token": self.token("/customer/dashboard")})
        response = self.client.post("/logout", data={"csrf_token": self.token("/login")})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", self.location(response))


class CsrfTests(AuthTestCase):
    def test_registration_without_a_token_is_refused(self):
        response = self.client.post("/register", data={"full_name": "Jane Doe", "email": "jane@example.com", "password": PASSWORD, "confirm_password": PASSWORD})
        self.assertEqual(response.status_code, 400)
        self.assertIn("could not be verified", self.text(response))
        self.assertEqual(self.user_count(), 0)

    def test_registration_with_a_wrong_token_is_refused(self):
        self.client.get("/register")
        response = self.client.post("/register", data={"full_name": "Jane Doe", "email": "jane@example.com", "password": PASSWORD, "confirm_password": PASSWORD, "csrf_token": "forged-token"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.user_count(), 0)

    def test_login_without_a_token_is_refused(self):
        self.make_user()
        response = self.client.post("/login", data={"email": "user@example.com", "password": PASSWORD})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/customer/dashboard").status_code, 302)

    def test_a_token_from_another_visitor_does_not_work(self):
        stolen = self.token("/register")  # token belongs to this visitor's session
        other = self.app.test_client()  # a different browser with its own session
        other.get("/register")
        response = other.post("/register", data={"full_name": "Jane Doe", "email": "jane@example.com", "password": PASSWORD, "confirm_password": PASSWORD, "csrf_token": stolen})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.user_count(), 0)

    def test_every_form_page_contains_a_token(self):
        self.make_user()
        for url in ("/login", "/register"):
            self.assertIn('name="csrf_token"', self.text(self.client.get(url)), url)
        self.login()
        self.assertIn('name="csrf_token"', self.text(self.client.get("/customer/dashboard")))  # the logout form


class RoleAuthorizationTests(AuthTestCase):
    DASHBOARDS = {ROLE_CUSTOMER: "/customer/dashboard", ROLE_PROVIDER: "/provider/dashboard", ROLE_ADMIN: "/admin/dashboard"}

    def test_anonymous_visitors_are_sent_to_login(self):
        for url in ["/dashboard", *self.DASHBOARDS.values()]:
            with self.subTest(url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(self.location(response).startswith("/login"), url)

    def test_each_role_can_open_only_its_own_dashboard(self):
        for role, own_url in self.DASHBOARDS.items():
            with self.subTest(role):
                email = f"{role}@example.com"
                self.make_user(email, role=role)
                self.login(email=email)
                for other_role, url in self.DASHBOARDS.items():
                    expected = 200 if other_role == role else 403
                    self.assertEqual(self.client.get(url).status_code, expected, f"{role} opening {url}")
                self.client.post("/logout", data={"csrf_token": self.token(own_url)})

    def test_dashboard_redirects_to_the_role_home(self):
        for role, own_url in self.DASHBOARDS.items():
            with self.subTest(role):
                email = f"{role}@example.com"
                self.make_user(email, role=role)
                self.login(email=email)
                self.assertEqual(self.location(self.client.get("/dashboard")), own_url)
                self.client.post("/logout", data={"csrf_token": self.token(own_url)})

    def test_forbidden_users_see_the_custom_403_page(self):
        self.make_user()
        self.login()
        response = self.client.get("/admin/dashboard")
        self.assertEqual(response.status_code, 403)
        self.assertIn("Access denied", self.text(response))
        self.assertNotIn("Traceback", self.text(response))

    def test_a_suspended_user_is_logged_out_on_the_next_request(self):
        user_id = self.make_user()
        self.login()
        self.assertEqual(self.client.get("/customer/dashboard").status_code, 200)
        with self.app.app_context():
            db.session.get(User, user_id).is_active = False
            db.session.commit()
        self.assertEqual(self.client.get("/customer/dashboard").status_code, 302)

    def test_a_deleted_user_is_logged_out_on_the_next_request(self):
        user_id = self.make_user()
        self.login()
        with self.app.app_context():
            db.session.delete(db.session.get(User, user_id))
            db.session.commit()
        self.assertEqual(self.client.get("/customer/dashboard").status_code, 302)

    def test_changing_a_role_in_the_database_takes_effect_immediately(self):
        user_id = self.make_user()
        self.login()
        with self.app.app_context():
            db.session.get(User, user_id).role = ROLE_PROVIDER
            db.session.commit()
        self.assertEqual(self.client.get("/customer/dashboard").status_code, 403)
        self.assertEqual(self.client.get("/provider/dashboard").status_code, 200)

    def test_dashboards_are_not_cached_by_the_browser(self):
        self.make_user()
        self.login()
        self.assertEqual(self.client.get("/customer/dashboard").headers["Cache-Control"], "no-store")

    def test_a_new_customers_dashboard_shows_an_honest_empty_state(self):
        # Stage 5: the dashboard shows real bookings, so a new customer sees none.
        self.make_user()
        self.login()
        html = self.text(self.client.get("/customer/dashboard"))
        self.assertIn("You have not booked any services yet", html)
        self.assertNotIn("FN-", html)


class PublicPagesStillWorkTests(AuthTestCase):
    def test_public_pages_work_for_visitors_and_logged_in_users(self):
        self.make_user()
        for logged_in in (False, True):
            if logged_in:
                self.login()
            for url in ["/", "/services", "/services?q=leak", "/services?category=plumbing", "/services/leak-detection-pipe-repair", "/about", "/contact"]:
                self.assertEqual(self.client.get(url).status_code, 200, f"{url} (logged_in={logged_in})")

    def test_nav_changes_with_login_state(self):
        anonymous = self.text(self.client.get("/"))
        self.assertIn("Log in", anonymous)
        self.assertIn("Create account", anonymous)
        self.assertNotIn("Log out", anonymous)
        self.make_user()
        self.login()
        logged_in = self.text(self.client.get("/"))
        self.assertIn("Log out", logged_in)
        self.assertIn("Dashboard", logged_in)
        self.assertNotIn("Create account", logged_in)

    def test_search_results_are_the_same_when_logged_in(self):
        before = self.text(self.client.get("/services?q=leak"))
        self.make_user()
        self.login()
        after = self.text(self.client.get("/services?q=leak"))
        self.assertIn("Leak Detection &amp; Pipe Repair", after)
        self.assertEqual(before.count("service-card"), after.count("service-card"))

    def test_a_logged_in_user_sees_a_safe_error_page_when_the_database_is_down(self):
        self.make_user()
        self.login()
        with self.app.app_context():
            db.drop_all()
        self.assertEqual(self.client.get("/about").status_code, 200)  # treated as logged out, no crash


class UserModelTests(AuthTestCase):
    def add_raw(self, **values):
        data = dict(email="raw@example.com", full_name="Raw User", password_hash="x", role=ROLE_CUSTOMER)
        data.update(values)
        with self.app.app_context():
            db.session.add(User(**data))
            try:
                db.session.commit()
            finally:
                db.session.rollback()

    def test_duplicate_email_is_blocked_by_the_database(self):
        self.make_user("dup@example.com")
        with self.assertRaises(IntegrityError):
            self.add_raw(email="dup@example.com")

    def test_unknown_role_is_blocked_by_the_database(self):
        with self.assertRaises(IntegrityError):
            self.add_raw(role="superuser")

    def test_mixed_case_email_is_blocked_by_the_database(self):
        with self.assertRaises(IntegrityError):
            self.add_raw(email="Mixed@Example.com")

    def test_create_user_rejects_an_unknown_role(self):
        with self.app.app_context():
            with self.assertRaises(ValueError):
                accounts.create_user("x@example.com", "X Person", PASSWORD, role="superuser")

    def test_create_user_rejects_weak_passwords_and_bad_emails(self):
        with self.app.app_context():
            with self.assertRaises(accounts.WeakPasswordError):
                accounts.create_user("x@example.com", "X Person", "short1")
            with self.assertRaises(accounts.InvalidEmailError):
                accounts.create_user("not-an-email", "X Person", PASSWORD)
            self.assertEqual(db.session.scalar(select(func.count(User.id))), 0)

    def test_create_user_reports_duplicates(self):
        self.make_user("dup@example.com")
        with self.app.app_context():
            with self.assertRaises(accounts.DuplicateEmailError):
                accounts.create_user("DUP@example.com", "Dup Person", PASSWORD)

    def test_timestamps_and_role_helpers(self):
        user_id = self.make_user(role=ROLE_PROVIDER)
        with self.app.app_context():
            user = db.session.get(User, user_id)
            self.assertIsNotNone(user.created_at)
            self.assertIsNotNone(user.updated_at)
            self.assertTrue(user.is_provider)
            self.assertFalse(user.is_admin or user.is_customer)
            self.assertNotIn(user.password_hash, repr(user))


class AdminCommandTests(AuthTestCase):
    def run_command(self, *args, input_text=None):
        return self.app.test_cli_runner().invoke(args=list(args), input=input_text)

    def test_create_admin_makes_an_administrator_with_a_hashed_password(self):
        result = self.run_command("create-admin", "--email", "Boss@Example.com", "--name", "Site Boss", input_text=f"{PASSWORD}\n{PASSWORD}\n")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Administrator created: boss@example.com", result.output)
        user = self.snapshot("boss@example.com")
        self.assertEqual(user.role, ROLE_ADMIN)
        self.assertNotIn(PASSWORD, user.password_hash)
        self.assertNotIn(PASSWORD, result.output)
        self.login(email="boss@example.com")
        self.assertEqual(self.client.get("/admin/dashboard").status_code, 200)

    def test_create_admin_refuses_a_weak_password(self):
        result = self.run_command("create-admin", "--email", "boss@example.com", "--name", "Site Boss", input_text="short\nshort\n")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("at least 10", result.output)
        self.assertIsNone(self.snapshot("boss@example.com"))

    def test_create_admin_refuses_mismatched_passwords(self):
        result = self.run_command("create-admin", "--email", "boss@example.com", "--name", "Site Boss", input_text=f"{PASSWORD}\nDifferent-Pass-1\n")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIsNone(self.snapshot("boss@example.com"))

    def test_create_admin_never_changes_an_existing_account(self):
        self.make_user("boss@example.com")
        before = self.snapshot("boss@example.com")
        result = self.run_command("create-admin", "--email", "boss@example.com", "--name", "Site Boss", input_text=f"{PASSWORD}\n{PASSWORD}\n")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("already exists", result.output)
        after = self.snapshot("boss@example.com")
        self.assertEqual((before.role, before.password_hash), (after.role, after.password_hash))

    def test_create_admin_rejects_a_bad_email(self):
        result = self.run_command("create-admin", "--email", "nope", "--name", "Site Boss", input_text=f"{PASSWORD}\n{PASSWORD}\n")
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(self.user_count(), 0)

    def test_list_users_shows_roles_but_never_hashes(self):
        self.make_user("a@example.com")
        self.make_user("b@example.com", role=ROLE_PROVIDER)
        result = self.run_command("list-users")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("a@example.com  customer  active", result.output)
        self.assertIn("b@example.com  provider  active", result.output)
        self.assertNotIn("scrypt", result.output)
        self.assertNotIn("pbkdf2", result.output)

    def test_list_users_on_an_empty_table(self):
        self.assertIn("No users yet.", self.run_command("list-users").output)
