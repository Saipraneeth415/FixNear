"""Pure-Python tests for the booking rules (no database needed):
    python -m unittest tests.test_booking_rules -v
"""
import unittest
from datetime import date, datetime, time, timedelta

from services import booking_rules as rules

NOW = datetime(2026, 10, 12, 10, 0)  # a Monday, 10:00


class StatusWorkflowTests(unittest.TestCase):
    def test_every_status_has_a_label_and_a_transition_entry(self):
        for status in rules.STATUSES:
            self.assertIn(status, rules.STATUS_LABELS)
            self.assertIn(status, rules.TRANSITIONS)
        self.assertEqual(rules.STATUS_LABELS[rules.STATUS_IN_PROGRESS], "In Progress")

    def test_the_normal_path_is_allowed(self):
        path = [rules.STATUS_PENDING, rules.STATUS_ACCEPTED, rules.STATUS_IN_PROGRESS, rules.STATUS_COMPLETED]
        for current, new in zip(path, path[1:]):
            self.assertTrue(rules.can_transition(current, new), f"{current} -> {new}")

    def test_pending_cannot_jump_to_completed_or_in_progress(self):
        self.assertFalse(rules.can_transition("pending", "completed"))
        self.assertFalse(rules.can_transition("pending", "in_progress"))
        self.assertFalse(rules.can_transition("accepted", "completed"))

    def test_no_going_backwards(self):
        for current, new in [("completed", "pending"), ("accepted", "pending"), ("in_progress", "accepted"), ("cancelled", "pending")]:
            self.assertFalse(rules.can_transition(current, new), f"{current} -> {new}")

    def test_final_statuses_have_no_way_out(self):
        for final in ("completed", "rejected", "cancelled"):
            self.assertEqual(rules.allowed_transitions(final), ())
            for other in rules.STATUSES:
                self.assertFalse(rules.can_transition(final, other))

    def test_a_status_cannot_change_to_itself_or_to_an_unknown_value(self):
        self.assertFalse(rules.can_transition("pending", "pending"))
        self.assertFalse(rules.can_transition("pending", "refunded"))
        self.assertFalse(rules.can_transition("nonsense", "pending"))

    def test_rejection_is_only_possible_from_pending(self):
        self.assertTrue(rules.can_transition("pending", "rejected"))
        self.assertFalse(rules.can_transition("accepted", "rejected"))

    def test_active_statuses(self):
        self.assertEqual(set(rules.ACTIVE_STATUSES), {"pending", "accepted", "in_progress"})


class CancellationRuleTests(unittest.TestCase):
    soon = NOW + timedelta(hours=5)
    far = NOW + timedelta(days=5)

    def block(self, status, start):
        return rules.cancellation_block_reason(status, start, NOW)

    def test_pending_can_always_be_cancelled(self):
        self.assertIsNone(self.block("pending", self.soon))
        self.assertIsNone(self.block("pending", self.far))

    def test_accepted_needs_24_hours_notice(self):
        self.assertIsNone(self.block("accepted", self.far))
        self.assertIsNone(self.block("accepted", NOW + timedelta(hours=24)))  # exactly 24h is allowed
        self.assertIn("24 hours", self.block("accepted", NOW + timedelta(hours=23, minutes=59)))
        self.assertIn("24 hours", self.block("accepted", self.soon))

    def test_other_statuses_cannot_be_cancelled(self):
        for status, words in [("completed", "Completed"), ("rejected", "Rejected"), ("in_progress", "in progress"), ("cancelled", "already been cancelled")]:
            self.assertIn(words, self.block(status, self.far), status)

    def test_unknown_status_cannot_be_cancelled(self):
        self.assertIsNotNone(self.block("nonsense", self.far))


