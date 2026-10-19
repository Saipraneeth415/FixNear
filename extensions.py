"""Shared Flask extensions.

They are created here, without an app, and connected to the app inside
create_app() with init_app(). This avoids circular imports.
"""
import sqlite3

from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import MetaData, event
from sqlalchemy.engine import Engine

# Predictable names for constraints and indexes. Migrations (Alembic) need
# names, especially for SQLite, and the same names work on PostgreSQL/MySQL.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

db = SQLAlchemy(metadata=MetaData(naming_convention=NAMING_CONVENTION))
migrate = Migrate()

# CSRF protection: every POST form must carry a secret token that belongs to the
# visitor's session. A malicious site cannot read it, so it cannot forge requests.
csrf = CSRFProtect()

# Login sessions. Anonymous visitors who open a protected page are sent to the
# login page, which then returns them to the page they wanted.
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "info"


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    """SQLite ignores foreign keys unless you switch them on for each connection."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
