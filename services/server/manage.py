
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
    if User.query.first() is None:
        db.session.add(User(email="admin", password="admin", role="admin"))
        db.session.commit()


if __name__ == "__main__":
    cli()