class AppointmentTests(unittest.TestCase):
    today = NOW.date()

    def test_past_date_is_rejected(self):
        self.assertIn("past", rules.date_problem(self.today - timedelta(days=1), NOW))

    def test_today_and_future_dates_are_fine(self):
        self.assertIsNone(rules.date_problem(self.today, NOW))
        self.assertIsNone(rules.date_problem(self.today + timedelta(days=30), NOW))

    def test_too_far_ahead_is_rejected(self):
        self.assertIsNone(rules.date_problem(self.today + timedelta(days=rules.MAX_DAYS_AHEAD), NOW))
        self.assertIn("within the next", rules.date_problem(self.today + timedelta(days=rules.MAX_DAYS_AHEAD + 1), NOW))

    def test_missing_date(self):
        self.assertIn("Choose a date", rules.date_problem(None, NOW))

    def test_only_listed_time_slots_are_valid(self):
        self.assertEqual(rules.parse_time_slot("09:30"), time(9, 30))
        for bad in ["", "9:30", "09:15", "25:00", "07:30", "20:00", "noon", None, 930, "09:30 "]:
            self.assertIsNone(rules.parse_time_slot(bad), repr(bad))
            self.assertIn("Choose a time", rules.time_problem(self.today + timedelta(days=1), bad, NOW))

    def test_time_earlier_today_is_rejected(self):
        self.assertIn("already passed", rules.time_problem(self.today, "09:30", NOW))
        self.assertIn("already passed", rules.time_problem(self.today, "10:00", NOW))  # not later than now
        self.assertIsNone(rules.time_problem(self.today, "10:30", NOW))

    def test_any_slot_is_fine_on_a_future_day(self):
        self.assertIsNone(rules.time_problem(self.today + timedelta(days=1), "08:00", NOW))

    def test_combined_problem_list(self):
        self.assertEqual(rules.appointment_problems(self.today + timedelta(days=2), "10:00", NOW), [])
        self.assertEqual(len(rules.appointment_problems(self.today - timedelta(days=2), "bad", NOW)), 2)

    def test_time_slot_choices(self):
        choices = rules.time_slot_choices()
        self.assertEqual(choices[0], ("", "Select a time"))
        self.assertEqual(choices[1], ("08:00", "8:00 AM"))
        self.assertIn(("12:00", "12:00 PM"), choices)
        self.assertEqual(choices[-1], ("19:30", "7:30 PM"))
        self.assertEqual(len(choices), 1 + 24)

    def test_local_now_applies_the_offset(self):
        utc = rules.local_now(0)
        india = rules.local_now(330)
        self.assertAlmostEqual((india - utc).total_seconds(), 330 * 60, delta=5)
        self.assertIsNone(india.tzinfo)


class PhoneTests(unittest.TestCase):
    def test_valid_numbers_are_normalised(self):
        for raw, expected in [("98765 43210", "9876543210"), ("+91 98765-43210", "+919876543210"), ("(080) 1234 5678", "08012345678"), ("  9876543210 ", "9876543210")]:
            self.assertEqual(rules.normalize_phone(raw), expected, raw)

    def test_invalid_numbers_are_rejected(self):
        for raw in ["", "   ", "abc", "98765abcde", "12345", "9" * 16, "+", "98765 43210 ext 5", "++919876543210", None, 9876543210, "<script>1234567890"]:
            self.assertIsNone(rules.normalize_phone(raw), repr(raw))


class TextCleaningTests(unittest.TestCase):
    def test_line_cleaning(self):
        self.assertEqual(rules.clean_line("  Jane    Q  Doe "), "Jane Q Doe")
        self.assertEqual(rules.clean_line(None), "")

    def test_multiline_cleaning_keeps_paragraphs_and_drops_control_characters(self):
        self.assertEqual(rules.clean_multiline("  Line one\r\nLine two\x00\x07  "), "Line one\nLine two")
        self.assertEqual(rules.clean_multiline(None), "")


