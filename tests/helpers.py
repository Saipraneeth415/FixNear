"""Shared test helpers.

Every database test gets its OWN temporary SQLite file, created in the
operating system's temp folder and deleted afterwards. The real database
(instance/fixnear.db) is never touched by the tests.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from app import create_app
from config import TestingConfig
from extensions import db
from services.seed import seed_database


def make_config(db_path):
    """A testing config that points at the given database file."""
    uri = f"sqlite:///{Path(db_path).as_posix()}"  # forward slashes also work on Windows
    return type("TempTestingConfig", (TestingConfig,), {"SQLALCHEMY_DATABASE_URI": uri})


class DatabaseTestCase(unittest.TestCase):
    """Creates a fresh temporary database (tables, plus sample data if seed=True).

    Set create_tables = False in a subclass to start with a completely empty file.
    """

    seed = True
    create_tables = True

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="fixnear-test-"))
        self.db_path = self.tmpdir / "test.db"
        self.addCleanup(self._remove_tmpdir)  # registered first, so it runs last
        self.app = create_app(make_config(self.db_path))
        self.addCleanup(self.dispose, self.app)
        if self.create_tables:
            with self.app.app_context():
                db.create_all()
                if self.seed:
                    seed_database()
        self.client = self.app.test_client()

    @staticmethod
    def dispose(app):
        """Close database connections (Windows cannot delete a file that is still open)."""
        with app.app_context():
            db.session.remove()
            db.engine.dispose()

    def _remove_tmpdir(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
