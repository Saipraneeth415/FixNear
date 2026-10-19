"""Small security helpers. Pure Python: no database or Flask imports."""
from urllib.parse import urlsplit


def normalize_email(value):
    """Emails are stored lower-case and trimmed so 'A@x.com' and 'a@x.com' are one account."""
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def safe_redirect_target(target, default="/"):
    """Return target only if it is a path on THIS site; otherwise return default.

    This stops "open redirect" attacks, where a crafted login link such as
    /login?next=https://evil.example sends the user to another website.
    Only paths that start with a single "/" are allowed.
    """
    if not target or not isinstance(target, str):
        return default
    if any(ord(char) < 32 or ord(char) == 127 for char in target):  # control characters
        return default
    if "\\" in target:  # some browsers treat \ like /
        return default
    if not target.startswith("/") or target.startswith("//"):
        return default
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return default
    return target
