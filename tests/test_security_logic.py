"""Pure-Python tests for password rules, hashing, email cleanup and safe redirects.

They need only Flask's own dependency (Werkzeug), so they run even before the
database and login packages are installed:
    python -m unittest tests.test_security_logic -v
"""
import unittest

from services.passwords import MAX_PASSWORD_LENGTH, hash_password, password_problems, verify_password
from services.security import normalize_email, safe_redirect_target


class PasswordRuleTests(unittest.TestCase):
    def test_a_good_password_has_no_problems(self):
        self.assertEqual(password_problems("Correct-Horse-9"), [])

    def test_too_short(self):
        self.assertTrue(any("at least 10" in p for p in password_problems("Short1a")))

    def test_too_long(self):
        self.assertTrue(any("no more than" in p for p in password_problems("a1" * MAX_PASSWORD_LENGTH)))

    def test_needs_a_letter_and_a_number(self):
        self.assertTrue(any("letter and one number" in p for p in password_problems("onlyletterspassword")))
        self.assertTrue(any("letter and one number" in p for p in password_problems("12345678901234")))

    def test_common_passwords_are_rejected_in_any_case(self):
        self.assertTrue(any("too common" in p for p in password_problems("Password123")))

    def test_password_may_not_be_the_email_or_the_name(self):
        self.assertTrue(any("email" in p for p in password_problems("me.myself9@example.com", email="Me.Myself9@example.com")))
        self.assertTrue(any("name" in p for p in password_problems("Jane Q Public 1", full_name="jane  q public 1")))

    def test_non_strings_are_rejected(self):
        self.assertTrue(password_problems(None))


class HashingTests(unittest.TestCase):
    def test_hash_is_not_the_password(self):
        hashed = hash_password("Correct-Horse-9")
        self.assertNotEqual(hashed, "Correct-Horse-9")
        self.assertNotIn("Correct-Horse-9", hashed)
        self.assertTrue(hashed.startswith(("scrypt:", "pbkdf2:")))

    def test_correct_and_wrong_passwords(self):
        hashed = hash_password("Correct-Horse-9")
        self.assertTrue(verify_password(hashed, "Correct-Horse-9"))
        self.assertFalse(verify_password(hashed, "correct-horse-9"))
        self.assertFalse(verify_password(hashed, ""))

    def test_same_password_gives_different_hashes_because_of_salt(self):
        self.assertNotEqual(hash_password("Correct-Horse-9"), hash_password("Correct-Horse-9"))

    def test_garbage_hash_never_matches(self):
        self.assertFalse(verify_password("not-a-hash", "anything"))
        self.assertFalse(verify_password("", "anything"))
        self.assertFalse(verify_password(None, "anything"))


class EmailNormalisationTests(unittest.TestCase):
    def test_trims_and_lowercases(self):
        self.assertEqual(normalize_email("  Jane.Doe@Example.COM "), "jane.doe@example.com")

    def test_non_strings_become_empty(self):
        self.assertEqual(normalize_email(None), "")


class SafeRedirectTests(unittest.TestCase):
    def test_local_paths_are_allowed(self):
        for target in ["/", "/customer/dashboard", "/services?q=tap&category=plumbing", "/services/leak-detection-pipe-repair"]:
            self.assertEqual(safe_redirect_target(target, "/home"), target)

    def test_other_sites_are_rejected(self):
        for target in [
            "https://evil.example", "http://evil.example/path", "//evil.example", "///evil.example",
            "/\\evil.example", "\\\\evil.example", "javascript:alert(1)", "data:text/html,hi",
            "evil.example", "customer/dashboard", " /customer/dashboard", "/ok\r\nSet-Cookie: a=b", "/ok\x00",
        ]:
            self.assertEqual(safe_redirect_target(target, "/home"), "/home", repr(target))

    def test_empty_and_missing_values_use_the_default(self):
        for target in [None, "", 0, ["/x"]]:
            self.assertEqual(safe_redirect_target(target, "/home"), "/home")


if __name__ == "__main__":
    unittest.main()
