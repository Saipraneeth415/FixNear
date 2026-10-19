"""Which providers offer which services (many-to-many).

A booking can only be assigned to a provider who offers its service. Rows are
added by administrators (the command line for now, the admin dashboard in Stage 7).
"""
from extensions import db
from models.mixins import utcnow

provider_services = db.Table(
    "provider_services",
    db.Column("provider_id", db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    db.Column("service_id", db.Integer, db.ForeignKey("services.id", ondelete="CASCADE"), primary_key=True, index=True),
    db.Column("created_at", db.DateTime(timezone=True), nullable=False, default=utcnow),
)
