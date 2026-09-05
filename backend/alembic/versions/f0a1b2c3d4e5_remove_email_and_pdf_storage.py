"""Remove deprecated email reset/verification and PDF archive metadata."""
from alembic import op
import sqlalchemy as sa

revision = 'f0a1b2c3d4e5'
down_revision = 'e7f8g9h0i1j2'
branch_labels = None
depends_on = None

def _columns(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}

def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())

def upgrade():
    tables = _tables()
    if 'email_verification_tokens' in tables: op.drop_table('email_verification_tokens')
    if 'password_reset_tokens' in tables: op.drop_table('password_reset_tokens')
    if 'email_verified' in _columns('users'): op.drop_column('users', 'email_verified')
    if 'source_uri' in _columns('import_batches'): op.drop_column('import_batches', 'source_uri')

def downgrade():
    raise RuntimeError('Deprecated email and PDF archive features are intentionally not restored.')
