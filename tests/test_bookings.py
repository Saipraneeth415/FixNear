"""Stage 5 tests: the booking model, the browser booking flow, validation,
ownership, cancellation, status transitions and the customer dashboard.

Every test uses its own temporary SQLite database. CSRF protection stays ON:
forms are posted with the token read from the page, like a browser does.
"""
import re
from datetime import date, time, timedelta
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, quote, urlsplit

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_PROVIDER, Booking, Service, User
from services import accounts, bookings, catalog
from services import booking_rules as rules
from tests.test_auth import AuthTestCase

SLUG = "leak-detection-pipe-repair"
OTHER_SLUG = "bathroom-fixture-installation"
BOOK_PATH = f"/services/{SLUG}/book"
SUBMISSION_RE = re.compile(r'name="submission_token"[^>]*value="([0-9a-f]{32})"')
CONFIRMATION_RE = re.compile(r"^/bookings/(FN-[A-Z0-9]{4}-[A-Z0-9]{4})/confirmation$")


class BookingTestCase(AuthTestCase):
    """Helpers for booking tests."""

    def future(self, days=3):
        return (rules.local_now(330).date() + timedelta(days=days)).isoformat()

    def valid(self, **overrides):
        data = {
            "contact_name": "Jane Doe",
            "contact_phone": "+91 98765 43210",
            "address": "12 Main Road, Test Area, near the old temple",
            "appointment_date": self.future(3),
            "appointment_time": "10:00",
            "problem_description": "The kitchen tap leaks all day long.",
        }
        data.update(overrides)
        return data

    def customer(self, email="cust@example.com"):
        """Create a customer and log in as them."""
        self.make_user(email)
        self.login(email=email)
        return email

    def logout(self, token_url="/"):
        self.client.post("/logout", data={"csrf_token": self.token(token_url)})

    def open_form(self, slug=SLUG):
        response = self.client.get(f"/services/{slug}/book")
        self.assertEqual(response.status_code, 200)
        html = self.text(response)
        csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
        token = SUBMISSION_RE.search(html)
        self.assertIsNotNone(csrf)
        self.assertIsNotNone(token)
        return csrf.group(1), token.group(1)

    def post_booking(self, csrf, submission, slug=SLUG, **overrides):
        data = self.valid(**overrides)
        data["csrf_token"] = csrf
        data["submission_token"] = submission
        for key in [k for k, v in data.items() if v is None]:
            del data[key]  # None means "leave this field out of the request"
        return self.client.post(f"/services/{slug}/book", data=data)

    def submit(self, slug=SLUG, **overrides):
        csrf, submission = self.open_form(slug)
        overrides.setdefault("submission_token", submission)
        submission = overrides.pop("submission_token")
        return self.post_booking(csrf, submission, slug=slug, **overrides)

    def reference_from(self, response):
        self.assertEqual(response.status_code, 302, self.text(response)[:300])
        match = CONFIRMATION_RE.match(self.location(response))
        self.assertIsNotNone(match, self.location(response))
        return match.group(1)

    def make_booking(self, email="cust@example.com", slug=SLUG, days=3, slot="10:00", **extra):
        """Create a booking directly through the service layer; returns its reference."""
        with self.app.app_context():
            customer = accounts.get_user_by_email(email)
            booking, _ = bookings.create_booking(
                customer, catalog.get_service(slug),
                contact_name="Test User", contact_phone="9876543210", address="12 Main Road, Test Area",
                appointment_date=bookings.now_local().date() + timedelta(days=days), appointment_time=slot,
                problem_description="The tap leaks badly.", **extra,
            )
            return booking.reference

    def snap(self, reference):
        with self.app.app_context():
            b = db.session.scalar(select(Booking).where(Booking.reference == reference))
            if b is None:
                return None
            return SimpleNamespace(
                id=b.id, reference=b.reference, status=b.status, customer_id=b.customer_id, service_id=b.service_id,
                provider_id=b.provider_id, contact_name=b.contact_name, contact_phone=b.contact_phone, address=b.address,
                appointment_date=b.appointment_date, appointment_time=b.appointment_time, description=b.problem_description,
                price=b.price_from_at_booking, reason=b.cancellation_reason, cancelled_at=b.cancelled_at,
                created_at=b.created_at, token=b.submission_token, service_slug=b.service.slug,
            )

    def count_bookings(self):
        with self.app.app_context():
            return db.session.scalar(select(func.count(Booking.id)))

    def set_status(self, reference, status):
        with self.app.app_context():
            db.session.scalar(select(Booking).where(Booking.reference == reference)).status = status
            db.session.commit()

    def stat(self, html, name):
        match = re.search(rf'id="stat-{name}"><span class="stat-number">(\d+)<', html)
        self.assertIsNotNone(match, f"stat {name} not found")
        return int(match.group(1))


