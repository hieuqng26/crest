from flask.cli import FlaskGroup

from project import create_app, db
from project.api.users.models import User

app = create_app()
cli = FlaskGroup(create_app=create_app)


@cli.command("create_db")
def create_db():
    db.drop_all()
    db.create_all()
    db.session.commit()


@cli.command("seed_db")
def seed_db():
    import os

    from project.api.roles.defaults import ensure_default_roles

    ensure_default_roles()
    admin_email = os.getenv("SEED_ADMIN_EMAIL", "admin@crest.local")
    admin_pw = os.getenv("SEED_ADMIN_PASSWORD")
    if not admin_pw:
        raise SystemExit(
            "SEED_ADMIN_PASSWORD env var is required to seed the admin user"
        )
    if not User.query.filter_by(email=admin_email).first():
        db.session.add(
            User(
                email=admin_email,
                password=admin_pw,
                role="sysadmin",
                name="Administrator",
            )
        )
        db.session.commit()


if __name__ == "__main__":
    cli()
