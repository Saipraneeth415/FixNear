"""Errors raised by the booking and scheduling services.

Messages on BookingRuleError (and its subclasses) are written to be safe to
show to the person who caused them.
"""


class BookingRuleError(Exception):
    """A booking rule was broken."""


class BookingPermissionError(PermissionError):
    """The user is not allowed to do this."""


class BookingReferenceError(Exception):
    """A unique reference could not be generated (extremely unlikely)."""


class InvalidTransitionError(BookingRuleError):
    """That status change is not allowed."""


class NoProviderAvailableError(BookingRuleError):
    """Providers offer this service, but every one of them is busy at that time."""


class SchedulingConflictError(BookingRuleError):
    """The provider already has another job at that time."""


class AdminPermissionError(PermissionError):
    """The user is not an active administrator."""


class AdminRuleError(Exception):
    """An admin action was refused. The message is safe to show to the administrator."""