# ===================================================================== model
class BookingModelTests(BookingTestCase):
    def ids(self):
        customer_id = self.make_user()
        with self.app.app_context():
            service_id = db.session.scalar(select(Service.id).where(Service.slug == SLUG))
        return customer_id, service_id

    def raw(self, customer_id, service_id, **overrides):
        values = dict(
            reference=rules.generate_reference(), customer_id=customer_id, service_id=service_id,
            contact_name="Test User", contact_phone="9876543210", address="12 Main Road, Test Area",
            appointment_date=date.today() + timedelta(days=3), appointment_time=time(10, 0),
            problem_description="Something is wrong here.", price_from_at_booking=399,
        )
        values.update(overrides)
        return Booking(**values)

    def save(self, booking):
        db.session.add(booking)
        try:
            db.session.commit()
        finally:
            db.session.rollback()

    def test_a_booking_can_be_created_with_sensible_defaults(self):
        customer_id, service_id = self.ids()
        with self.app.app_context():
            booking = self.raw(customer_id, service_id)
            db.session.add(booking)
            db.session.commit()
            self.assertIsNotNone(booking.id)
            self.assertEqual(booking.status, "pending")
            self.assertEqual(booking.status_label, "Pending")
            self.assertIsNone(booking.provider_id)
            self.assertIsNone(booking.cancellation_reason)
            self.assertIsNotNone(booking.created_at)
            self.assertIsNotNone(booking.updated_at)
            self.assertEqual(booking.service.slug, SLUG)
            self.assertEqual(booking.customer.email, "user@example.com")
            self.assertEqual(booking.appointment_start.hour, 10)

    def test_relationships_work_both_ways(self):
        customer_id, service_id = self.ids()
        with self.app.app_context():
            db.session.add(self.raw(customer_id, service_id))
            db.session.commit()
            self.assertEqual(len(db.session.get(User, customer_id).bookings), 1)
            self.assertEqual(len(db.session.get(Service, service_id).bookings), 1)

    def test_a_provider_can_be_attached_later_but_is_optional(self):
        customer_id, service_id = self.ids()
        provider_id = self.make_user("provider@example.com", role=ROLE_PROVIDER)
        with self.app.app_context():
            booking = self.raw(customer_id, service_id, provider_id=provider_id)
            db.session.add(booking)
            db.session.commit()
            self.assertEqual(booking.provider.email, "provider@example.com")

    def test_references_must_be_unique_in_the_database(self):
        customer_id, service_id = self.ids()
        with self.app.app_context():
            db.session.add(self.raw(customer_id, service_id, reference="FN-AAAA-BBBB"))
            db.session.commit()
            with self.assertRaises(IntegrityError):
                self.save(self.raw(customer_id, service_id, reference="FN-AAAA-BBBB"))

    def test_a_reference_can_never_be_changed(self):
        customer_id, service_id = self.ids()
        with self.app.app_context():
            booking = self.raw(customer_id, service_id, reference="FN-AAAA-BBBB")
            db.session.add(booking)
            db.session.commit()
            with self.assertRaises(ValueError):
                booking.reference = "FN-CCCC-DDDD"
            booking.reference = "FN-AAAA-BBBB"  # setting the same value is harmless
            self.assertEqual(booking.reference, "FN-AAAA-BBBB")

    def test_the_database_refuses_an_unknown_status(self):
        customer_id, service_id = self.ids()
        with self.app.app_context(), self.assertRaises(IntegrityError):
            self.save(self.raw(customer_id, service_id, status="refunded"))

    def test_the_database_refuses_a_negative_price(self):
        customer_id, service_id = self.ids()
        with self.app.app_context(), self.assertRaises(IntegrityError):
            self.save(self.raw(customer_id, service_id, price_from_at_booking=-1))

    def test_customer_and_service_must_exist(self):
        customer_id, service_id = self.ids()
        with self.app.app_context():
            with self.assertRaises(IntegrityError):
                self.save(self.raw(99999, service_id))
            with self.assertRaises(IntegrityError):
                self.save(self.raw(customer_id, 99999))

    def test_a_customer_with_bookings_cannot_be_deleted(self):
        customer_id, service_id = self.ids()
        with self.app.app_context():
            db.session.add(self.raw(customer_id, service_id))
            db.session.commit()
            db.session.delete(db.session.get(User, customer_id))
            with self.assertRaises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_one_submission_token_per_customer(self):
        customer_id, service_id = self.ids()
        other_id = self.make_user("other@example.com")
        with self.app.app_context():
            db.session.add(self.raw(customer_id, service_id, submission_token="a" * 32))
            db.session.add(self.raw(other_id, service_id, submission_token="a" * 32))  # a different customer may reuse it
            db.session.commit()
            with self.assertRaises(IntegrityError):
                self.save(self.raw(customer_id, service_id, submission_token="a" * 32))

    def test_many_bookings_without_a_token_are_fine(self):
        customer_id, service_id = self.ids()
        with self.app.app_context():
            db.session.add(self.raw(customer_id, service_id))
            db.session.add(self.raw(customer_id, service_id))
            db.session.commit()


