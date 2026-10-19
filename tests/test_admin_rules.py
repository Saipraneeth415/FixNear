"""Pure-Python tests for the admin rules (no database needed):
    python -m unittest tests.test_admin_rules -v
"""
import unittest

from services import admin_rules as rules
from services.icons import ICON_NAMES, _ICONS


class PaginationTests(unittest.TestCase):
    def test_parse_page_accepts_only_positive_whole_numbers(self):
        for good, expected in [("1", 1), ("7", 7), (" 3 ", 3), (4, 4)]:
            self.assertEqual(rules.parse_page(good), expected)
        for bad in [None, "", "abc", "0", "-5", "2.5", "1; DROP TABLE users", [], "\u096f", "9" * 5000]:
            self.assertEqual(rules.parse_page(bad), 1, repr(bad))

    def test_first_page_of_many(self):
        info = rules.paginate(45, 1, 20)
        self.assertEqual((info["page"], info["pages"], info["offset"], info["first"], info["last"]), (1, 3, 0, 1, 20))
        self.assertFalse(info["has_prev"])
        self.assertTrue(info["has_next"])

    def test_last_page_is_partial(self):
        info = rules.paginate(45, 3, 20)
        self.assertEqual((info["offset"], info["first"], info["last"]), (40, 41, 45))
        self.assertTrue(info["has_prev"])
        self.assertFalse(info["has_next"])

    def test_exact_multiple_has_no_extra_page(self):
        self.assertEqual(rules.paginate(40, 1, 20)["pages"], 2)

    def test_out_of_range_pages_are_clamped(self):
        self.assertEqual(rules.paginate(45, 99, 20)["page"], 3)
        self.assertEqual(rules.paginate(45, 0, 20)["page"], 1)
        self.assertEqual(rules.paginate(45, -4, 20)["page"], 1)

    def test_an_empty_list_is_one_empty_page(self):
        info = rules.paginate(0, 1, 20)
        self.assertEqual((info["pages"], info["offset"], info["first"], info["last"], info["total"]), (1, 0, 0, 0, 0))
        self.assertFalse(info["has_prev"] or info["has_next"])


class SlugTests(unittest.TestCase):
    def test_valid_slugs(self):
        for slug in ["plumbing", "ac-repair", "leak-detection-pipe-repair", "a1", "x", "gen-2-fix"]:
            self.assertTrue(rules.is_valid_slug(slug), slug)

    def test_invalid_slugs(self):
        for slug in ["", "Plumbing", "has space", "-lead", "trail-", "double--hyphen", "under_score", "slash/slash", "dot.dot", "../x",
                     "emoji\u2728", "a" * 101, None, 5, "tab\there", "new\nline", "x\n"]:
            self.assertFalse(rules.is_valid_slug(slug), repr(slug))


class IncludesTests(unittest.TestCase):
    def test_one_item_per_line(self):
        self.assertEqual(rules.parse_includes("  Inspection \r\n\r\n Repair   of  pipes\nClean-up  "), ["Inspection", "Repair of pipes", "Clean-up"])

    def test_empty_and_non_text(self):
        self.assertEqual(rules.parse_includes(""), [])
        self.assertEqual(rules.parse_includes("   \n \n"), [])
        self.assertEqual(rules.parse_includes(None), [])

    def test_limits(self):
        self.assertIsNone(rules.includes_problem(["a"] * rules.MAX_INCLUDES))
        self.assertIn("at most", rules.includes_problem(["a"] * (rules.MAX_INCLUDES + 1)))
        self.assertIn("under", rules.includes_problem(["x" * (rules.MAX_INCLUDE_LENGTH + 1)]))


class UserStatusRuleTests(unittest.TestCase):
    def problem(self, **kw):
        values = dict(actor_id=1, target_id=2, target_role="customer", target_is_active=True, new_is_active=False, other_active_admins=1)
        values.update(kw)
        return rules.user_status_problem(**values)

    def test_deactivating_another_user_is_allowed(self):
        for role in ("customer", "provider", "admin"):
            self.assertIsNone(self.problem(target_role=role, other_active_admins=1), role)

    def test_reactivating_a_deactivated_user_is_allowed(self):
        self.assertIsNone(self.problem(target_is_active=False, new_is_active=True))

    def test_nobody_can_deactivate_themselves(self):
        self.assertIn("own account", self.problem(actor_id=5, target_id=5, target_role="admin", other_active_admins=3))

    def test_the_last_active_admin_cannot_be_deactivated(self):
        self.assertIn("At least one active administrator", self.problem(target_role="admin", other_active_admins=0))

    def test_other_admins_may_be_deactivated_while_one_remains(self):
        self.assertIsNone(self.problem(target_role="admin", other_active_admins=1))

    def test_a_no_op_is_reported(self):
        self.assertIn("already active", self.problem(target_is_active=True, new_is_active=True))
        self.assertIn("already deactivated", self.problem(target_is_active=False, new_is_active=False))

    def test_the_admin_rule_does_not_block_non_admins(self):
        self.assertIsNone(self.problem(target_role="provider", other_active_admins=0))


class IconTests(unittest.TestCase):
    def test_every_offered_icon_exists(self):
        for name in ICON_NAMES:
            self.assertIn(name, _ICONS, name)


if __name__ == "__main__":
    unittest.main()
