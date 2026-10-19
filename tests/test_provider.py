"""Stage 6 tests: provider/service links, automatic assignment, availability and
conflict checks, the provider dashboard, provider actions, ownership, CSRF and
the provider admin commands.

Every test uses its own temporary SQLite database. CSRF protection stays ON.
"""
import re
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import create_app
from flask import render_template_string
from flask_login import login_user
from extensions import db
from models import ROLE_ADMIN, ROLE_PROVIDER, Booking, Service, User, provider_services
from services import accounts, bookings, providers, scheduling
from services import booking_rules as rules
from services import provider_bookings
from services.errors import BookingPermissionError, NoProviderAvailableError
from services.permissions import can_manage_booking
from tests.helpers import make_config
from tests.test_auth import PASSWORD
from tests.test_bookings import OTHER_SLUG, SLUG, BookingTestCase

THIRD_SLUG = "split-ac-installation"  # a service nobody offers in these tests


class ProviderTestCase(BookingTestCase):
    """Helpers for provider tests."""

    def make_provider(self, email="prov@example.com", services=(SLUG,), full_name="Pat Provider", active=True):
        with self.app.app_context():
            user = accounts.create_user(email, full_name, PASSWORD, role=ROLE_PROVIDER)
            for slug in services:
                providers.grant_service(user, providers.get_service_by_slug(slug))
            if not active:
                user.is_active = False
                db.session.commit()
            return user.id

    def user_id(self, email):
        with self.app.app_context():
            return accounts.get_user_by_email(email).id

    def day(self, days=3):
        return rules.local_now(330).date() + timedelta(days=days)

    def raw_booking(self, customer_email, provider_id, slug=SLUG, slot="10:00", days=3, status="pending"):
        """Insert a booking directly, bypassing automatic assignment (to set up special situations)."""
        with self.app.app_context():
            booking = Booking(
                reference=rules.generate_reference(),
                customer_id=accounts.get_user_by_email(customer_email).id,
                service_id=db.session.scalar(select(Service.id).where(Service.slug == slug)),
                provider_id=provider_id,
                contact_name="Test User", contact_phone="9876543210", address="12 Main Road, Test Area",
                appointment_date=self.day(days), appointment_time=rules.parse_time_slot(slot),
                problem_description="The tap leaks badly.", price_from_at_booking=399, status=status,
            )
            db.session.add(booking)
            db.session.commit()
            return booking.reference

    def act(self, booking_reference, action, token_url="/provider/dashboard", **extra):
        data = {"csrf_token": self.token(token_url), **extra}
        return self.client.post(f"/provider/bookings/{booking_reference}/{action}", data=data)

    def action_names_in(self, html, booking_reference):
        """Provider actions (accept/reject/start/complete) that a page offers for this booking.

        Looks for the action URLs, so it does not depend on how the HTML is formatted.
        """
        return set(re.findall(rf"/provider/bookings/{re.escape(booking_reference)}/(accept|reject|start|complete)\b", html))

    def follow(self, response):
        """The page a redirect points to (this is where flash messages show up)."""
        return self.text(self.client.get(self.location(response)))

    def run_command(self, app, *args, input_text=None):
        return app.test_cli_runner().invoke(args=list(args), input=input_text)


class ProviderActionTestCase(ProviderTestCase):
    """One provider, one customer and one booking that was automatically assigned to the provider."""

    def setUp(self):
        super().setUp()
        self.provider_id = self.make_provider()
        self.make_user("cust@example.com")
        self.reference = self.make_booking("cust@example.com")
        self.assertEqual(self.snap(self.reference).provider_id, self.provider_id)
        self.login(email="prov@example.com")


# =========================================================== provider <-> service
class ProviderServiceLinkTests(ProviderTestCase):
    def test_a_provider_can_be_linked_to_a_service(self):
        provider_id = self.make_provider(services=())
        with self.app.app_context():
            provider = db.session.get(User, provider_id)
            service = providers.get_service_by_slug(SLUG)
            self.assertTrue(providers.grant_service(provider, service))
            self.assertFalse(providers.grant_service(provider, service))  # already linked: nothing happens
            self.assertEqual([s.slug for s in providers.offered_services(provider)], [SLUG])
            self.assertEqual([p.id for p in service.providers], [provider_id])
            self.assertEqual(db.session.scalar(select(func.count()).select_from(provider_services)), 1)

    def test_only_provider_accounts_can_offer_services(self):
        self.make_user("cust@example.com")
        self.make_user("boss@example.com", role=ROLE_ADMIN)
        with self.app.app_context():
            service = providers.get_service_by_slug(SLUG)
            for email in ("cust@example.com", "boss@example.com"):
                with self.assertRaises(ValueError):
                    providers.grant_service(accounts.get_user_by_email(email), service)
            with self.assertRaises(ValueError):
                providers.grant_service(None, service)

    def test_an_unknown_service_cannot_be_linked(self):
        provider_id = self.make_provider(services=())
        with self.app.app_context():
            with self.assertRaises(ValueError):
                providers.grant_service(db.session.get(User, provider_id), None)

    def test_revoking_a_service_keeps_existing_bookings(self):
        provider_id = self.make_provider()
        self.make_user("cust@example.com")
        reference = self.make_booking("cust@example.com")
        with self.app.app_context():
            provider = db.session.get(User, provider_id)
            self.assertTrue(providers.revoke_service(provider, providers.get_service_by_slug(SLUG)))
            self.assertFalse(providers.revoke_service(provider, providers.get_service_by_slug(SLUG)))
            self.assertEqual(providers.offered_services(provider), [])
        self.assertEqual(self.snap(reference).provider_id, provider_id)

    def test_the_database_blocks_duplicate_links(self):
        provider_id = self.make_provider()
        with self.app.app_context():
            service_id = db.session.scalar(select(Service.id).where(Service.slug == SLUG))
            with self.assertRaises(IntegrityError):
                db.session.execute(provider_services.insert().values(provider_id=provider_id, service_id=service_id))
                db.session.commit()
            db.session.rollback()

    def test_deleting_a_provider_removes_their_links_only(self):
        provider_id = self.make_provider()
        with self.app.app_context():
            db.session.delete(db.session.get(User, provider_id))
            db.session.commit()
            self.assertEqual(db.session.scalar(select(func.count()).select_from(provider_services)), 0)
            self.assertIsNotNone(providers.get_service_by_slug(SLUG))

    def test_get_provider_by_email_ignores_other_roles(self):
        self.make_provider()
        self.make_user("cust@example.com")
        with self.app.app_context():
            self.assertIsNotNone(providers.get_provider_by_email(" PROV@example.com "))
            self.assertIsNone(providers.get_provider_by_email("cust@example.com"))
            self.assertIsNone(providers.get_provider_by_email(""))


