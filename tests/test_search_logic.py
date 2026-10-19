"""Pure-Python tests for the search rules and the sample data.

These need only the standard library, so they can run before any database
package is installed:
    python -m unittest tests.test_search_logic -v
"""
import unittest

from services import sample_data
from services.search import matches_terms, tokenize


class TokenizeTests(unittest.TestCase):
    def test_lowercases_and_splits_on_punctuation(self):
        self.assertEqual(tokenize("AC & Repair!"), ["ac", "repair"])

    def test_empty_and_none(self):
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize(None), [])

    def test_punctuation_only_has_no_words(self):
        self.assertEqual(tokenize("!!! ???"), [])


class MatchTests(unittest.TestCase):
    words = tokenize("Leak Detection & Pipe Repair for plumbing")

    def test_prefix_match(self):
        self.assertTrue(matches_terms(self.words, ["plumb"]))

    def test_middle_of_word_does_not_match(self):
        self.assertFalse(matches_terms(self.words, ["umbing"]))

    def test_all_terms_must_match(self):
        self.assertTrue(matches_terms(self.words, ["leak", "pipe"]))
        self.assertFalse(matches_terms(self.words, ["leak", "laptop"]))


class SampleDataTests(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(len(sample_data.CATEGORIES), 6)
        self.assertEqual(len(sample_data.SERVICES), 12)

    def test_slugs_are_unique(self):
        slugs = [s.slug for s in sample_data.SERVICES]
        self.assertEqual(len(slugs), len(set(slugs)))

    def test_every_service_points_to_a_real_category(self):
        category_slugs = {c.slug for c in sample_data.CATEGORIES}
        for service in sample_data.SERVICES:
            self.assertIn(service.category_slug, category_slugs)

    def test_every_provider_is_labelled_sample(self):
        for service in sample_data.SERVICES:
            self.assertIn("Sample", service.provider_name)

    def test_no_negative_prices(self):
        for service in sample_data.SERVICES:
            self.assertGreaterEqual(service.price_from, 0)


if __name__ == "__main__":
    unittest.main()
