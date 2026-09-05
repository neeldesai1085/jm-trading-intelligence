"""Remove obsolete broker connection storage."""
from alembic import op
import sqlalchemy as sa

revision = 'e7f8g9h0i1j2'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None

def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'broker_connections' in inspector.get_table_names():
        op.drop_index('ix_broker_connections_user_id', table_name='broker_connections')
        op.drop_table('broker_connections')

def downgrade():
    raise RuntimeError('Obsolete broker integration is intentionally not restored.')