# ============================================================== scheduling
class SchedulingTests(ProviderTestCase):
    def setUp(self):
        super().setUp()
        self.p1 = self.make_provider("p1@example.com", full_name="Provider One")
        for n in range(1, 5):
            self.make_user(f"c{n}@example.com")

    def conflict(self, provider_id, when, slot, **kwargs):
        with self.app.app_context():
            return scheduling.find_conflict(provider_id, when, rules.parse_time_slot(slot), **kwargs) is not None

    def test_a_booking_blocks_the_two_hours_around_its_start_time(self):
        reference = self.make_booking("c1@example.com", slot="10:00")
        self.assertEqual(self.snap(reference).provider_id, self.p1)
        expected = {"10:00": True, "11:30": True, "08:30": True, "11:00": True, "12:00": False, "08:00": False, "19:30": False}
        for slot, clashes in expected.items():
            with self.subTest(slot):
                self.assertEqual(self.conflict(self.p1, self.day(), slot), clashes)

    def test_another_day_never_conflicts(self):
        self.make_booking("c1@example.com", slot="10:00")
        self.assertFalse(self.conflict(self.p1, self.day(4), "10:00"))

    def test_finished_or_dropped_bookings_do_not_block(self):
        reference = self.make_booking("c1@example.com", slot="10:00")
        for status in ("cancelled", "rejected", "completed"):
            with self.subTest(status):
                self.set_status(reference, status)
                self.assertFalse(self.conflict(self.p1, self.day(), "10:00"))

    def test_the_statuses_argument_chooses_what_counts(self):
        reference = self.make_booking("c1@example.com", slot="10:00")  # pending
        self.assertTrue(self.conflict(self.p1, self.day(), "10:00"))
        self.assertFalse(self.conflict(self.p1, self.day(), "10:00", statuses=rules.COMMITTED_STATUSES))
        for status in ("accepted", "in_progress"):
            self.set_status(reference, status)
            self.assertTrue(self.conflict(self.p1, self.day(), "10:00", statuses=rules.COMMITTED_STATUSES), status)

    def test_a_booking_can_be_excluded_from_its_own_check(self):
        reference = self.make_booking("c1@example.com", slot="10:00")
        self.assertFalse(self.conflict(self.p1, self.day(), "10:00", exclude_booking_id=self.snap(reference).id))

    def test_a_service_nobody_offers_stays_unassigned(self):
        reference = self.make_booking("c1@example.com", slug=OTHER_SLUG)
        self.assertIsNone(self.snap(reference).provider_id)

    def test_a_provider_is_only_used_for_services_they_offer(self):
        p2 = self.make_provider("p2@example.com", services=(OTHER_SLUG,))
        self.assertEqual(self.snap(self.make_booking("c1@example.com", slug=OTHER_SLUG)).provider_id, p2)
        self.assertEqual(self.snap(self.make_booking("c2@example.com", slug=SLUG)).provider_id, self.p1)

    def test_a_busy_provider_means_no_provider_available(self):
        self.make_booking("c1@example.com", slot="10:00")
        before = self.count_bookings()
        with self.assertRaises(NoProviderAvailableError):
            self.make_booking("c2@example.com", slot="11:00")
        self.assertEqual(self.count_bookings(), before)

    def test_work_is_spread_across_free_providers(self):
        p2 = self.make_provider("p2@example.com", full_name="Provider Two")
        first = self.snap(self.make_booking("c1@example.com", slot="08:00"))
        second = self.snap(self.make_booking("c2@example.com", slot="14:00"))
        third = self.snap(self.make_booking("c3@example.com", slot="14:00"))
        self.assertEqual(first.provider_id, self.p1)  # tie: lowest account number
        self.assertEqual(second.provider_id, p2)  # p1 already has a job that day
        self.assertEqual(third.provider_id, self.p1)  # p2 is busy at 14:00
        with self.assertRaises(NoProviderAvailableError):  # now both are busy at 14:00
            self.make_booking("c4@example.com", slot="14:00")

    def test_a_suspended_provider_is_not_used(self):
        with self.app.app_context():
            db.session.get(User, self.p1).is_active = False
            db.session.commit()
        self.assertIsNone(self.snap(self.make_booking("c1@example.com")).provider_id)

    def test_pending_requests_also_block_the_time_when_assigning(self):
        self.make_booking("c1@example.com", slot="10:00")  # still pending
        with self.assertRaises(NoProviderAvailableError):
            self.make_booking("c2@example.com", slot="10:30")


class AssignExistingTests(ProviderTestCase):
    def setUp(self):
        super().setUp()
        for n in range(1, 3):
            self.make_user(f"c{n}@example.com")

    def assign(self, reference):
        with self.app.app_context():
            booking = db.session.scalar(select(Booking).where(Booking.reference == reference))
            provider = scheduling.assign_existing(booking)
            return provider.id if provider else None

    def test_an_unassigned_pending_booking_gets_a_provider_once_one_exists(self):
        reference = self.make_booking("c1@example.com")
        self.assertIsNone(self.snap(reference).provider_id)
        self.assertIsNone(self.assign(reference))  # nobody offers the service yet
        provider_id = self.make_provider()
        self.assertEqual(self.assign(reference), provider_id)
        self.assertEqual(self.snap(reference).provider_id, provider_id)
        self.assertIsNone(self.assign(reference))  # already assigned: left alone

    def test_bookings_that_are_not_pending_are_not_touched(self):
        reference = self.make_booking("c1@example.com")
        self.set_status(reference, "cancelled")
        self.make_provider()
        self.assertIsNone(self.assign(reference))
        self.assertIsNone(self.snap(reference).provider_id)

    def test_a_busy_provider_leaves_the_booking_unassigned(self):
        waiting = self.make_booking("c1@example.com", slot="11:00")
        provider_id = self.make_provider()
        self.make_booking("c2@example.com", slot="10:00")  # takes the provider's morning
        self.assertIsNone(self.assign(waiting))
        self.assertIsNone(self.snap(waiting).provider_id)
        self.assertIsNotNone(provider_id)


class AutoAssignmentFlowTests(ProviderTestCase):
    def test_a_new_booking_is_sent_to_the_provider_who_offers_the_service(self):
        provider_id = self.make_provider()
        self.customer("c1@example.com")
        reference = self.reference_from(self.submit())
        self.assertEqual(self.snap(reference).provider_id, provider_id)
        self.assertEqual(self.snap(reference).status, "pending")
        confirmation = self.text(self.client.get(f"/bookings/{reference}/confirmation"))
        self.assertIn("Pat Provider", confirmation)
        detail = self.text(self.client.get(f"/bookings/{reference}"))
        self.assertIn("Waiting for Pat Provider", detail)
        self.assertNotIn("prov@example.com", detail + confirmation)  # no provider email shown to customers

    def test_the_customer_cannot_choose_the_provider(self):
        offering = self.make_provider("offering@example.com", services=(SLUG,))
        other = self.make_provider("other@example.com", services=(OTHER_SLUG,))
        self.customer("c1@example.com")
        reference = self.reference_from(self.submit(provider_id=str(other), assigned_to=str(other)))
        self.assertEqual(self.snap(reference).provider_id, offering)

    def test_a_service_nobody_offers_can_still_be_booked_unassigned(self):
        self.customer("c1@example.com")
        reference = self.reference_from(self.submit())
        self.assertIsNone(self.snap(reference).provider_id)
        self.assertIn("Not assigned yet", self.text(self.client.get(f"/bookings/{reference}")))

    def test_when_every_provider_is_busy_the_booking_is_refused_clearly(self):
        self.make_provider()
        self.customer("c1@example.com")
        self.reference_from(self.submit())
        self.logout()
        self.customer("c2@example.com")
        response = self.submit()
        self.assertEqual(response.status_code, 200)
        self.assertIn("No provider is available for that date and time", self.text(response))
        self.assertEqual(self.count_bookings(), 1)
        self.reference_from(self.submit(appointment_time="14:00"))  # another time works
        self.assertEqual(self.count_bookings(), 2)

    def test_a_customer_can_still_cancel_an_assigned_booking_and_the_provider_sees_it(self):
        self.make_provider()
        self.customer("c1@example.com")
        reference = self.reference_from(self.submit())
        cancel = self.client.post(f"/bookings/{reference}/cancel", data={"csrf_token": self.token(f"/bookings/{reference}/cancel")})
        self.assertEqual(cancel.status_code, 302)
        self.assertEqual(self.snap(reference).status, "cancelled")
        self.logout()
        self.login(email="prov@example.com")
        page = self.text(self.client.get(f"/provider/bookings/{reference}"))
        self.assertIn("cancelled this booking", page)
        self.assertNotIn("Accept</button>", page)


