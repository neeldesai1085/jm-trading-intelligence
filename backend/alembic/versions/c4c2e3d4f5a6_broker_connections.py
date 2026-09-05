"""Add encrypted per-user broker connections."""
from alembic import op
import sqlalchemy as sa

revision='c4c2e3d4f5a6'
down_revision='8f5f7d2c1a90'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('broker_connections', sa.Column('id',sa.Integer(),primary_key=True), sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False), sa.Column('provider',sa.String(32),nullable=False), sa.Column('access_token_encrypted',sa.Text(),nullable=False), sa.Column('refresh_token_encrypted',sa.Text()), sa.Column('expires_at',sa.DateTime()), sa.Column('connected_at',sa.DateTime(),nullable=False), sa.Column('updated_at',sa.DateTime(),nullable=False), sa.UniqueConstraint('user_id','provider',name='uq_broker_user_provider'))
    op.create_index('ix_broker_connections_user_id','broker_connections',['user_id'])

def downgrade():
    op.drop_table('broker_connections')
