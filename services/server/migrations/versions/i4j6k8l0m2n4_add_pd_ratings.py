"""add pd_ratings table and seed data

Revision ID: i4j6k8l0m2n4
Revises: h3i5k7l9m1n2
Create Date: 2026-06-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "i4j6k8l0m2n4"
down_revision = "h3i5k7l9m1n2"
branch_labels = None
depends_on = None

_SEED_ROWS = [
    (1,  "moodys", 1,  "Aaa1",  0.0003),
    (2,  "moodys", 2,  "Aaa2",  0.001),
    (3,  "moodys", 3,  "Aaa3",  0.0019),
    (4,  "moodys", 4,  "Aa1",   0.0031),
    (5,  "moodys", 5,  "Aa2",   0.0048),
    (6,  "moodys", 6,  "Aa3",   0.0069),
    (7,  "moodys", 7,  "A1",    0.0097),
    (8,  "moodys", 8,  "A2",    0.0135),
    (9,  "moodys", 9,  "A3",    0.0184),
    (10, "moodys", 10, "Baa1",  0.0249),
    (11, "moodys", 11, "Baa2",  0.0336),
    (12, "moodys", 12, "Baa3",  0.0451),
    (13, "moodys", 13, "Ba1",   0.0602),
    (14, "moodys", 14, "Ba2",   0.0803),
    (15, "moodys", 15, "B1",    0.1068),
    (16, "moodys", 16, "B2",    0.1419),
    (17, "moodys", 17, "Caa1",  0.1884),
    (18, "moodys", 18, "Caa2",  0.2498),
    (19, "moodys", 19, "Caa3",  0.3311),
]


def upgrade():
    pd_ratings = op.create_table(
        "pd_ratings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("curve_name", sa.String(32), nullable=False, server_default="moodys"),
        sa.Column("category", sa.Integer(), nullable=False),
        sa.Column("rating", sa.String(16), nullable=False),
        sa.Column("pd", sa.Float(), nullable=False),
    )
    op.bulk_insert(
        pd_ratings,
        [
            {"id": r[0], "curve_name": r[1], "category": r[2], "rating": r[3], "pd": r[4]}
            for r in _SEED_ROWS
        ],
    )


def downgrade():
    op.drop_table("pd_ratings")
