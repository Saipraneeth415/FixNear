"""The Booking model: one customer's request for one service at a chosen time."""
from datetime import datetime

from sqlalchemy.orm import validates

from extensions import db
from models.mixins import TimestampMixin
from services.booking_rules import ACTIVE_STATUSES, STATUS_LABELS, STATUS_PENDING, STATUSES


class Booking(TimestampMixin, db.Model):
    __tablename__ = "bookings"
    __table_args__ = (
        db.CheckConstraint("status IN (" + ", ".join(f"'{s}'" for s in STATUSES) + ")", name="status_valid"),
        db.CheckConstraint("price_from_at_booking >= 0", name="price_nonnegative"),
        # The same customer cannot save the same form submission twice.
        db.UniqueConstraint("customer_id", "submission_token"),
        # Fast "my bookings, newest first".
        db.Index("ix_bookings_customer_created", "customer_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)  # internal only; never shown to customers
    reference = db.Column(db.String(20), nullable=False, unique=True)  # public, e.g. FN-7K4M-9QXT

    customer_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id", ondelete="RESTRICT"), nullable=False, index=True)
    # Optional for now. Stage 6 connects providers: a provider will be assigned
    # when they accept the request. Customers can never set this.
    provider_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    contact_name = db.Column(db.String(100), nullable=False)
    contact_phone = db.Column(db.String(20), nullable=False)
    address = db.Column(db.String(300), nullable=False)
    appointment_date = db.Column(db.Date, nullable=False)
    appointment_time = db.Column(db.Time, nullable=False)
    problem_description = db.Column(db.Text, nullable=False)

    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING, index=True)
    cancellation_reason = db.Column(db.String(300), nullable=True)
    cancelled_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # The service's starting price when the booking was made. Set by the server
    # from the service, never from the form, and it does not change if the
    # service price changes later.
    price_from_at_booking = db.Column(db.Integer, nullable=False)

    # Random value created with the booking form; makes double-clicks harmless.
    submission_token = db.Column(db.String(64), nullable=True)

    customer = db.relationship("User", foreign_keys=[customer_id], back_populates="bookings")
    provider = db.relationship("User", foreign_keys=[provider_id])
    service = db.relationship("Service", back_populates="bookings")

    @validates("reference")
    def _reference_never_changes(self, _key, value):
        if self.reference is not None and self.reference != value:
            raise ValueError("A booking reference can never be changed.")
        return value

    @property
    def status_label(self):
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def appointment_start(self):
        return datetime.combine(self.appointment_date, self.appointment_time)

    @property
    def is_active_status(self):
        return self.status in ACTIVE_STATUSES

    def __repr__(self):
        return f"<Booking {self.reference} {self.status}>"