# ============================================================ creating bookings
class BookingFlowTests(BookingTestCase):
    def test_a_customer_sees_a_working_book_button(self):
        self.customer()
        self.assertIn(f'href="{BOOK_PATH}"', self.text(self.client.get(f"/services/{SLUG}")))

    def test_the_form_is_preselected_prefilled_and_has_no_privileged_fields(self):
        self.customer()
        html = self.text(self.client.get(BOOK_PATH))
        self.assertIn("Leak Detection &amp; Pipe Repair", html)
        self.assertIn("Test User", html)  # name prefilled from the account
        for name in ("contact_name", "contact_phone", "address", "appointment_date", "appointment_time", "problem_description", "csrf_token", "submission_token"):
            self.assertIn(f'name="{name}"', html)
        for forbidden in ("status", "provider_id", "price_from_at_booking", "customer_id", "service_id", "role", "reference"):
            self.assertNotIn(f'name="{forbidden}"', html)

    def test_a_visitor_is_sent_to_login_and_then_back_to_the_form(self):
        response = self.client.get(BOOK_PATH)
        self.assertEqual(response.status_code, 302)
        login_url = self.location(response)
        self.assertEqual(parse_qs(urlsplit(login_url).query)["next"], [BOOK_PATH])
        self.make_user()
        self.assertEqual(self.location(self.login(next_url=BOOK_PATH)), BOOK_PATH)
        self.assertEqual(self.client.get(BOOK_PATH).status_code, 200)

    def test_the_service_page_sends_visitors_to_login_with_a_return_address(self):
        html = self.text(self.client.get(f"/services/{SLUG}"))
        self.assertIn("/login?next=", html)
        self.assertIn("/register?next=", html)

    def test_signing_up_from_a_service_returns_to_the_booking_form(self):
        html = self.text(self.client.get(f"/register?next={BOOK_PATH}"))
        self.assertIn(f'value="{BOOK_PATH}"', html)
        response = self.register(next_url=BOOK_PATH)
        self.assertEqual(self.location(response), BOOK_PATH)
        self.assertEqual(self.client.get(BOOK_PATH).status_code, 200)

    def test_an_unsafe_next_address_is_ignored_when_registering(self):
        response = self.register(next_url="https://evil.example/steal")
        self.assertEqual(self.location(response), "/customer/dashboard")

    def test_an_anonymous_post_is_redirected_and_creates_nothing(self):
        data = self.valid()
        data["csrf_token"] = self.token("/login")
        data["submission_token"] = "a" * 32
        response = self.client.post(BOOK_PATH, data=data)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", self.location(response))
        self.assertEqual(self.count_bookings(), 0)

    def test_providers_and_admins_cannot_book(self):
        for role in (ROLE_PROVIDER, ROLE_ADMIN):
            with self.subTest(role):
                email = f"{role}@example.com"
                self.make_user(email, role=role)
                self.login(email=email)
                self.assertEqual(self.client.get(BOOK_PATH).status_code, 403)
                data = self.valid(csrf_token=self.token("/"), submission_token="b" * 32)
                self.assertEqual(self.client.post(BOOK_PATH, data=data).status_code, 403)
                self.assertNotIn(f'href="{BOOK_PATH}"', self.text(self.client.get(f"/services/{SLUG}")))
                self.logout()
        self.assertEqual(self.count_bookings(), 0)

    def test_an_unknown_service_is_a_404(self):
        self.customer()
        self.assertEqual(self.client.get("/services/no-such-service/book").status_code, 404)
        data = self.valid(csrf_token=self.token("/"), submission_token="c" * 32)
        self.assertEqual(self.client.post("/services/no-such-service/book", data=data).status_code, 404)
        self.assertEqual(self.client.get("/services/12345/book").status_code, 404)

    def test_an_unavailable_service_cannot_be_booked_or_seen(self):
        self.customer()
        with self.app.app_context():
            db.session.scalar(select(Service).where(Service.slug == SLUG)).is_available = False
            db.session.commit()
        self.assertEqual(self.client.get(BOOK_PATH).status_code, 404)
        self.assertEqual(self.client.get(f"/services/{SLUG}").status_code, 404)
        data = self.valid(csrf_token=self.token("/"), submission_token="d" * 32)
        self.assertEqual(self.client.post(BOOK_PATH, data=data).status_code, 404)
        listing = self.text(self.client.get("/services"))
        self.assertNotIn(f"/services/{SLUG}", listing)
        self.assertIn("11 services found", listing)
        self.assertEqual(self.count_bookings(), 0)

    def test_service_layer_refuses_an_unavailable_service_even_if_the_page_is_bypassed(self):
        email = self.customer()
        with self.app.app_context():
            service = db.session.scalar(select(Service).where(Service.slug == SLUG))
            service.is_available = False
            db.session.commit()
            with self.assertRaises(bookings.BookingRuleError):
                bookings.create_booking(accounts.get_user_by_email(email), service, contact_name="Test User", contact_phone="9876543210",
                                        address="12 Main Road, Test Area", appointment_date=bookings.now_local().date() + timedelta(days=3),
                                        appointment_time="10:00", problem_description="The tap leaks badly.")

    def test_a_valid_booking_is_saved_and_confirmed(self):
        self.customer()
        reference = self.reference_from(self.submit())
        booking = self.snap(reference)
        self.assertEqual(booking.status, "pending")
        self.assertEqual(booking.service_slug, SLUG)
        self.assertIsNone(booking.provider_id)
        self.assertEqual(booking.contact_name, "Jane Doe")
        self.assertEqual(booking.contact_phone, "+919876543210")
        self.assertEqual(booking.appointment_time, time(10, 0))
        self.assertEqual(booking.appointment_date.isoformat(), self.future(3))

        page = self.text(self.client.get(f"/bookings/{reference}/confirmation"))
        self.assertIn(reference, page)
        self.assertIn("Pending", page)
        self.assertIn("Leak Detection &amp; Pipe Repair", page)
        self.assertIn("Your booking request has been saved.", page)  # the flash message

    def test_input_is_cleaned_before_saving(self):
        self.customer()
        response = self.submit(contact_name="  Jane    Q   Doe ", contact_phone="(98765) 43210", problem_description="Line one\r\n\r\nLine two is here")
        booking = self.snap(self.reference_from(response))
        self.assertEqual(booking.contact_name, "Jane Q Doe")
        self.assertEqual(booking.contact_phone, "9876543210")
        self.assertEqual(booking.description, "Line one\n\nLine two is here")

    def test_the_starting_price_is_copied_from_the_service_and_frozen(self):
        self.customer()
        reference = self.reference_from(self.submit())
        self.assertEqual(self.snap(reference).price, 399)
        with self.app.app_context():
            db.session.scalar(select(Service).where(Service.slug == SLUG)).price_from = 999
            db.session.commit()
        self.assertEqual(self.snap(reference).price, 399)

    def test_the_booking_is_still_there_after_the_app_restarts(self):
        self.customer()
        reference = self.reference_from(self.submit())
        self.dispose(self.app)
        from app import create_app
        from tests.helpers import make_config

        restarted = create_app(make_config(self.db_path))
        self.addCleanup(self.dispose, restarted)
        with restarted.app_context():
            saved = db.session.scalar(select(Booking).where(Booking.reference == reference))
            self.assertIsNotNone(saved)
            self.assertEqual(saved.status, "pending")
            self.assertEqual(saved.service.slug, SLUG)

    def test_each_booking_gets_its_own_reference(self):
        self.customer()
        first = self.reference_from(self.submit(appointment_time="10:00"))
        second = self.reference_from(self.submit(appointment_time="11:00"))
        self.assertNotEqual(first, second)
        self.assertEqual(self.count_bookings(), 2)

    def test_the_internal_id_does_not_work_as_a_reference(self):
        self.customer()
        reference = self.reference_from(self.submit())
        internal_id = self.snap(reference).id
        for path in (f"/bookings/{internal_id}", f"/bookings/{internal_id}/cancel", f"/bookings/{internal_id}/confirmation"):
            self.assertEqual(self.client.get(path).status_code, 404, path)