# =============================================================== access control
class ProviderAccessTests(ProviderActionTestCase):
    PAGES = ("/provider/dashboard", "/provider/bookings")

    def test_visitors_are_sent_to_login(self):
        self.logout()
        for url in (*self.PAGES, f"/provider/bookings/{self.reference}"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn("/login", self.location(response))
        response = self.act(self.reference, "accept", token_url="/login")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", self.location(response))
        self.assertEqual(self.snap(self.reference).status, "pending")

    def test_customers_and_admins_are_blocked(self):
        self.logout()
        self.make_user("boss@example.com", role=ROLE_ADMIN)
        for email in ("cust@example.com", "boss@example.com"):
            with self.subTest(email):
                self.login(email=email)
                for url in (*self.PAGES, f"/provider/bookings/{self.reference}"):
                    self.assertEqual(self.client.get(url).status_code, 403, url)
                for action in ("accept", "reject", "start", "complete"):
                    self.assertEqual(self.act(self.reference, action, token_url="/").status_code, 403, action)
                self.logout()
        self.assertEqual(self.snap(self.reference).status, "pending")

    def test_a_provider_can_open_their_pages_and_gets_a_jobs_link(self):
        for url in self.PAGES:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        home = self.text(self.client.get("/"))
        self.assertIn(">Jobs</a>", home)
        self.assertNotIn("My bookings", home)

    def test_customers_do_not_see_the_jobs_link(self):
        self.logout()
        self.login(email="cust@example.com")
        self.assertNotIn(">Jobs</a>", self.text(self.client.get("/")))

    def test_providers_cannot_use_the_customer_booking_pages(self):
        self.assertEqual(self.client.get("/bookings").status_code, 403)
        self.assertEqual(self.client.get(f"/bookings/{self.reference}").status_code, 403)

    def test_a_suspended_provider_is_logged_out(self):
        with self.app.app_context():
            db.session.get(User, self.provider_id).is_active = False
            db.session.commit()
        self.assertEqual(self.client.get("/provider/dashboard").status_code, 302)

    def test_provider_pages_are_not_cached(self):
        for url in (*self.PAGES, f"/provider/bookings/{self.reference}"):
            self.assertEqual(self.client.get(url).headers["Cache-Control"], "no-store", url)


# ================================================================= dashboard
class ProviderDashboardTests(ProviderTestCase):
    def setUp(self):
        super().setUp()
        self.provider_id = self.make_provider()
        self.make_user("cust@example.com")

    def stats(self, html):
        return {name: self.stat(html, name) for name in ("total", "pending", "accepted", "in_progress", "completed")}

    def test_a_provider_with_no_services_sees_an_honest_empty_dashboard(self):
        self.make_provider("lonely@example.com", services=())
        self.login(email="lonely@example.com")
        html = self.text(self.client.get("/provider/dashboard"))
        self.assertIn("No services linked to your account yet", html)
        self.assertIn("No requests are waiting for you.", html)
        self.assertEqual(set(self.stats(html).values()), {0})
        self.assertNotIn("FN-", html)

    def test_the_dashboard_lists_only_bookings_assigned_to_this_provider(self):
        mine = self.make_booking("cust@example.com")
        other_provider = self.make_provider("other@example.com", services=(OTHER_SLUG,))
        theirs = self.make_booking("cust@example.com", slug=OTHER_SLUG)
        unassigned = self.make_booking("cust@example.com", slug=THIRD_SLUG)
        self.assertEqual(self.snap(theirs).provider_id, other_provider)
        self.assertIsNone(self.snap(unassigned).provider_id)
        self.login(email="prov@example.com")
        for url in ("/provider/dashboard", "/provider/bookings"):
            html = self.text(self.client.get(url))
            self.assertIn(mine, html, url)
            self.assertNotIn(theirs, html, url)
            self.assertNotIn(unassigned, html, url)

    def test_statistics_come_from_the_database(self):
        statuses = ["pending", "accepted", "in_progress", "completed", "cancelled"]
        for index, status in enumerate(statuses):
            reference = self.make_booking("cust@example.com", slot=rules.TIME_SLOTS[index * 4])  # 2 hours apart
            if status != "pending":
                self.set_status(reference, status)
        self.login(email="prov@example.com")
        self.assertEqual(self.stats(self.text(self.client.get("/provider/dashboard"))),
                         {"total": 5, "pending": 1, "accepted": 1, "in_progress": 1, "completed": 1})

    def test_each_list_shows_the_right_buttons(self):
        pending = self.make_booking("cust@example.com", slot="08:00")
        accepted = self.make_booking("cust@example.com", slot="10:00")
        in_progress = self.make_booking("cust@example.com", slot="12:00")
        completed = self.make_booking("cust@example.com", slot="14:00")
        self.set_status(accepted, "accepted")
        self.set_status(in_progress, "in_progress")
        self.set_status(completed, "completed")
        self.login(email="prov@example.com")
        html = self.text(self.client.get("/provider/dashboard"))
        for reference, action in [(pending, "accept"), (pending, "reject"), (accepted, "start"), (in_progress, "complete")]:
            self.assertIn(f"/provider/bookings/{reference}/{action}", html, (reference, action))
        self.assertIn(completed, html)  # listed under "recently completed", without any action buttons
        self.assertNotIn(f"/provider/bookings/{completed}/", html)
        self.assertNotIn(f"/provider/bookings/{pending}/start", html)
        self.assertNotIn(f"/provider/bookings/{accepted}/accept", html)

    def test_the_assigned_provider_sees_the_customers_contact_details_but_not_their_email(self):
        reference = self.make_booking("cust@example.com")
        self.login(email="prov@example.com")
        html = self.text(self.client.get(f"/provider/bookings/{reference}"))
        for expected in ("Test User", "9876543210", "12 Main Road, Test Area", "The tap leaks badly."):
            self.assertIn(expected, html)
        self.assertNotIn("cust@example.com", html)

    def test_the_jobs_list_filters_by_status_and_ignores_unknown_filters(self):
        pending = self.make_booking("cust@example.com", slot="08:00")
        accepted = self.make_booking("cust@example.com", slot="12:00")
        self.set_status(accepted, "accepted")
        self.login(email="prov@example.com")
        only_accepted = self.text(self.client.get("/provider/bookings?status=accepted"))
        self.assertIn(accepted, only_accepted)
        self.assertNotIn(pending, only_accepted)
        everything = self.text(self.client.get("/provider/bookings?status=nonsense"))
        self.assertIn(pending, everything)
        self.assertIn(accepted, everything)
        self.assertIn("No completed jobs", self.text(self.client.get("/provider/bookings?status=completed")))

    def test_the_jobs_list_shows_the_soonest_appointment_first(self):
        late = self.make_booking("cust@example.com", slot="16:00")
        early = self.make_booking("cust@example.com", slot="08:00")
        self.login(email="prov@example.com")
        html = self.text(self.client.get("/provider/bookings"))
        self.assertLess(html.index(early), html.index(late))

    def test_the_empty_jobs_list_explains_itself(self):
        self.login(email="prov@example.com")
        self.assertIn("No jobs assigned to you yet", self.text(self.client.get("/provider/bookings")))

    def test_the_detail_page_offers_only_the_actions_that_make_sense(self):
        reference = self.make_booking("cust@example.com")
        self.login(email="prov@example.com")
        expected = {"pending": ("accept", "reject"), "accepted": ("start",), "in_progress": ("complete",), "completed": (), "rejected": (), "cancelled": ()}
        for status, actions in expected.items():
            with self.subTest(status):
                self.set_status(reference, status)
                html = self.text(self.client.get(f"/provider/bookings/{reference}"))
                for action in ("accept", "reject", "start", "complete"):
                    self.assertEqual(f"/provider/bookings/{reference}/{action}" in html, action in actions, (status, action))


# ================================================================== actions
class ProviderActionTests(ProviderActionTestCase):
    def test_accepting_a_pending_booking(self):
        response = self.act(self.reference, "accept")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.location(response), f"/provider/bookings/{self.reference}")
        self.assertEqual(self.snap(self.reference).status, "accepted")
        self.assertIn("Booking accepted.", self.follow(response))

    def test_rejecting_a_pending_booking_frees_the_time_for_a_new_request(self):
        response = self.act(self.reference, "reject")
        self.assertEqual(self.snap(self.reference).status, "rejected")
        self.assertIn("Booking rejected.", self.follow(response))
        self.logout()
        self.login(email="cust@example.com")
        page = self.text(self.client.get(f"/bookings/{self.reference}"))
        self.assertIn("was rejected", page)
        self.assertNotIn("Cancel this booking", page)
        new_reference = self.reference_from(self.submit())  # same service, date and time again
        self.assertEqual(self.snap(new_reference).provider_id, self.provider_id)

    def test_the_whole_workflow_accept_start_complete(self):
        for action, expected in [("accept", "accepted"), ("start", "in_progress"), ("complete", "completed")]:
            with self.subTest(action):
                response = self.act(self.reference, action)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(self.snap(self.reference).status, expected)
                self.assertIn(rules.PROVIDER_ACTION_MESSAGES[action], self.follow(response))
        self.assertEqual(self.stat(self.text(self.client.get("/provider/dashboard")), "completed"), 1)

    def test_the_customer_sees_each_step_and_the_provider_name(self):
        self.act(self.reference, "accept")
        self.act(self.reference, "start")
        self.logout()
        self.login(email="cust@example.com")
        page = self.text(self.client.get(f"/bookings/{self.reference}"))
        self.assertIn("In Progress", page)
        self.assertIn("is-done", page)
        self.assertIn("Pat Provider", page)
        self.assertNotIn("Cancel this booking", page)  # a job in progress cannot be cancelled
        self.logout()
        self.login(email="prov@example.com")
        self.act(self.reference, "complete")
        self.logout()
        self.login(email="cust@example.com")
        self.assertEqual(self.stat(self.text(self.client.get("/customer/dashboard")), "completed"), 1)

    def test_repeating_an_action_is_harmless(self):
        self.act(self.reference, "accept")
        response = self.act(self.reference, "accept")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.snap(self.reference).status, "accepted")
        self.assertIn("already accepted", self.follow(response))
        self.act(self.reference, "start")
        self.assertIn("already in progress", self.follow(self.act(self.reference, "start")))
        self.assertEqual(self.snap(self.reference).status, "in_progress")

    def test_invalid_transitions_are_refused_and_change_nothing(self):
        invalid = {
            "pending": ["start", "complete"],
            "accepted": ["reject", "complete"],
            "in_progress": ["accept", "reject"],
            "completed": ["accept", "reject", "start"],
            "rejected": ["accept", "start", "complete"],
            "cancelled": ["accept", "reject", "start", "complete"],
        }
        for status, actions in invalid.items():
            for action in actions:
                with self.subTest(f"{status} + {action}"):
                    self.set_status(self.reference, status)
                    response = self.act(self.reference, action)
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(self.snap(self.reference).status, status)
                    self.assertIn("cannot be changed to", self.follow(response))

    def test_pending_cannot_jump_straight_to_completed(self):
        self.act(self.reference, "complete")
        self.assertEqual(self.snap(self.reference).status, "pending")

    def test_unknown_actions_are_a_404_and_get_is_not_allowed(self):
        for action in ("cancel", "delete", "reopen", "ACCEPT", "accept%20", "../start"):
            self.assertEqual(self.act(self.reference, action).status_code, 404, action)
        self.assertEqual(self.client.get(f"/provider/bookings/{self.reference}/accept").status_code, 405)
        self.assertEqual(self.snap(self.reference).status, "pending")

    def test_a_customer_cancelling_in_the_meantime_blocks_the_provider(self):
        with self.app.app_context():
            db.session.scalar(select(Booking).where(Booking.reference == self.reference)).status = "cancelled"
            db.session.commit()
        response = self.act(self.reference, "accept")
        self.assertEqual(self.snap(self.reference).status, "cancelled")
        self.assertIn("cancelled booking cannot be changed to accepted", self.follow(response))

    def test_extra_form_fields_cannot_change_anything_else(self):
        other = self.make_provider("other@example.com", services=(OTHER_SLUG,))
        self.act(self.reference, "accept", status="completed", provider_id=str(other), price_from_at_booking="0", reference="FN-AAAA-BBBB")
        booking = self.snap(self.reference)
        self.assertEqual(booking.status, "accepted")
        self.assertEqual(booking.provider_id, self.provider_id)
        self.assertEqual(booking.price, 399)
        self.assertEqual(booking.reference, self.reference)


