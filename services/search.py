"""Search matching rules. Pure Python: no database or Flask imports."""
import re


def tokenize(text):
    """Lower-case alphanumeric words, e.g. 'AC & Repair!' -> ['ac', 'repair']."""
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def matches_terms(words, terms):
    """True if every search term matches the START of at least one word.

    So 'plumb' finds 'plumbing', and 'laptop cleaning' needs both words.
    """
    return all(any(word.startswith(term) for word in words) for term in terms)