class BookingValidationTests(BookingTestCase):
    def setUp(self):
        super().setUp()
        self.customer()

    def test_invalid_submissions_are_rejected_and_nothing_is_saved(self):
        today = rules.local_now(330).date()
        cases = [
            ("empty name", {"contact_name": ""}, "Enter your name"),
            ("one-letter name", {"contact_name": "J"}, "2 to 100"),
            ("name too long", {"contact_name": "J" * 101}, "2 to 100"),
            ("empty phone", {"contact_phone": ""}, "Enter a phone number"),
            ("letters in phone", {"contact_phone": "call me"}, "valid phone"),
            ("short phone", {"contact_phone": "12345"}, "valid phone"),
            ("long phone", {"contact_phone": "9" * 20}, "valid phone"),
            ("empty address", {"address": ""}, "Enter the address"),
            ("short address", {"address": "Home"}, "10 to 300"),
            ("long address", {"address": "A" * 301}, "10 to 300"),
            ("empty description", {"problem_description": ""}, "Describe the problem"),
            ("short description", {"problem_description": "Leaks"}, "10 to 1000"),
            ("long description", {"problem_description": "x" * 1001}, "10 to 1000"),
            ("missing date", {"appointment_date": ""}, "Choose a date"),
            ("malformed date", {"appointment_date": "not-a-date"}, "Choose a date"),
            ("impossible date", {"appointment_date": "2026-13-45"}, "Choose a date"),
            ("past date", {"appointment_date": (today - timedelta(days=1)).isoformat()}, "cannot be in the past"),
            ("last year", {"appointment_date": (today - timedelta(days=400)).isoformat()}, "cannot be in the past"),
            ("too far ahead", {"appointment_date": (today + timedelta(days=500)).isoformat()}, "within the next"),
            ("missing time", {"appointment_time": ""}, "Choose a time"),
            ("time outside the list", {"appointment_time": "09:15"}, "Choose a time"),
            ("malformed time", {"appointment_time": "noon"}, "Choose a time"),
        ]
        for label, overrides, expected in cases:
            with self.subTest(label):
                response = self.submit(**overrides)
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected, self.text(response))
        self.assertEqual(self.count_bookings(), 0)

    def test_missing_fields_in_the_request_are_rejected(self):
        for field in ("contact_name", "contact_phone", "address", "appointment_date", "appointment_time", "problem_description"):
            with self.subTest(field):
                response = self.submit(**{field: None})
                self.assertEqual(response.status_code, 200)
        self.assertEqual(self.count_bookings(), 0)

    def test_a_missing_or_malformed_submission_token_is_rejected(self):
        for token in (None, "", "not-hex", "A" * 32, "a" * 31, "a" * 33):
            with self.subTest(token=token):
                csrf, _real = self.open_form()
                response = self.post_booking(csrf, token)
                self.assertEqual(response.status_code, 200)
                self.assertIn("expired", self.text(response))
        self.assertEqual(self.count_bookings(), 0)

    def test_on_error_safe_values_are_kept_and_html_is_escaped(self):
        response = self.submit(contact_name="Jane <b>X</b>", contact_phone="abc", problem_description="My <script>alert(1)</script> tap leaks badly")
        html = self.text(response)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Jane &lt;b&gt;X&lt;/b&gt;", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("12 Main Road, Test Area", html)  # the address was kept
        self.assertEqual(self.count_bookings(), 0)

    def test_the_customer_cannot_choose_status_provider_price_customer_or_reference(self):
        with self.app.app_context():
            other_service = db.session.scalar(select(Service.id).where(Service.slug == OTHER_SLUG))
        other_user = self.make_user("other@example.com")
        provider = self.make_user("prov@example.com", role=ROLE_PROVIDER)
        reference = self.reference_from(self.submit(
            status="completed", provider_id=str(provider), price_from_at_booking="1", customer_id=str(other_user),
            service_id=str(other_service), role="admin", reference="FN-AAAA-BBBB", cancellation_reason="hack",
        ))
        booking = self.snap(reference)
        self.assertEqual(booking.status, "pending")
        self.assertIsNone(booking.provider_id)
        self.assertEqual(booking.price, 399)
        self.assertNotEqual(booking.customer_id, other_user)
        self.assertEqual(booking.service_slug, SLUG)
        self.assertNotEqual(reference, "FN-AAAA-BBBB")
        self.assertIsNone(booking.reason)

    def test_service_layer_rules_hold_without_the_form(self):
        with self.app.app_context():
            customer = accounts.get_user_by_email("cust@example.com")
            service = catalog.get_service(SLUG)
            good = dict(contact_name="Test User", contact_phone="9876543210", address="12 Main Road, Test Area",
                        appointment_date=bookings.now_local().date() + timedelta(days=3), appointment_time="10:00",
                        problem_description="The tap leaks badly.")
            for bad in (
                {"appointment_date": bookings.now_local().date() - timedelta(days=1)},
                {"appointment_time": "03:00"},
                {"contact_phone": "xx"},
                {"contact_name": "J"},
                {"address": "short"},
                {"problem_description": "x" * 1001},
            ):
                with self.subTest(bad), self.assertRaises(bookings.BookingRuleError):
                    bookings.create_booking(customer, service, **{**good, **bad})
            self.assertEqual(db.session.scalar(select(func.count(Booking.id))), 0)

    def test_service_layer_refuses_non_customers(self):
        provider_email = "prov@example.com"
        self.make_user(provider_email, role=ROLE_PROVIDER)
        with self.app.app_context():
            with self.assertRaises(bookings.BookingPermissionError):
                bookings.create_booking(accounts.get_user_by_email(provider_email), catalog.get_service(SLUG),
                                        contact_name="Test User", contact_phone="9876543210", address="12 Main Road, Test Area",
                                        appointment_date=bookings.now_local().date() + timedelta(days=3), appointment_time="10:00",
                                        problem_description="The tap leaks badly.")