class ProviderCsrfTests(ProviderActionTestCase):
    def test_actions_without_a_csrf_token_are_refused(self):
        for action in ("accept", "reject", "start", "complete"):
            response = self.client.post(f"/provider/bookings/{self.reference}/{action}")
            self.assertEqual(response.status_code, 400, action)
            self.assertIn("could not be verified", self.text(response))
        self.assertEqual(self.snap(self.reference).status, "pending")

    def test_actions_with_a_wrong_token_are_refused(self):
        self.client.get("/provider/dashboard")
        response = self.client.post(f"/provider/bookings/{self.reference}/accept", data={"csrf_token": "forged"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.snap(self.reference).status, "pending")

    def test_a_token_from_another_visitor_does_not_work(self):
        stolen = self.token("/provider/dashboard")
        attacker = self.app.test_client()
        attacker.get("/login")
        response = attacker.post(f"/provider/bookings/{self.reference}/accept", data={"csrf_token": stolen})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.snap(self.reference).status, "pending")

    def test_every_action_button_sits_in_a_form_with_a_token(self):
        html = self.text(self.client.get(f"/provider/bookings/{self.reference}"))
        forms = re.findall(r'<form[^>]*provider/bookings/[^>]*>.*?</form>', html, re.S)
        self.assertEqual(len(forms), 2)  # accept and reject
        for form in forms:
            self.assertIn('name="csrf_token"', form)


