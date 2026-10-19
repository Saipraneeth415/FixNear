"""Booking rules in plain Python: statuses, allowed changes, cancellation, dates,
phone numbers and booking references.

No database or Flask imports here, so every rule can be tested on its own.
"""
import re
import secrets
from datetime import datetime, time, timedelta, timezone

# ---------------------------------------------------------------- statuses
STATUS_PENDING = "pending"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"

STATUSES = (STATUS_PENDING, STATUS_ACCEPTED, STATUS_REJECTED, STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_CANCELLED)

STATUS_LABELS = {
    STATUS_PENDING: "Pending",
    STATUS_ACCEPTED: "Accepted",
    STATUS_REJECTED: "Rejected",
    STATUS_IN_PROGRESS: "In Progress",
    STATUS_COMPLETED: "Completed",
    STATUS_CANCELLED: "Cancelled",
}

# Statuses that still "use up" a time slot.
ACTIVE_STATUSES = (STATUS_PENDING, STATUS_ACCEPTED, STATUS_IN_PROGRESS)

# The ONLY allowed status changes. Anything not listed here is refused.
#   Pending -> Accepted -> In Progress -> Completed
#   Pending -> Rejected;  Pending or Accepted -> Cancelled
TRANSITIONS = {
    STATUS_PENDING: (STATUS_ACCEPTED, STATUS_REJECTED, STATUS_CANCELLED),
    STATUS_ACCEPTED: (STATUS_IN_PROGRESS, STATUS_CANCELLED),
    STATUS_IN_PROGRESS: (STATUS_COMPLETED,),
    STATUS_COMPLETED: (),
    STATUS_REJECTED: (),
    STATUS_CANCELLED: (),
}

CANCELLATION_NOTICE_HOURS = 24


def can_transition(current, new):
    """True only if moving from current to new is allowed."""
    return new in TRANSITIONS.get(current, ())


def allowed_transitions(current):
    return TRANSITIONS.get(current, ())


def cancellation_block_reason(status, appointment_start, now):
    """Why a CUSTOMER cannot cancel right now, or None if they can.

    Rules:
      * Pending bookings can be cancelled at any time.
      * Accepted bookings can be cancelled until 24 hours before the appointment.
      * In progress, completed, rejected and cancelled bookings cannot be cancelled.
    """
    if status == STATUS_CANCELLED:
        return "This booking has already been cancelled."
    if status == STATUS_COMPLETED:
        return "Completed bookings cannot be cancelled."
    if status == STATUS_REJECTED:
        return "Rejected bookings cannot be cancelled."
    if status == STATUS_IN_PROGRESS:
        return "This job is already in progress and can no longer be cancelled online."
    if not can_transition(status, STATUS_CANCELLED):
        return "This booking cannot be cancelled."
    if status == STATUS_ACCEPTED and appointment_start - now < timedelta(hours=CANCELLATION_NOTICE_HOURS):
        return f"Accepted bookings can only be cancelled at least {CANCELLATION_NOTICE_HOURS} hours before the appointment."
    return None


# ------------------------------------------------------- provider rules
# Statuses in which a provider has promised to do the job.
COMMITTED_STATUSES = (STATUS_ACCEPTED, STATUS_IN_PROGRESS)

# A job reserves this long from its start time. Real jobs vary (the service
# page says "1 to 2 hours" and so on), so this is a simple, documented rule:
# a provider cannot have two active jobs that start less than 2 hours apart.
JOB_BLOCK_MINUTES = 120

# What a provider may do, and the status each action leads to. The server
# still checks every change against TRANSITIONS.
PROVIDER_ACTIONS = {
    "accept": STATUS_ACCEPTED,
    "reject": STATUS_REJECTED,
    "start": STATUS_IN_PROGRESS,
    "complete": STATUS_COMPLETED,
}
PROVIDER_ACTION_ORDER = ("accept", "reject", "start", "complete")
PROVIDER_ACTION_LABELS = {"accept": "Accept", "reject": "Reject", "start": "Start job", "complete": "Mark completed"}
PROVIDER_ACTION_MESSAGES = {
    "accept": "Booking accepted.",
    "reject": "Booking rejected.",
    "start": "Job started.",
    "complete": "Job marked as completed.",
}


def provider_actions_for(status):
    """The provider actions that make sense for a booking in this status."""
    return [action for action in PROVIDER_ACTION_ORDER if can_transition(status, PROVIDER_ACTIONS[action])]


def times_conflict(first, second, block_minutes=JOB_BLOCK_MINUTES):
    """True if two start times on the SAME day are too close together."""
    first_minutes = first.hour * 60 + first.minute
    second_minutes = second.hour * 60 + second.minute
    return abs(first_minutes - second_minutes) < block_minutes