class DuplicateSubmissionTests(BookingTestCase):
    def setUp(self):
        super().setUp()
        self.customer()

    def test_submitting_the_same_form_twice_creates_one_booking(self):
        csrf, submission = self.open_form()
        first = self.reference_from(self.post_booking(csrf, submission))
        second = self.reference_from(self.post_booking(csrf, submission))
        self.assertEqual(first, second)
        self.assertEqual(self.count_bookings(), 1)
        self.assertIn("already saved", self.text(self.client.get(f"/bookings/{second}/confirmation")))

    def test_the_same_slot_booked_again_from_a_new_form_is_refused(self):
        self.reference_from(self.submit())
        response = self.submit()
        self.assertEqual(response.status_code, 200)
        self.assertIn("already have an active booking", self.text(response))
        self.assertEqual(self.count_bookings(), 1)

    def test_a_different_time_or_service_is_allowed(self):
        self.reference_from(self.submit())
        self.reference_from(self.submit(appointment_time="11:00"))
        self.reference_from(self.submit(slug=OTHER_SLUG))
        self.assertEqual(self.count_bookings(), 3)

    def test_after_cancelling_the_same_slot_can_be_booked_again(self):
        reference = self.reference_from(self.submit())
        self.set_status(reference, "cancelled")
        self.reference_from(self.submit())
        self.assertEqual(self.count_bookings(), 2)

    def test_two_customers_may_book_the_same_slot(self):
        self.reference_from(self.submit())
        self.logout()
        self.customer("second@example.com")
        self.reference_from(self.submit())
        self.assertEqual(self.count_bookings(), 2)

    def test_a_reference_collision_is_retried_safely(self):
        first = self.make_booking(slot="10:00")
        with self.app.app_context():
            customer = accounts.get_user_by_email("cust@example.com")
            service = catalog.get_service(SLUG)
            kwargs = dict(contact_name="Test User", contact_phone="9876543210", address="12 Main Road, Test Area",
                          appointment_date=bookings.now_local().date() + timedelta(days=4), problem_description="The tap leaks badly.")
            with mock.patch.object(rules, "generate_reference", side_effect=[first, first, "FN-2222-3333"]):
                booking, created = bookings.create_booking(customer, service, appointment_time="11:00", **kwargs)
            self.assertTrue(created)
            self.assertEqual(booking.reference, "FN-2222-3333")

            with mock.patch.object(rules, "generate_reference", return_value=first):
                with self.assertRaises(bookings.BookingReferenceError):
                    bookings.create_booking(customer, service, appointment_time="12:00", **kwargs)
            self.assertEqual(db.session.scalar(select(func.count(Booking.id))), 2)


class BookingCsrfTests(BookingTestCase):
    def setUp(self):
        super().setUp()
        self.customer()

    def test_booking_without_a_csrf_token_is_refused(self):
        data = self.valid(submission_token="a" * 32)
        response = self.client.post(BOOK_PATH, data=data)
        self.assertEqual(response.status_code, 400)
        self.assertIn("could not be verified", self.text(response))
        self.assertEqual(self.count_bookings(), 0)

    def test_booking_with_a_wrong_csrf_token_is_refused(self):
        self.open_form()
        response = self.post_booking("forged-token", "a" * 32)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.count_bookings(), 0)

    def test_cancelling_without_a_csrf_token_is_refused(self):
        reference = self.make_booking()
        self.assertEqual(self.client.post(f"/bookings/{reference}/cancel", data={"reason": "x"}).status_code, 400)
        self.assertEqual(self.snap(reference).status, "pending")

    def test_the_booking_and_cancel_forms_contain_tokens(self):
        reference = self.make_booking()
        self.assertIn('name="csrf_token"', self.text(self.client.get(BOOK_PATH)))
        self.assertIn('name="csrf_token"', self.text(self.client.get(f"/bookings/{reference}/cancel")))