# =============================================================== ownership
class ProviderOwnershipTests(ProviderTestCase):
    def setUp(self):
        super().setUp()
        self.p1 = self.make_provider("p1@example.com", services=(SLUG,), full_name="Provider One")
        self.p2 = self.make_provider("p2@example.com", services=(OTHER_SLUG,), full_name="Provider Two")
        self.make_user("cust@example.com")
        self.job1 = self.make_booking("cust@example.com", slug=SLUG)
        self.job2 = self.make_booking("cust@example.com", slug=OTHER_SLUG)
        self.unassigned = self.make_booking("cust@example.com", slug=THIRD_SLUG)
        self.assertEqual((self.snap(self.job1).provider_id, self.snap(self.job2).provider_id, self.snap(self.unassigned).provider_id), (self.p1, self.p2, None))
        self.login(email="p1@example.com")

    def test_a_provider_cannot_see_someone_elses_or_unassigned_bookings(self):
        for reference in (self.job2, self.unassigned):
            response = self.client.get(f"/provider/bookings/{reference}")
            self.assertEqual(response.status_code, 404, reference)
            self.assertNotIn("12 Main Road", self.text(response))
            self.assertNotIn(reference, self.text(response))

    def test_a_provider_cannot_act_on_someone_elses_or_unassigned_bookings(self):
        for reference in (self.job2, self.unassigned):
            for action in ("accept", "reject", "start", "complete"):
                with self.subTest((reference, action)):
                    self.assertEqual(self.act(reference, action).status_code, 404)
        self.assertEqual(self.snap(self.job2).status, "pending")
        self.assertEqual(self.snap(self.unassigned).status, "pending")
        self.assertEqual(self.snap(self.job2).provider_id, self.p2)

    def test_the_other_providers_booking_looks_exactly_like_a_missing_one(self):
        blank = lambda html: re.sub(r'(name="csrf_token" value=")[^"]+', r"\1X", html)
        real_but_not_mine = self.client.get(f"/provider/bookings/{self.job2}")
        made_up = self.client.get("/provider/bookings/FN-ZZZZ-ZZZZ")
        self.assertEqual(real_but_not_mine.status_code, made_up.status_code)
        self.assertEqual(blank(self.text(real_but_not_mine)), blank(self.text(made_up)))

    def test_each_provider_sees_only_their_own_job_on_the_dashboard(self):
        mine = self.text(self.client.get("/provider/dashboard"))
        self.assertIn(self.job1, mine)
        self.assertNotIn(self.job2, mine)
        self.logout()
        self.login(email="p2@example.com")
        theirs = self.text(self.client.get("/provider/dashboard"))
        self.assertIn(self.job2, theirs)
        self.assertNotIn(self.job1, theirs)

    def test_invalid_references_are_a_plain_404(self):
        from urllib.parse import quote

        for bad in ["abc", "FN-0000-0000", "FN-AAAA-BBBB' OR '1'='1", "../etc/passwd", "1", "<script>"]:
            response = self.client.get("/provider/bookings/" + quote(bad, safe=""))
            self.assertEqual(response.status_code, 404, bad)
            self.assertNotIn("Traceback", self.text(response))

    def test_the_service_layer_refuses_other_providers_bookings_too(self):
        with self.app.app_context():
            booking = db.session.scalar(select(Booking).where(Booking.reference == self.job2))
            p1 = db.session.get(User, self.p1)
            with self.assertRaises(BookingPermissionError):
                provider_bookings.perform_action(booking, p1, "accept")
            self.assertIsNone(provider_bookings.get_provider_booking(p1, self.job2))
            self.assertIsNone(provider_bookings.get_provider_booking(p1, self.unassigned))
            self.assertIsNotNone(provider_bookings.get_provider_booking(p1, self.job1.lower()))
        self.assertEqual(self.snap(self.job2).status, "pending")

    def test_only_providers_can_use_the_service_layer_actions(self):
        with self.app.app_context():
            booking = db.session.scalar(select(Booking).where(Booking.reference == self.job1))
            customer = accounts.get_user_by_email("cust@example.com")
            with self.assertRaises(BookingPermissionError):
                provider_bookings.perform_action(booking, customer, "accept")
            with self.assertRaises(BookingPermissionError):
                provider_bookings.perform_action(booking, None, "accept")
        self.assertEqual(self.snap(self.job1).status, "pending")


# ============================================================ accept conflicts
class AcceptConflictTests(ProviderTestCase):
    def setUp(self):
        super().setUp()
        self.provider_id = self.make_provider()
        self.make_user("cust@example.com")
        self.first = self.make_booking("cust@example.com", slot="10:00")  # assigned to the provider
        self.login(email="prov@example.com")

    def test_accepting_a_job_that_overlaps_an_accepted_one_is_refused(self):
        self.act(self.first, "accept")
        overlapping = self.raw_booking("cust@example.com", self.provider_id, slot="11:00")
        response = self.act(overlapping, "accept")
        self.assertEqual(self.snap(overlapping).status, "pending")
        self.assertIn("already have a job around that time", self.follow(response))

    def test_a_job_two_hours_later_can_be_accepted(self):
        self.act(self.first, "accept")
        later = self.raw_booking("cust@example.com", self.provider_id, slot="12:00")
        self.act(later, "accept")
        self.assertEqual(self.snap(later).status, "accepted")

    def test_a_job_on_another_day_can_be_accepted(self):
        self.act(self.first, "accept")
        other_day = self.raw_booking("cust@example.com", self.provider_id, slot="10:00", days=4)
        self.act(other_day, "accept")
        self.assertEqual(self.snap(other_day).status, "accepted")

    def test_an_in_progress_job_also_blocks(self):
        self.set_status(self.first, "in_progress")
        overlapping = self.raw_booking("cust@example.com", self.provider_id, slot="10:30")
        self.act(overlapping, "accept")
        self.assertEqual(self.snap(overlapping).status, "pending")

    def test_cancelled_rejected_or_completed_jobs_do_not_block(self):
        overlapping = self.raw_booking("cust@example.com", self.provider_id, slot="10:30")
        for status in ("cancelled", "rejected", "completed"):
            with self.subTest(status):
                self.set_status(self.first, status)
                self.act(overlapping, "accept")
                self.assertEqual(self.snap(overlapping).status, "accepted")
                self.set_status(overlapping, "pending")

    def test_two_pending_requests_cannot_both_be_accepted(self):
        overlapping = self.raw_booking("cust@example.com", self.provider_id, slot="11:00")
        self.act(self.first, "accept")  # fine: nothing committed yet
        self.act(overlapping, "accept")  # refused: the first one is committed now
        self.assertEqual(self.snap(self.first).status, "accepted")
        self.assertEqual(self.snap(overlapping).status, "pending")

    def test_another_providers_job_at_the_same_time_is_not_a_conflict(self):
        other = self.make_provider("other@example.com", services=(OTHER_SLUG,))
        theirs = self.raw_booking("cust@example.com", other, slug=OTHER_SLUG, slot="10:00")
        self.set_status(theirs, "accepted")
        self.act(self.first, "accept")
        self.assertEqual(self.snap(self.first).status, "accepted")

    def test_rejecting_and_starting_are_not_blocked_by_a_conflict(self):
        overlapping = self.raw_booking("cust@example.com", self.provider_id, slot="11:00")
        self.act(self.first, "accept")
        self.act(overlapping, "reject")
        self.assertEqual(self.snap(overlapping).status, "rejected")
        self.act(self.first, "start")
        self.assertEqual(self.snap(self.first).status, "in_progress")