class ReferenceTests(unittest.TestCase):
    def test_format(self):
        for _ in range(200):
            reference = rules.generate_reference()
            self.assertTrue(rules.is_valid_reference(reference), reference)

    def test_no_confusing_characters(self):
        for char in "0O1IL":
            self.assertNotIn(char, rules.REFERENCE_ALPHABET)
        self.assertEqual(len(rules.REFERENCE_ALPHABET), 31)
        for _ in range(200):
            self.assertFalse(set(rules.generate_reference()[3:].replace("-", "")) & set("0O1IL"))

    def test_references_are_random_and_not_sequential(self):
        batch = [rules.generate_reference() for _ in range(2000)]
        self.assertEqual(len(set(batch)), len(batch))
        self.assertNotEqual(batch, sorted(batch))

    def test_invalid_references_are_recognised(self):
        for bad in ["", "FN-AAAA-BBB", "FN-AAAA-BBBBB", "fn-aaaa-bbbb", "FN-0000-1111", "XX-AAAA-BBBB", "FN-AAAA-BBBB' OR '1'='1", "../etc/passwd", None, 12, "FN-AAAA-BBBB\n"]:
            self.assertFalse(rules.is_valid_reference(bad), repr(bad))


class TrackingStepTests(unittest.TestCase):
    def test_pending(self):
        self.assertEqual(rules.tracking_steps("pending"), [("Pending", "current"), ("Accepted", "upcoming"), ("In Progress", "upcoming"), ("Completed", "upcoming")])

    def test_in_progress(self):
        states = [state for _, state in rules.tracking_steps("in_progress")]
        self.assertEqual(states, ["done", "done", "current", "upcoming"])

    def test_completed_is_all_done(self):
        self.assertEqual({state for _, state in rules.tracking_steps("completed")}, {"done"})

    def test_rejected_and_cancelled_have_no_steps(self):
        self.assertIsNone(rules.tracking_steps("rejected"))
        self.assertIsNone(rules.tracking_steps("cancelled"))


class ProviderRuleTests(unittest.TestCase):
    def test_every_provider_action_leads_to_a_status_the_workflow_allows(self):
        reachable = {target for source in rules.STATUSES for target in rules.allowed_transitions(source)}
        for action, target in rules.PROVIDER_ACTIONS.items():
            self.assertIn(target, reachable, action)
            self.assertIn(action, rules.PROVIDER_ACTION_LABELS)
            self.assertIn(action, rules.PROVIDER_ACTION_MESSAGES)
        self.assertEqual(set(rules.PROVIDER_ACTION_ORDER), set(rules.PROVIDER_ACTIONS))

    def test_actions_offered_for_each_status(self):
        self.assertEqual(rules.provider_actions_for("pending"), ["accept", "reject"])
        self.assertEqual(rules.provider_actions_for("accepted"), ["start"])
        self.assertEqual(rules.provider_actions_for("in_progress"), ["complete"])
        for final in ("completed", "rejected", "cancelled"):
            self.assertEqual(rules.provider_actions_for(final), [], final)
        self.assertEqual(rules.provider_actions_for("nonsense"), [])

    def test_a_provider_cannot_cancel_or_skip_steps(self):
        self.assertNotIn("cancel", rules.PROVIDER_ACTIONS)
        self.assertNotIn("complete", rules.provider_actions_for("pending"))
        self.assertNotIn("complete", rules.provider_actions_for("accepted"))
        self.assertNotIn("start", rules.provider_actions_for("pending"))

    def test_jobs_closer_than_two_hours_conflict(self):
        self.assertTrue(rules.times_conflict(time(10, 0), time(10, 0)))
        self.assertTrue(rules.times_conflict(time(10, 0), time(11, 30)))
        self.assertTrue(rules.times_conflict(time(11, 30), time(10, 0)))
        self.assertTrue(rules.times_conflict(time(10, 0), time(11, 59)))

    def test_jobs_at_least_two_hours_apart_do_not_conflict(self):
        self.assertFalse(rules.times_conflict(time(10, 0), time(12, 0)))
        self.assertFalse(rules.times_conflict(time(12, 0), time(10, 0)))
        self.assertFalse(rules.times_conflict(time(8, 0), time(19, 30)))

    def test_committed_statuses(self):
        self.assertEqual(set(rules.COMMITTED_STATUSES), {"accepted", "in_progress"})
        self.assertTrue(set(rules.COMMITTED_STATUSES) <= set(rules.ACTIVE_STATUSES))


if __name__ == "__main__":
    unittest.main()
