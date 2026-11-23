"""Allow draft scoring standards without changing existing records."""
from alembic import op
import sqlalchemy as sa

revision = 'draft_standards_approval'
down_revision = '75bf68f6980a'
branch_labels = None
depends_on = None

PAIR = '(approved_by IS NULL AND approved_at IS NULL) OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)'

def upgrade():
    with op.batch_alter_table('scoring_standards') as batch:
        batch.alter_column('approved_by', existing_type=sa.String(120), nullable=True)
        batch.alter_column('approved_at', existing_type=sa.DateTime(timezone=True), nullable=True)
        batch.create_check_constraint('standard_approval_pair', PAIR)

def downgrade():
    # Never delete drafts or fabricate approval evidence to force a downgrade.
    if not op.get_context().as_sql:
        count = op.get_bind().scalar(sa.text('SELECT count(*) FROM scoring_standards WHERE approved_by IS NULL OR approved_at IS NULL'))
        if count:
            raise RuntimeError('Cannot downgrade while draft standards exist; retain this migration or supply genuine approval evidence first')
    with op.batch_alter_table('scoring_standards') as batch:
        batch.drop_constraint('standard_approval_pair', type_='check')
        batch.alter_column('approved_by', existing_type=sa.String(120), nullable=False)
        batch.alter_column('approved_at', existing_type=sa.DateTime(timezone=True), nullable=False)