# ================================================================== history
class BookingHistoryTests(BookingTestCase):
    def test_an_empty_history_shows_an_empty_state(self):
        self.customer()
        html = self.text(self.client.get("/bookings"))
        self.assertIn("You have not booked any services yet", html)
        self.assertNotIn("FN-", html)

    def test_history_lists_real_bookings_newest_first(self):
        self.customer()
        first = self.make_booking(slot="10:00")
        second = self.make_booking(slot="11:00")
        html = self.text(self.client.get("/bookings"))
        self.assertIn(first, html)
        self.assertIn(second, html)
        self.assertLess(html.index(second), html.index(first))
        self.assertIn("Leak Detection &amp; Pipe Repair", html)

    def test_history_shows_only_my_bookings(self):
        self.customer("a@example.com")
        mine = self.make_booking("a@example.com")
        self.logout()
        self.customer("b@example.com")
        theirs = self.make_booking("b@example.com", slot="11:00")
        html = self.text(self.client.get("/bookings"))
        self.assertIn(theirs, html)
        self.assertNotIn(mine, html)

    def test_status_filter(self):
        self.customer()
        pending = self.make_booking(slot="10:00")
        accepted = self.make_booking(slot="11:00")
        self.set_status(accepted, "accepted")
        html = self.text(self.client.get("/bookings?status=accepted"))
        self.assertIn(accepted, html)
        self.assertNotIn(pending, html)
        everything = self.text(self.client.get("/bookings?status=nonsense"))  # unknown filters are ignored
        self.assertIn(pending, everything)
        self.assertIn(accepted, everything)
        self.assertIn("No completed bookings", self.text(self.client.get("/bookings?status=completed")))

    def test_history_requires_a_customer_login(self):
        self.assertEqual(self.client.get("/bookings").status_code, 302)
        self.make_user("prov@example.com", role=ROLE_PROVIDER)
        self.login(email="prov@example.com")
        self.assertEqual(self.client.get("/bookings").status_code, 403)

    def test_booking_pages_are_not_cached(self):
        self.customer()
        reference = self.make_booking()
        for path in ("/bookings", f"/bookings/{reference}", f"/bookings/{reference}/confirmation", BOOK_PATH):
            self.assertEqual(self.client.get(path).headers["Cache-Control"], "no-store", path)

    def test_my_bookings_link_is_only_in_the_customer_menu(self):
        self.customer()
        self.assertIn("My bookings", self.text(self.client.get("/")))
        self.logout()
        self.make_user("prov@example.com", role=ROLE_PROVIDER)
        self.login(email="prov@example.com")
        self.assertNotIn("My bookings", self.text(self.client.get("/")))


class BookingDetailTests(BookingTestCase):
    def test_details_show_the_booking_and_its_progress(self):
        self.customer()
        reference = self.make_booking()
        self.set_status(reference, "accepted")
        html = self.text(self.client.get(f"/bookings/{reference}"))
        for expected in (reference, "Accepted", "Leak Detection &amp; Pipe Repair", "12 Main Road, Test Area", "9876543210", "Not assigned yet", "The tap leaks badly."):
            self.assertIn(expected, html)
        self.assertIn("is-done", html)
        self.assertIn("is-current", html)

    def test_cancelled_and_rejected_bookings_explain_themselves(self):
        self.customer()
        cancelled = self.make_booking(slot="10:00")
        rejected = self.make_booking(slot="11:00")
        self.set_status(cancelled, "cancelled")
        self.set_status(rejected, "rejected")
        self.assertIn("was cancelled", self.text(self.client.get(f"/bookings/{cancelled}")))
        self.assertIn("was rejected", self.text(self.client.get(f"/bookings/{rejected}")))


# ================================================================ ownership
class BookingOwnershipTests(BookingTestCase):
    def setUp(self):
        super().setUp()
        self.customer("a@example.com")
        self.reference = self.make_booking("a@example.com")
        self.logout()

    def test_another_customer_cannot_see_or_touch_the_booking(self):
        self.customer("b@example.com")
        for path in (f"/bookings/{self.reference}", f"/bookings/{self.reference}/confirmation", f"/bookings/{self.reference}/cancel"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404, path)
            self.assertNotIn("12 Main Road", self.text(response))
            self.assertNotIn(self.reference, self.text(response))
        cancel = self.client.post(f"/bookings/{self.reference}/cancel", data={"csrf_token": self.token("/"), "reason": "not mine"})
        self.assertEqual(cancel.status_code, 404)
        self.assertEqual(self.snap(self.reference).status, "pending")

    def test_the_other_customer_gets_the_same_404_as_for_a_booking_that_does_not_exist(self):
        self.customer("b@example.com")
        real_but_not_mine = self.client.get(f"/bookings/{self.reference}")
        made_up = self.client.get("/bookings/FN-ZZZZ-ZZZZ")
        self.assertEqual(real_but_not_mine.status_code, made_up.status_code)
        # CSRF tokens contain a timestamp, so blank them out before comparing the pages.
        blank = lambda html: re.sub(r'(name="csrf_token" value=")[^"]+', r"\1X", html)
        self.assertEqual(blank(self.text(real_but_not_mine)), blank(self.text(made_up)))

    def test_visitors_are_sent_to_login(self):
        self.assertEqual(self.client.get(f"/bookings/{self.reference}").status_code, 302)
        response = self.client.post(f"/bookings/{self.reference}/cancel", data={"csrf_token": self.token("/login")})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", self.location(response))
        self.assertEqual(self.snap(self.reference).status, "pending")

    def test_providers_and_admins_are_blocked_from_customer_booking_pages(self):
        for role in (ROLE_PROVIDER, ROLE_ADMIN):
            with self.subTest(role):
                email = f"{role}2@example.com"
                self.make_user(email, role=role)
                self.login(email=email)
                self.assertEqual(self.client.get(f"/bookings/{self.reference}").status_code, 403)
                response = self.client.post(f"/bookings/{self.reference}/cancel", data={"csrf_token": self.token("/")})
                self.assertEqual(response.status_code, 403)
                self.logout()
        self.assertEqual(self.snap(self.reference).status, "pending")

    def test_invalid_references_are_a_plain_404(self):
        self.login(email="a@example.com")  # the account already exists (created in setUp)
        for bad in ["abc", "FN-0000-0000", "FN-AAAA-BBBB' OR '1'='1", "../etc/passwd", "1", "FN-AAAA-BBBB-CCCC", "%00", "<script>"]:
            for suffix in ("", "/cancel", "/confirmation"):
                response = self.client.get("/bookings/" + quote(bad, safe="") + suffix)
                self.assertEqual(response.status_code, 404, (bad, suffix))
                self.assertNotIn("Traceback", self.text(response))

    def test_service_layer_ownership_checks(self):
        self.customer("b@example.com")
        with self.app.app_context():
            booking = db.session.scalar(select(Booking).where(Booking.reference == self.reference))
            with self.assertRaises(bookings.BookingPermissionError):
                bookings.cancel_booking(booking, accounts.get_user_by_email("b@example.com"))
            self.assertIsNone(bookings.get_customer_booking(accounts.get_user_by_email("b@example.com"), self.reference))
            self.assertIsNotNone(bookings.get_customer_booking(accounts.get_user_by_email("a@example.com"), self.reference.lower()))


