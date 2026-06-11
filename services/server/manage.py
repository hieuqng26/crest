import os
from flask.cli import FlaskGroup

try:
    import ORE
    print("ORE imported successfully before Flask initialization")
except ImportError as e:
    print(f"Warning: Could not import ORE: {e}")

from project import create_app, db, socketio
from project.api.users.models import User
from project.db_models import seed_data, clean_data

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


@cli.command("seed_data_db")
def seed_data_db():
    seed_data()


@cli.command("clean_data_db")
def clean_data_db():
    clean_data()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        cli()
    else:
        if app.config.get("CONFIG_NAME") == "production":
            socketio.run(app, debug=False, host='0.0.0.0')
        else:
            socketio.run(app, debug=True, allow_unsafe_werkzeug=True, host='0.0.0.0')
