"""Initial multi-user schema.

The ORM metadata is the single source of truth for the initial deployment; Alembic records
that the schema has been initialized so subsequent revisions can be incremental.
"""
from alembic import op
from sqlalchemy import text
from app.db.session import Base, engine
from app.models import entities

revision='786383fd7320'
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    Base.metadata.create_all(bind=engine)

def downgrade():
    bind=op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        table.drop(bind=bind,checkfirst=True)