# ============================================================== cancellation
class CancellationTests(BookingTestCase):
    def setUp(self):
        super().setUp()
        self.customer()

    def post_cancel(self, reference, **data):
        data = {"csrf_token": self.token(f"/bookings/{reference}/cancel") if self.snap(reference).status in ("pending", "accepted") else self.token("/"), **data}
        return self.client.post(f"/bookings/{reference}/cancel", data=data)

    def test_the_confirmation_page_lists_the_booking(self):
        reference = self.make_booking()
        html = self.text(self.client.get(f"/bookings/{reference}/cancel"))
        self.assertIn("Cancel this booking?", html)
        self.assertIn(reference, html)
        self.assertIn("Yes, cancel this booking", html)

    def test_a_pending_booking_can_be_cancelled_with_a_reason(self):
        reference = self.make_booking()
        response = self.post_cancel(reference, reason="  Fixed it   myself ")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.location(response), f"/bookings/{reference}")
        booking = self.snap(reference)
        self.assertEqual(booking.status, "cancelled")
        self.assertEqual(booking.reason, "Fixed it myself")
        self.assertIsNotNone(booking.cancelled_at)
        page = self.text(self.client.get(f"/bookings/{reference}"))
        self.assertIn("Your booking has been cancelled.", page)
        self.assertIn("was cancelled", page)
        self.assertIn("Fixed it myself", page)
        self.assertNotIn("Cancel this booking", page)

    def test_the_reason_is_optional(self):
        reference = self.make_booking()
        self.post_cancel(reference)
        self.assertEqual(self.snap(reference).status, "cancelled")
        self.assertIsNone(self.snap(reference).reason)

    def test_an_over_long_reason_is_rejected_by_the_form(self):
        reference = self.make_booking()
        response = self.post_cancel(reference, reason="x" * 301)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.snap(reference).status, "pending")

    def test_an_accepted_booking_far_in_the_future_can_be_cancelled(self):
        reference = self.make_booking(days=10)
        self.set_status(reference, "accepted")
        self.assertEqual(self.post_cancel(reference).status_code, 302)
        self.assertEqual(self.snap(reference).status, "cancelled")

    def test_an_accepted_booking_inside_the_notice_period_cannot_be_cancelled(self):
        reference = self.make_booking(days=10, slot="10:00")
        self.set_status(reference, "accepted")
        with self.app.app_context():
            booking = db.session.scalar(select(Booking).where(Booking.reference == reference))
            customer = accounts.get_user_by_email("cust@example.com")
            start = booking.appointment_start
            with self.assertRaises(bookings.BookingRuleError) as caught:
                bookings.cancel_booking(booking, customer, now=start - timedelta(hours=5))
            self.assertIn("24 hours", str(caught.exception))
            self.assertEqual(booking.status, "accepted")
            bookings.cancel_booking(booking, customer, now=start - timedelta(hours=25))
            self.assertEqual(booking.status, "cancelled")

    def test_final_and_in_progress_bookings_cannot_be_cancelled(self):
        cases = [("completed", "Completed bookings cannot be cancelled."), ("rejected", "Rejected bookings cannot be cancelled."),
                 ("in_progress", "already in progress"), ("cancelled", "already been cancelled")]
        for index, (status, message) in enumerate(cases):
            with self.subTest(status):
                reference = self.make_booking(slot=rules.TIME_SLOTS[index])
                self.set_status(reference, status)
                before = self.snap(reference)
                page_get = self.client.get(f"/bookings/{reference}/cancel")
                self.assertEqual(page_get.status_code, 302)
                response = self.post_cancel(reference, reason="trying anyway")
                self.assertEqual(response.status_code, 302)
                self.assertIn(message, self.text(self.client.get(self.location(response))))
                after = self.snap(reference)
                self.assertEqual((after.status, after.reason), (before.status, before.reason))

    def test_cancelling_twice_changes_nothing_the_second_time(self):
        reference = self.make_booking()
        self.post_cancel(reference, reason="first reason")
        self.post_cancel(reference, reason="second reason")
        booking = self.snap(reference)
        self.assertEqual((booking.status, booking.reason), ("cancelled", "first reason"))

    def test_cancelling_cannot_be_used_to_change_other_fields(self):
        reference = self.make_booking()
        provider = self.make_user("prov@example.com", role=ROLE_PROVIDER)
        self.post_cancel(reference, status="completed", provider_id=str(provider), price_from_at_booking="0")
        booking = self.snap(reference)
        self.assertEqual(booking.status, "cancelled")
        self.assertIsNone(booking.provider_id)
        self.assertEqual(booking.price, 399)

    def test_the_dashboard_offers_cancel_only_when_allowed(self):
        pending = self.make_booking(slot="10:00")
        done = self.make_booking(slot="11:00")
        self.set_status(done, "completed")
        html = self.text(self.client.get("/customer/dashboard"))
        self.assertIn(f"/bookings/{pending}/cancel", html)
        self.assertNotIn(f"/bookings/{done}/cancel", html)