def tracking_steps(status):
    """The progress line for the details page: [(label, state)] with state done/current/upcoming.

    Returns None for Rejected and Cancelled, which are not steps on the normal path.
    """
    path = [STATUS_PENDING, STATUS_ACCEPTED, STATUS_IN_PROGRESS, STATUS_COMPLETED]
    if status not in path:
        return None
    position = path.index(status)
    steps = []
    for index, step in enumerate(path):
        if status == STATUS_COMPLETED or index < position:
            state = "done"
        elif index == position:
            state = "current"
        else:
            state = "upcoming"
        steps.append((STATUS_LABELS[step], state))
    return steps


# ------------------------------------------------------------ date and time
MAX_DAYS_AHEAD = 90


def _build_time_slots():
    slots = []
    for hour in range(8, 20):  # 08:00 to 19:30, every 30 minutes
        for minute in (0, 30):
            slots.append(f"{hour:02d}:{minute:02d}")
    return tuple(slots)


TIME_SLOTS = _build_time_slots()


def _slot_label(slot):
    hour, minute = int(slot[:2]), slot[3:]
    suffix = "AM" if hour < 12 else "PM"
    return f"{hour % 12 or 12}:{minute} {suffix}"


def time_slot_choices():
    """(value, label) pairs for the time drop-down, starting with an empty prompt."""
    return [("", "Select a time")] + [(slot, _slot_label(slot)) for slot in TIME_SLOTS]


def local_now(offset_minutes=330):
    """The customer's local date and time as a plain datetime.

    The server may run in another time zone, so the offset from UTC comes from
    configuration. 330 minutes = India Standard Time (no daylight saving).
    """
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=offset_minutes)


def parse_time_slot(value):
    """'09:30' -> time(9, 30). Only the offered slots are accepted; anything else gives None."""
    if not isinstance(value, str) or value not in TIME_SLOTS:
        return None
    return time(int(value[:2]), int(value[3:]))


def date_problem(appointment_date, now):
    if appointment_date is None:
        return "Choose a date."
    if appointment_date < now.date():
        return "The appointment date cannot be in the past."
    if appointment_date > now.date() + timedelta(days=MAX_DAYS_AHEAD):
        return f"Choose a date within the next {MAX_DAYS_AHEAD} days."
    return None


def time_problem(appointment_date, slot, now):
    parsed = parse_time_slot(slot)
    if parsed is None:
        return "Choose a time from the list."
    if appointment_date is not None and appointment_date == now.date() and parsed <= now.time():
        return "That time has already passed today. Choose a later time."
    return None


def appointment_problems(appointment_date, slot, now):
    """All date and time problems as a list of plain-English messages."""
    problems = []
    for problem in (date_problem(appointment_date, now), time_problem(appointment_date, slot, now)):
        if problem:
            problems.append(problem)
    return problems


# ------------------------------------------------------------------- text
_PHONE_PATTERN = re.compile(r"^\+?[0-9(][0-9 ()\-]*$")


def normalize_phone(raw):
    """Return a tidy phone number such as '+919876543210', or None if it is not valid.

    Accepts digits with optional spaces, brackets and dashes and an optional
    leading +. Must contain 10 to 15 digits.
    """
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw or len(raw) > 25 or not _PHONE_PATTERN.match(raw):
        return None
    digits = re.sub(r"\D", "", raw)
    if not 10 <= len(digits) <= 15:
        return None
    return ("+" if raw.startswith("+") else "") + digits


def clean_line(value):
    """Single-line text: trim and collapse repeated spaces."""
    return " ".join(value.split()) if isinstance(value, str) else ""


def clean_multiline(value):
    """Multi-line text: trim, use \\n line endings, and drop control characters."""
    if not isinstance(value, str):
        return ""
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    return "".join(ch for ch in value if ch == "\n" or ch >= " ")


# --------------------------------------------------------------- reference
# No 0, O, 1, I or L, so a reference is easy to read out over the phone.
REFERENCE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
REFERENCE_PATTERN = re.compile(r"^FN-[A-HJ-KM-NP-Z2-9]{4}-[A-HJ-KM-NP-Z2-9]{4}$")


def generate_reference():
    """A random reference like FN-7K4M-9QXT (31^8, about 850 billion, possibilities).

    It is random, not a counter, so it reveals nothing about how many bookings
    exist or about anyone's database ID.
    """
    chars = [secrets.choice(REFERENCE_ALPHABET) for _ in range(8)]
    return "FN-" + "".join(chars[:4]) + "-" + "".join(chars[4:])


def is_valid_reference(value):
    return isinstance(value, str) and REFERENCE_PATTERN.fullmatch(value) is not None