# ===================================================== provider selection query
class ProviderSelectionQueryTests(ProviderTestCase):
    """Regression tests for choose_provider(), whose query once failed with
    "'ChunkedIteratorResult' object is not subscriptable" (dict() applied to a query result)."""

    def setUp(self):
        super().setUp()
        self.p1 = self.make_provider("p1@example.com", full_name="Provider One")
        for n in range(1, 4):
            self.make_user(f"c{n}@example.com")

    def choose(self, slug=SLUG, slot="10:00", days=3):
        with self.app.app_context():
            provider = scheduling.choose_provider(providers.get_service_by_slug(slug), self.day(days), rules.parse_time_slot(slot))
            return provider.id if provider else None

    def test_an_eligible_provider_is_selected(self):
        self.assertEqual(self.choose(), self.p1)  # runs the load query that used to crash

    def test_a_customer_booking_through_the_form_reaches_the_providers_jobs_list(self):
        self.login(email="c1@example.com")  # the account already exists (created in setUp)
        reference = self.reference_from(self.submit())  # this request used to crash
        self.assertEqual(self.snap(reference).provider_id, self.p1)
        self.logout()
        self.login(email="p1@example.com")
        self.assertIn(reference, self.text(self.client.get("/provider/bookings")))
        self.assertIn(reference, self.text(self.client.get("/provider/dashboard")))

    def test_a_provider_with_a_conflicting_booking_is_not_selected(self):
        # p1 has ONE job (10:00); p2 has TWO jobs that day, so p1 would normally be preferred.
        # If the conflict were ignored, p1 would win at 10:00. It must not.
        p2 = self.make_provider("p2@example.com", full_name="Provider Two")
        self.raw_booking("c1@example.com", self.p1, slot="10:00")
        self.raw_booking("c2@example.com", p2, slot="14:00")
        self.raw_booking("c3@example.com", p2, slot="16:00")
        self.assertEqual(self.choose(slot="10:00"), p2)  # p1 clashes (same time)
        self.assertEqual(self.choose(slot="11:00"), p2)  # p1 clashes (60 minutes apart)
        self.assertEqual(self.choose(slot="12:00"), self.p1)  # nobody clashes: fewest jobs wins (p1: 1, p2: 2)

    def test_a_provider_with_the_fewest_jobs_that_day_is_preferred_when_both_are_free(self):
        p2 = self.make_provider("p2@example.com", full_name="Provider Two")
        self.make_booking("c1@example.com", slot="08:00")  # p1
        self.assertEqual(self.choose(slot="14:00"), p2)  # both free, p2 has no jobs that day

    def test_no_provider_offers_the_service(self):
        self.assertIsNone(self.choose(slug=THIRD_SLUG))
        self.make_provider("p2@example.com", services=(OTHER_SLUG,))
        self.assertIsNone(self.choose(slug=THIRD_SLUG))

    def test_providers_exist_but_all_are_busy(self):
        self.make_booking("c1@example.com", slot="10:00")
        with self.app.app_context():
            with self.assertRaises(NoProviderAvailableError):
                scheduling.choose_provider(providers.get_service_by_slug(SLUG), self.day(), rules.parse_time_slot("10:30"))

    def test_the_load_query_returns_a_plain_dict_of_counts(self):
        p2 = self.make_provider("p2@example.com", full_name="Provider Two")
        first = self.make_booking("c1@example.com", slot="08:00")
        second = self.make_booking("c2@example.com", slot="14:00")
        third = self.make_booking("c3@example.com", slot="10:00", days=4)  # another day
        self.assertEqual(self.snap(first).provider_id, self.p1)
        self.assertEqual(self.snap(second).provider_id, p2)
        with self.app.app_context():
            counts = scheduling.active_job_counts([self.p1, p2], self.day())
            self.assertIsInstance(counts, dict)
            self.assertEqual(counts, {self.p1: 1, p2: 1})
            self.assertTrue(all(isinstance(count, int) for count in counts.values()))
            self.assertEqual(scheduling.active_job_counts([self.p1, p2], self.day(4)), {self.snap(third).provider_id: 1})
            self.assertEqual(scheduling.active_job_counts([self.p1, p2], self.day(9)), {})  # a day with no jobs
            self.assertEqual(scheduling.active_job_counts([], self.day()), {})  # nothing asked for

    def test_finished_bookings_are_not_counted_as_load(self):
        reference = self.make_booking("c1@example.com", slot="08:00")
        with self.app.app_context():
            self.assertEqual(scheduling.active_job_counts([self.p1], self.day()), {self.p1: 1})
        for status in ("cancelled", "rejected", "completed"):
            self.set_status(reference, status)
            with self.app.app_context():
                self.assertEqual(scheduling.active_job_counts([self.p1], self.day()), {}, status)


# ============================================ who sees and who can use the buttons
ACTIONS = ("accept", "reject", "start", "complete")
READY_STATUS = {"accept": "pending", "reject": "pending", "start": "accepted", "complete": "in_progress"}  # a status where the action WOULD be valid