# ========================================================= status transitions
class StatusTransitionTests(BookingTestCase):
    def setUp(self):
        super().setUp()
        self.customer()
        self.reference = self.make_booking()

    def move(self, status):
        with self.app.app_context():
            booking = db.session.scalar(select(Booking).where(Booking.reference == self.reference))
            return bookings.transition_status(booking, status).status

    def test_the_normal_path_works_step_by_step(self):
        for status in ("accepted", "in_progress", "completed"):
            self.assertEqual(self.move(status), status)
            self.assertEqual(self.snap(self.reference).status, status)

    def test_pending_cannot_jump_to_completed(self):
        with self.assertRaises(bookings.InvalidTransitionError):
            self.move("completed")
        self.assertEqual(self.snap(self.reference).status, "pending")

    def test_invalid_changes_are_refused_and_leave_the_booking_alone(self):
        for start, target in [("pending", "in_progress"), ("accepted", "completed"), ("accepted", "pending"), ("completed", "pending"),
                              ("completed", "cancelled"), ("cancelled", "accepted"), ("rejected", "accepted"), ("pending", "refunded")]:
            with self.subTest(f"{start}->{target}"):
                self.set_status(self.reference, start)
                with self.assertRaises(bookings.InvalidTransitionError):
                    self.move(target)
                self.assertEqual(self.snap(self.reference).status, start)


# ================================================================ dashboard
class CustomerDashboardTests(BookingTestCase):
    def test_new_customer_sees_zeroes_and_an_empty_state(self):
        self.customer()
        html = self.text(self.client.get("/customer/dashboard"))
        for name in ("total", "pending", "accepted", "completed"):
            self.assertEqual(self.stat(html, name), 0)
        self.assertIn("You have not booked any services yet", html)
        self.assertNotIn("FN-", html)

    def test_statistics_and_recent_bookings_come_from_the_database(self):
        self.customer()
        refs = {}
        for index, status in enumerate(["pending", "pending", "accepted", "completed", "cancelled"]):
            refs[index] = self.make_booking(slot=rules.TIME_SLOTS[index])
            if status != "pending":
                self.set_status(refs[index], status)
        html = self.text(self.client.get("/customer/dashboard"))
        self.assertEqual(self.stat(html, "total"), 5)
        self.assertEqual(self.stat(html, "pending"), 2)
        self.assertEqual(self.stat(html, "accepted"), 1)
        self.assertEqual(self.stat(html, "completed"), 1)
        for reference in refs.values():
            self.assertIn(reference, html)
        for expected in ("Leak Detection &amp; Pipe Repair", "View details", "Pending", "Accepted", "Completed", "Cancelled"):
            self.assertIn(expected, html)

    def test_only_the_five_most_recent_bookings_are_listed(self):
        self.customer()
        refs = [self.make_booking(slot=rules.TIME_SLOTS[i]) for i in range(6)]
        html = self.text(self.client.get("/customer/dashboard"))
        self.assertEqual(html.count("booking-card-title"), 5)
        self.assertNotIn(refs[0], html)  # the oldest is left off
        self.assertIn(refs[5], html)
        self.assertEqual(self.stat(html, "total"), 6)
        self.assertIn("See all", html)

    def test_other_customers_bookings_are_never_counted_or_shown(self):
        self.customer("a@example.com")
        theirs = self.make_booking("a@example.com")
        self.logout()
        self.customer("b@example.com")
        html = self.text(self.client.get("/customer/dashboard"))
        self.assertEqual(self.stat(html, "total"), 0)
        self.assertNotIn(theirs, html)

    def test_view_details_and_cancel_actions_point_at_the_right_booking(self):
        self.customer()
        reference = self.make_booking()
        html = self.text(self.client.get("/customer/dashboard"))
        self.assertIn(f'href="/bookings/{reference}"', html)
        self.assertIn(f'href="/bookings/{reference}/cancel"', html)


# ============================================================ whole journey
class EndToEndTests(BookingTestCase):
    def test_visitor_to_confirmed_booking_to_cancellation(self):
        # 1. a visitor opens a service and chooses to book
        service_page = self.text(self.client.get(f"/services/{SLUG}"))
        self.assertIn("/login?next=", service_page)
        # 2. they register from there and land on the booking form
        self.assertEqual(self.location(self.register(next_url=BOOK_PATH)), BOOK_PATH)
        # 3. they submit the booking
        reference = self.reference_from(self.submit())
        # 4. they see it in their history and dashboard
        self.assertIn(reference, self.text(self.client.get("/bookings")))
        self.assertIn(reference, self.text(self.client.get("/customer/dashboard")))
        # 5. they cancel it
        cancel = self.client.post(f"/bookings/{reference}/cancel", data={"csrf_token": self.token(f"/bookings/{reference}/cancel")})
        self.assertEqual(cancel.status_code, 302)
        self.assertEqual(self.snap(reference).status, "cancelled")

    def test_existing_public_pages_still_work_for_a_customer_with_bookings(self):
        self.customer()
        self.make_booking()
        for url in ("/", "/services", "/services?q=leak", "/services?category=plumbing", f"/services/{SLUG}", "/about", "/contact"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_a_broken_bookings_table_shows_a_safe_error_page(self):
        self.customer()
        with self.app.app_context():
            Booking.__table__.drop(db.engine)
        with self.assertLogs(self.app.logger, level="ERROR"):
            response = self.client.get("/bookings")
        body = self.text(response)
        self.assertEqual(response.status_code, 500)
        self.assertIn("Something went wrong", body)
        for secret in ("OperationalError", "no such table", "Traceback", "SELECT"):
            self.assertNotIn(secret, body)


if __name__ == "__main__":
    import unittest

    unittest.main()
