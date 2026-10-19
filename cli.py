"""Custom Flask commands.

    flask --app app seed-db       add the sample categories and services
    flask --app app db-stats      show which database is used and what it holds
    flask --app app create-admin  create the first administrator (password is typed in)
    flask --app app list-users    list accounts (never shows passwords or hashes)
    flask --app app create-provider    create a provider account and link services to it
    flask --app app provider-services  show, add or remove the services a provider offers
    flask --app app assign-pending     give providers to Pending bookings that have none yet
"""
import click
from sqlalchemy import func, inspect, select

from extensions import db
from models import ROLE_ADMIN, ROLE_PROVIDER, Booking, Service, ServiceCategory, User
from services import accounts, providers, scheduling
from services.seed import seed_database, tables_exist

MISSING_TABLES_HELP = (
    "The database tables do not exist yet. Create them first with:\n"
    "    flask --app app db upgrade"
)


def register_commands(app):
    @app.cli.command("seed-db")
    def seed_db_command():
        """Add sample categories and services. Safe to run many times."""
        if not tables_exist():
            raise click.ClickException(MISSING_TABLES_HELP)

        click.echo("Seeding sample data (nothing is deleted or overwritten)...")
        result = seed_database()
        click.echo(f"Categories: {result.categories_created} created, {result.categories_existing} already present")
        click.echo(f"Services: {result.services_created} created, {result.services_skipped} skipped (already present)")
        click.echo("Done.")

    @app.cli.command("db-stats")
    def db_stats_command():
        """Show the configured database and how many rows it contains."""
        click.echo(f"Database: {db.engine.url.render_as_string(hide_password=True)}")
        if not tables_exist():
            click.echo("Tables: not created yet (run: flask --app app db upgrade)")
            return
        categories = db.session.scalar(select(func.count(ServiceCategory.id)))
        services = db.session.scalar(select(func.count(Service.id)))
        click.echo(f"Service categories: {categories}")
        click.echo(f"Services: {services}")

MISSING_USERS_TABLE_HELP = (
    "The users table does not exist yet. Create it first with:\n"
    "    flask --app app db migrate -m \"Add users table\"\n"
    "    flask --app app db upgrade"
)


def register_account_commands(app):
    @app.cli.command("create-admin")
    @click.option("--email", prompt="Administrator email", help="Login email for the new administrator.")
    @click.option("--name", "full_name", prompt="Full name", help="Display name.")
    def create_admin_command(email, full_name):
        """Create an administrator. You type the password; it is never stored in code."""
        if not accounts.users_table_exists():
            raise click.ClickException(MISSING_USERS_TABLE_HELP)
        if accounts.get_user_by_email(email) is not None:
            raise click.ClickException("An account with that email already exists. Nothing was changed.")

        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
        try:
            user = accounts.create_user(email=email, full_name=full_name, password=password, role=ROLE_ADMIN)
        except (accounts.InvalidEmailError, accounts.WeakPasswordError, accounts.DuplicateEmailError, ValueError) as error:
            raise click.ClickException(str(error) or "Could not create the account.")
        click.echo(f"Administrator created: {user.email}")

    @app.cli.command("list-users")
    def list_users_command():
        """List accounts: email, role and whether they are active."""
        if not accounts.users_table_exists():
            raise click.ClickException(MISSING_USERS_TABLE_HELP)
        users = list(db.session.scalars(select(User).order_by(User.id)))
        if not users:
            click.echo("No users yet.")
            return
        for user in users:
            status = "active" if user.is_active else "suspended"
            click.echo(f"{user.id:>3}  {user.email}  {user.role}  {status}")


MISSING_PROVIDER_TABLE_HELP = (
    "The provider_services table does not exist yet. Create it first with:\n"
    "    flask --app app db migrate -m \"Add provider services table\"\n"
    "    flask --app app db upgrade"
)


def _require_provider_tables():
    inspector = inspect(db.engine)
    if not (inspector.has_table("users") and inspector.has_table("provider_services")):
        raise click.ClickException(MISSING_PROVIDER_TABLE_HELP)


def _resolve_services(slugs):
    """Turn slugs into Service rows. Unknown slugs stop the command before anything is changed."""
    found, unknown = [], []
    for slug in slugs:
        service = providers.get_service_by_slug(slug.strip().lower())
        (found if service is not None else unknown).append(service if service is not None else slug)
    if unknown:
        raise click.ClickException("Unknown service(s): " + ", ".join(unknown) + ". Nothing was changed.")
    return found


def register_provider_commands(app):
    @app.cli.command("create-provider")
    @click.option("--email", prompt="Provider email", help="Login email for the new provider.")
    @click.option("--name", "full_name", prompt="Full name", help="Display name.")
    @click.option("--service", "service_slugs", multiple=True, help="Slug of a service this provider offers. Repeat for several.")
    def create_provider_command(email, full_name, service_slugs):
        """Create a provider account. You type the password; it is never stored in code."""
        _require_provider_tables()
        if accounts.get_user_by_email(email) is not None:
            raise click.ClickException("An account with that email already exists. Nothing was changed.")
        services = _resolve_services(service_slugs)

        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
        try:
            user = accounts.create_user(email=email, full_name=full_name, password=password, role=ROLE_PROVIDER)
        except (accounts.InvalidEmailError, accounts.WeakPasswordError, accounts.DuplicateEmailError, ValueError) as error:
            raise click.ClickException(str(error) or "Could not create the account.")
        for service in services:
            providers.grant_service(user, service)
        click.echo(f"Provider created: {user.email}")
        click.echo("Offers: " + (", ".join(s.slug for s in services) if services else "no services yet"))

    @app.cli.command("provider-services")
    @click.option("--email", required=True, help="Email of the provider account.")
    @click.option("--add", "add_slugs", multiple=True, help="Service slug to add. Repeat for several.")
    @click.option("--remove", "remove_slugs", multiple=True, help="Service slug to remove. Repeat for several.")
    def provider_services_command(email, add_slugs, remove_slugs):
        """Show, add or remove the services a provider offers."""
        _require_provider_tables()
        provider = providers.get_provider_by_email(email)
        if provider is None:
            raise click.ClickException("No provider account with that email.")
        to_add = _resolve_services(add_slugs)
        to_remove = _resolve_services(remove_slugs)
        for service in to_add:
            click.echo(("Added: " if providers.grant_service(provider, service) else "Already offered: ") + service.slug)
        for service in to_remove:
            click.echo(("Removed: " if providers.revoke_service(provider, service) else "Was not offered: ") + service.slug)
        current = providers.offered_services(provider)
        click.echo(f"Services offered by {provider.email}:")
        click.echo("\n".join(f"  {service.slug}" for service in current) if current else "  (none)")

    @app.cli.command("assign-pending")
    def assign_pending_command():
        """Give a provider to Pending bookings that have none (made before a provider offered the service)."""
        _require_provider_tables()
        waiting = list(
            db.session.scalars(
                select(Booking).where(Booking.provider_id.is_(None), Booking.status == "pending").order_by(Booking.created_at, Booking.id)
            )
        )
        assigned = 0
        for booking in waiting:
            provider = scheduling.assign_existing(booking)
            if provider is not None:
                assigned += 1
                click.echo(f"{booking.reference} -> {provider.email}")
        click.echo(f"Assigned: {assigned}. Still unassigned: {len(waiting) - assigned}.")