class ProviderButtonPermissionTests(ProviderTestCase):
    """Regression tests: a customer must never see or use the provider-only buttons."""

    def setUp(self):
        super().setUp()
        self.p1 = self.make_provider("p1@example.com", services=(SLUG,), full_name="Provider One")
        self.p2 = self.make_provider("p2@example.com", services=(OTHER_SLUG,), full_name="Provider Two")
        self.make_user("cust@example.com")
        self.make_user("boss@example.com", role=ROLE_ADMIN)
        self.reference = self.make_booking("cust@example.com")
        self.assertEqual(self.snap(self.reference).provider_id, self.p1)

    def assert_cannot_act(self, email, action, expected_status=403):
        """Log in as email, try the action, and prove the booking did not change."""
        self.set_status(self.reference, READY_STATUS[action])
        self.login(email=email)
        response = self.act(self.reference, action, token_url="/")
        self.assertEqual(response.status_code, expected_status, f"{email} -> {action}")
        before = self.snap(self.reference)
        self.assertEqual(before.status, READY_STATUS[action], f"{email} changed the status with {action}")
        self.assertEqual(before.provider_id, self.p1)
        self.logout()

    # ---- 1. what customers SEE
    def test_customers_never_see_provider_buttons_on_any_customer_page(self):
        self.login(email="cust@example.com")
        for status in rules.STATUSES:
            self.set_status(self.reference, status)
            for url in (f"/bookings/{self.reference}", f"/bookings/{self.reference}/confirmation", "/bookings", "/customer/dashboard"):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, (status, url))  # the page really rendered
                html = self.text(response)
                self.assertEqual(self.action_names_in(html, self.reference), set(), (status, url))
                self.assertNotIn("/provider/", html, (status, url))
            self.assertIn(rules.STATUS_LABELS[status], self.text(self.client.get(f"/bookings/{self.reference}")))  # status is still shown

    def test_customers_keep_their_own_booking_view_and_cancellation(self):
        self.login(email="cust@example.com")
        html = self.text(self.client.get(f"/bookings/{self.reference}"))
        self.assertIn(self.reference, html)
        self.assertIn("Pending", html)
        self.assertIn(f"/bookings/{self.reference}/cancel", html)  # legitimate customer action stays

    # ---- 2. what customers can DO by sending requests directly
    def test_a_customer_cannot_accept_a_booking(self):
        self.assert_cannot_act("cust@example.com", "accept")

    def test_a_customer_cannot_reject_a_booking(self):
        self.assert_cannot_act("cust@example.com", "reject")

    def test_a_customer_cannot_start_a_job(self):
        self.assert_cannot_act("cust@example.com", "start")

    def test_a_customer_cannot_complete_a_job(self):
        self.assert_cannot_act("cust@example.com", "complete")

    def test_a_customer_cannot_open_the_provider_job_page(self):
        self.login(email="cust@example.com")
        for url in (f"/provider/bookings/{self.reference}", "/provider/bookings", "/provider/dashboard"):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_an_admin_cannot_use_the_provider_actions_either(self):
        for action in ACTIONS:
            self.assert_cannot_act("boss@example.com", action)

    # ---- visitors, other providers, invalid references
    def test_visitors_cannot_run_provider_actions(self):
        for action in ACTIONS:
            with self.subTest(action):
                self.set_status(self.reference, READY_STATUS[action])
                with_token = self.act(self.reference, action, token_url="/login")
                self.assertEqual(with_token.status_code, 302)
                self.assertIn("/login", self.location(with_token))
                self.assertEqual(self.client.post(f"/provider/bookings/{self.reference}/{action}").status_code, 400)  # no CSRF token
                self.assertEqual(self.snap(self.reference).status, READY_STATUS[action])

    def test_another_provider_cannot_manage_the_booking(self):
        self.login(email="p2@example.com")
        for action in ACTIONS:
            with self.subTest(action):
                self.set_status(self.reference, READY_STATUS[action])
                self.assertEqual(self.act(self.reference, action, token_url="/provider/dashboard").status_code, 404)
                self.assertEqual(self.snap(self.reference).status, READY_STATUS[action])
                self.assertEqual(self.snap(self.reference).provider_id, self.p1)
        self.assertEqual(self.client.get(f"/provider/bookings/{self.reference}").status_code, 404)
        for url in ("/provider/dashboard", "/provider/bookings"):
            self.assertEqual(self.action_names_in(self.text(self.client.get(url)), self.reference), set(), url)

    def test_invalid_references_return_404_for_provider_actions(self):
        from urllib.parse import quote

        self.login(email="p1@example.com")
        for bad in ("abc", "FN-0000-0000", "FN-ZZZZ-ZZZZ", "FN-AAAA-BBBB' OR '1'='1", "../etc/passwd", "1", "<script>"):
            for action in ACTIONS:
                response = self.act(quote(bad, safe=""), action, token_url="/provider/dashboard")
                self.assertEqual(response.status_code, 404, (bad, action))
        self.assertEqual(self.act(self.reference, "cancel", token_url="/provider/dashboard").status_code, 404)  # unknown action
        self.assertEqual(self.snap(self.reference).status, "pending")

    # ---- 3. the assigned provider keeps full use of the buttons
    def test_the_assigned_provider_still_sees_and_can_use_every_button(self):
        self.login(email="p1@example.com")
        detail = lambda: self.text(self.client.get(f"/provider/bookings/{self.reference}"))
        self.assertEqual(self.action_names_in(detail(), self.reference), {"accept", "reject"})
        self.assertEqual(self.act(self.reference, "accept").status_code, 302)
        self.assertEqual(self.snap(self.reference).status, "accepted")
        self.assertEqual(self.action_names_in(detail(), self.reference), {"start"})
        self.assertEqual(self.act(self.reference, "start").status_code, 302)
        self.assertEqual(self.snap(self.reference).status, "in_progress")
        self.assertEqual(self.action_names_in(detail(), self.reference), {"complete"})
        self.assertEqual(self.act(self.reference, "complete").status_code, 302)
        self.assertEqual(self.snap(self.reference).status, "completed")
        self.assertEqual(self.action_names_in(detail(), self.reference), set())

    # ---- 4. the template itself checks the viewer (defence in depth)
    def render_buttons(self, email=None):
        """Draw the action macro exactly as a template would, for the given logged-in user."""
        with self.app.test_request_context("/"):
            if email:
                login_user(accounts.get_user_by_email(email))
            booking = db.session.scalar(select(Booking).where(Booking.reference == self.reference))
            return render_template_string('{% from "partials/_provider_actions.html" import job_actions %}{{ job_actions(booking) }}', booking=booking)

    def test_the_action_macro_draws_buttons_only_for_the_assigned_provider(self):
        self.assertEqual(self.action_names_in(self.render_buttons("p1@example.com"), self.reference), {"accept", "reject"})
        for who in ("p2@example.com", "cust@example.com", "boss@example.com", None):
            with self.subTest(who):
                self.assertEqual(self.render_buttons(who).strip(), "")

    def test_can_manage_booking_rules(self):
        booking = SimpleNamespace(provider_id=7)
        user = lambda **kw: SimpleNamespace(**{"is_authenticated": True, "role": "provider", "is_active": True, "id": 7, **kw})
        self.assertTrue(can_manage_booking(user(), booking))
        self.assertFalse(can_manage_booking(user(id=8), booking))  # another provider
        self.assertFalse(can_manage_booking(user(role="customer"), booking))  # same id, wrong role
        self.assertFalse(can_manage_booking(user(role="admin"), booking))
        self.assertFalse(can_manage_booking(user(is_authenticated=False), booking))  # visitor
        self.assertFalse(can_manage_booking(user(is_active=False), booking))  # suspended
        self.assertFalse(can_manage_booking(user(), SimpleNamespace(provider_id=None)))  # unassigned booking
        self.assertFalse(can_manage_booking(None, booking))
        self.assertFalse(can_manage_booking(user(), None))


