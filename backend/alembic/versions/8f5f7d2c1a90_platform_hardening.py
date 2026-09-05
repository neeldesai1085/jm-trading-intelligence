"""Add portfolios, background imports, password reset and operational metadata."""
from alembic import op
import sqlalchemy as sa

revision = '8f5f7d2c1a90'
down_revision = '786383fd7320'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('portfolios', sa.Column('id',sa.Integer(),primary_key=True), sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False), sa.Column('name',sa.String(120),nullable=False), sa.Column('is_default',sa.Boolean(),nullable=False,server_default=sa.false()), sa.Column('created_at',sa.DateTime(),nullable=False), sa.UniqueConstraint('user_id','name',name='uq_portfolio_user_name'))
    op.create_index('ix_portfolios_user_id','portfolios',['user_id']);op.create_index('ix_portfolios_is_default','portfolios',['is_default'])
    op.add_column('users', sa.Column('email_verified',sa.Boolean(),nullable=False,server_default=sa.false())); op.add_column('users', sa.Column('updated_at',sa.DateTime()))
    op.create_table('password_reset_tokens', sa.Column('id',sa.Integer(),primary_key=True), sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False), sa.Column('token_hash',sa.String(128),nullable=False), sa.Column('expires_at',sa.DateTime(),nullable=False), sa.Column('used_at',sa.DateTime()), sa.Column('created_at',sa.DateTime(),nullable=False), sa.UniqueConstraint('token_hash'))
    op.create_index('ix_password_reset_tokens_user_id','password_reset_tokens',['user_id']);op.create_index('ix_password_reset_tokens_token_hash','password_reset_tokens',['token_hash'],unique=True)
    op.create_table('import_jobs', sa.Column('id',sa.Integer(),primary_key=True), sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False), sa.Column('portfolio_id',sa.Integer(),sa.ForeignKey('portfolios.id'),nullable=False), sa.Column('filename',sa.String(255),nullable=False), sa.Column('status',sa.String(32),nullable=False), sa.Column('error',sa.Text()), sa.Column('result_json',sa.Text()), sa.Column('created_at',sa.DateTime(),nullable=False), sa.Column('started_at',sa.DateTime()), sa.Column('completed_at',sa.DateTime()))
    op.create_index('ix_import_jobs_user_id','import_jobs',['user_id']);op.create_index('ix_import_jobs_portfolio_id','import_jobs',['portfolio_id']);op.create_index('ix_import_jobs_status','import_jobs',['status'])
    for table in ['import_batches','contract_notes','security_ledger','executions','trade_annotations']:
        op.add_column(table, sa.Column('portfolio_id',sa.Integer(),nullable=True))
        op.create_index(f'ix_{table}_portfolio_id', table, ['portfolio_id'])
    bind = op.get_bind()
    rows = bind.execute(sa.text('SELECT id FROM users')).fetchall()
    for row in rows:
        bind.execute(sa.text("INSERT INTO portfolios (user_id,name,is_default,created_at) VALUES (:uid,'Main Portfolio',1,CURRENT_TIMESTAMP)"), {'uid': row[0]})
        pid = bind.execute(sa.text('SELECT id FROM portfolios WHERE user_id=:uid ORDER BY id DESC LIMIT 1'), {'uid': row[0]}).scalar_one()
        for table in ['import_batches','contract_notes','security_ledger','executions','trade_annotations']:
            bind.execute(sa.text(f'UPDATE {table} SET portfolio_id=:pid WHERE user_id=:uid'), {'pid': pid, 'uid': row[0]})
    op.create_index('ix_import_batches_user_portfolio','import_batches',['user_id','portfolio_id'])
    op.create_index('ix_contract_user_portfolio_date','contract_notes',['user_id','portfolio_id','trade_date'])
    op.create_index('ix_sec_user_portfolio_date','security_ledger',['user_id','portfolio_id','trade_date'])
    op.create_index('ix_exec_user_portfolio_date','executions',['user_id','portfolio_id','trade_date'])


def downgrade():
    for table,idx in [('executions','ix_exec_user_portfolio_date'),('security_ledger','ix_sec_user_portfolio_date'),('contract_notes','ix_contract_user_portfolio_date'),('import_batches','ix_import_batches_user_portfolio')]:
        op.drop_index(idx,table_name=table)
    for table in ['trade_annotations','executions','security_ledger','contract_notes','import_batches']:
        op.drop_index(f'ix_{table}_portfolio_id',table_name=table);op.drop_column(table,'portfolio_id')
    op.drop_table('import_jobs');op.drop_table('password_reset_tokens');op.drop_column('users','updated_at');op.drop_column('users','email_verified');op.drop_table('portfolios')
