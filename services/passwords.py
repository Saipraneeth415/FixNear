"""Password rules and hashing. Pure Python: no database or Flask imports.

Passwords are NEVER stored. Only a salted, slow hash is stored. Werkzeug's
default method (scrypt) is designed so that guessing passwords is expensive.
"""
from werkzeug.security import check_password_hash, generate_password_hash

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128  # stops absurdly long inputs from wasting server time

# A tiny list of very common choices that would otherwise satisfy the rules.
COMMON_PASSWORDS = frozenset(
    {
        "password123", "password1234", "password12345", "qwerty12345", "qwertyuiop1",
        "iloveyou123", "welcome1234", "welcome12345", "admin12345", "administrator1",
        "letmein1234", "changeme123", "abc1234567", "test123456", "football123",
        "monkey12345", "dragon12345", "baseball123", "sunshine123", "princess123",
    }
)


def password_problems(password, email="", full_name=""):
    """Return a list of plain-English problems. An empty list means the password is acceptable."""
    if not isinstance(password, str):
        return ["Enter a password."]

    problems = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        problems.append(f"Use no more than {MAX_PASSWORD_LENGTH} characters.")
    if not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        problems.append("Include at least one letter and one number.")

    lowered = password.lower()
    if lowered in COMMON_PASSWORDS:
        problems.append("That password is too common. Choose something harder to guess.")
    if email and lowered == email.strip().lower():
        problems.append("Do not use your email address as your password.")
    if full_name and lowered == " ".join(full_name.split()).lower():
        problems.append("Do not use your name as your password.")
    return problems


def hash_password(password):
    """Return a salted hash that is safe to store."""
    return generate_password_hash(password)


def verify_password(stored_hash, password):
    """True if the password matches the stored hash. Bad or empty hashes never match."""
    if not isinstance(stored_hash, str) or not isinstance(password, str) or not stored_hash:
        return False
    try:
        return check_password_hash(stored_hash, password)
    except (ValueError, TypeError):
        return False