# ================================================================ admin CLI
class ProviderCommandTests(ProviderTestCase):
    def test_create_provider_links_services_and_hashes_the_password(self):
        result = self.run_command(self.app, "create-provider", "--email", "New.Prov@Example.com", "--name", "New Provider",
                                  "--service", SLUG, "--service", OTHER_SLUG, input_text=f"{PASSWORD}\n{PASSWORD}\n")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Provider created: new.prov@example.com", result.output)
        self.assertNotIn(PASSWORD, result.output)
        user = self.snapshot("new.prov@example.com")
        self.assertEqual(user.role, ROLE_PROVIDER)
        self.assertNotIn(PASSWORD, user.password_hash)
        with self.app.app_context():
            self.assertEqual([s.slug for s in providers.offered_services(providers.get_provider_by_email("new.prov@example.com"))], [SLUG, OTHER_SLUG])
        self.login(email="new.prov@example.com")
        self.assertEqual(self.client.get("/provider/dashboard").status_code, 200)

    def test_an_unknown_service_stops_everything_before_any_account_is_made(self):
        result = self.run_command(self.app, "create-provider", "--email", "p@example.com", "--name", "New Provider",
                                  "--service", SLUG, "--service", "no-such-service", input_text=f"{PASSWORD}\n{PASSWORD}\n")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("no-such-service", result.output)
        self.assertIsNone(self.snapshot("p@example.com"))

    def test_weak_passwords_and_duplicate_emails_are_refused(self):
        weak = self.run_command(self.app, "create-provider", "--email", "p@example.com", "--name", "New Provider", input_text="short\nshort\n")
        self.assertNotEqual(weak.exit_code, 0)
        self.assertIsNone(self.snapshot("p@example.com"))
        self.make_user("taken@example.com")
        before = self.snapshot("taken@example.com")
        duplicate = self.run_command(self.app, "create-provider", "--email", "taken@example.com", "--name", "New Provider", input_text=f"{PASSWORD}\n{PASSWORD}\n")
        self.assertNotEqual(duplicate.exit_code, 0)
        self.assertIn("already exists", duplicate.output)
        self.assertEqual(self.snapshot("taken@example.com").role, before.role)

    def test_the_provider_commands_explain_a_missing_table(self):
        empty = create_app(make_config(self.tmpdir / "empty.db"))
        self.addCleanup(self.dispose, empty)
        for args in (("create-provider", "--email", "p@example.com", "--name", "New Provider"), ("provider-services", "--email", "p@example.com"), ("assign-pending",)):
            result = self.run_command(empty, *args, input_text=f"{PASSWORD}\n{PASSWORD}\n")
            self.assertNotEqual(result.exit_code, 0, args)
            self.assertIn("db upgrade", result.output)

    def test_provider_services_adds_removes_and_lists(self):
        self.make_provider(services=())
        added = self.run_command(self.app, "provider-services", "--email", "prov@example.com", "--add", SLUG, "--add", OTHER_SLUG)
        self.assertEqual(added.exit_code, 0, added.output)
        self.assertIn(f"Added: {SLUG}", added.output)
        again = self.run_command(self.app, "provider-services", "--email", "prov@example.com", "--add", SLUG)
        self.assertIn(f"Already offered: {SLUG}", again.output)
        removed = self.run_command(self.app, "provider-services", "--email", "prov@example.com", "--remove", OTHER_SLUG)
        self.assertIn(f"Removed: {OTHER_SLUG}", removed.output)
        listing = self.run_command(self.app, "provider-services", "--email", "prov@example.com")
        self.assertIn(f"  {SLUG}", listing.output)
        self.assertNotIn(OTHER_SLUG, listing.output)

    def test_provider_services_refuses_unknown_services_and_non_providers(self):
        self.make_provider(services=())
        self.make_user("cust@example.com")
        bad_service = self.run_command(self.app, "provider-services", "--email", "prov@example.com", "--add", SLUG, "--add", "nope")
        self.assertNotEqual(bad_service.exit_code, 0)
        with self.app.app_context():
            self.assertEqual(providers.offered_services(providers.get_provider_by_email("prov@example.com")), [])  # nothing changed
        for email in ("cust@example.com", "nobody@example.com"):
            result = self.run_command(self.app, "provider-services", "--email", email, "--add", SLUG)
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("No provider account", result.output)

    def test_assign_pending_gives_providers_to_waiting_bookings_once(self):
        self.make_user("cust@example.com")
        waiting = self.make_booking("cust@example.com")
        self.assertIsNone(self.snap(waiting).provider_id)
        provider_id = self.make_provider()
        first = self.run_command(self.app, "assign-pending")
        self.assertEqual(first.exit_code, 0, first.output)
        self.assertIn(f"{waiting} -> prov@example.com", first.output)
        self.assertIn("Assigned: 1. Still unassigned: 0.", first.output)
        self.assertEqual(self.snap(waiting).provider_id, provider_id)
        second = self.run_command(self.app, "assign-pending")
        self.assertIn("Assigned: 0. Still unassigned: 0.", second.output)


# ====================================================== customers still work
class CustomerFunctionalityPreservedTests(ProviderTestCase):
    def test_the_customer_journey_works_with_providers_in_the_system(self):
        self.make_provider()
        self.customer("c1@example.com")
        reference = self.reference_from(self.submit())
        self.assertIn(reference, self.text(self.client.get("/bookings")))
        self.assertEqual(self.stat(self.text(self.client.get("/customer/dashboard")), "pending"), 1)
        self.logout()
        self.login(email="prov@example.com")
        self.act(reference, "accept")
        self.logout()
        self.login(email="c1@example.com")
        self.assertEqual(self.stat(self.text(self.client.get("/customer/dashboard")), "accepted"), 1)
        cancel = self.client.post(f"/bookings/{reference}/cancel", data={"csrf_token": self.token(f"/bookings/{reference}/cancel")})
        self.assertEqual(cancel.status_code, 302)
        self.assertEqual(self.snap(reference).status, "cancelled")

    def test_customers_cannot_use_provider_pages_and_public_pages_still_work(self):
        self.customer("c1@example.com")
        for url in ("/provider/dashboard", "/provider/bookings"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        for url in ("/", "/services", "/services?q=leak", f"/services/{SLUG}", "/about", "/contact", "/customer/dashboard", "/bookings"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_a_broken_database_shows_a_safe_page_to_providers(self):
        self.make_provider()
        self.login(email="prov@example.com")
        with self.app.app_context():
            Booking.__table__.drop(db.engine)
        with self.assertLogs(self.app.logger, level="ERROR"):
            response = self.client.get("/provider/dashboard")
        body = self.text(response)
        self.assertEqual(response.status_code, 500)
        self.assertIn("Something went wrong", body)
        for secret in ("OperationalError", "no such table", "Traceback", "SELECT"):
            self.assertNotIn(secret, body)


if __name__ == "__main__":
    import unittest

    unittest.main()
