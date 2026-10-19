"""Rules for the admin area, in plain Python (no database or Flask imports).

Keeping them here means they can be tested on their own and reused by the
services, the forms and the templates.
"""
import re

SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_INCLUDES = 10
MAX_INCLUDE_LENGTH = 150
PAGE_SIZE = 20


# ---------------------------------------------------------------- pagination
def parse_page(value):
    """A page number from the address bar: anything that is not a positive whole number becomes 1."""
    text = str(value).strip() if value is not None else ""
    if not (text.isascii() and text.isdigit()):  # plain 0-9 only (no signs, decimals or other scripts)
        return 1
    try:
        page = int(text)
    except ValueError:  # an absurdly long number
        return 1
    return page if page >= 1 else 1


def paginate(total, page, per_page=PAGE_SIZE):
    """Work out which slice of a list to show. Pages outside the range are clamped, never an error."""
    total = max(int(total), 0)
    per_page = max(int(per_page), 1)
    pages = max((total + per_page - 1) // per_page, 1)
    page = min(max(int(page), 1), pages)
    offset = (page - 1) * per_page
    return {
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "total": total,
        "offset": offset,
        "has_prev": page > 1,
        "has_next": page < pages,
        "first": offset + 1 if total else 0,
        "last": min(offset + per_page, total),
    }


# ----------------------------------------------------------------- text input
def is_valid_slug(value):
    """Lower-case words joined by single hyphens, for example 'ac-servicing'. Safe to use in a web address."""
    return isinstance(value, str) and 1 <= len(value) <= 100 and SLUG_PATTERN.fullmatch(value) is not None


def parse_includes(text):
    """One 'what is included' item per line -> a clean list. Blank lines and extra spaces are dropped."""
    if not isinstance(text, str):
        return []
    items = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        item = " ".join(line.split())
        if item:
            items.append(item)
    return items


def includes_problem(items):
    """A message if the list is too long, otherwise None."""
    if len(items) > MAX_INCLUDES:
        return f"List at most {MAX_INCLUDES} items."
    if any(len(item) > MAX_INCLUDE_LENGTH for item in items):
        return f"Keep each item under {MAX_INCLUDE_LENGTH} characters."
    return None


# ---------------------------------------------------------------- user safety
def user_status_problem(actor_id, target_id, target_role, target_is_active, new_is_active, other_active_admins):
    """Why this activate/deactivate must be refused, or None if it is allowed.

    * Nobody can deactivate their own account (it would lock them out).
    * The last active administrator can never be deactivated.
    * Doing nothing (already in that state) is refused so the page tells the truth.
    """
    if bool(target_is_active) == bool(new_is_active):
        return "That account is already " + ("active." if new_is_active else "deactivated.")
    if not new_is_active and actor_id == target_id:
        return "You cannot deactivate your own account."
    if not new_is_active and target_role == "admin" and other_active_admins < 1:
        return "At least one active administrator must remain."
    return None
