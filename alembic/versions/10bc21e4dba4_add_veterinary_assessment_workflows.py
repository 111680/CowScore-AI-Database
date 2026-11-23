"""add veterinary assessment workflows"""
from alembic import op
import sqlalchemy as sa

revision = '10bc21e4dba4'
down_revision = 'draft_standards_approval'
branch_labels = None
depends_on = None

def upgrade():
    # Additive only: all existing observation and assessment tables are retained.
    op.create_table('assessment_workflows',
    sa.Column('cow_id', sa.Integer(), nullable=False),
    sa.Column('image_cow_id', sa.Integer(), nullable=False),
    sa.Column('scoring_standard', sa.String(length=120), nullable=False),
    sa.Column('mode', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_by', sa.String(length=120), nullable=False),
    sa.Column('request_key', sa.String(length=120), nullable=False),
    sa.Column('bcs_record_id', sa.Integer(), nullable=True),
    sa.Column('prediction_id', sa.Integer(), nullable=True),
    sa.Column('finalized_by', sa.String(length=120), nullable=True),
    sa.Column('finalized_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("(status = 'pending' AND finalized_by IS NULL AND finalized_at IS NULL) OR (status <> 'pending' AND finalized_by IS NOT NULL AND finalized_at IS NOT NULL)", name='workflow_finalizer'),
    sa.CheckConstraint("mode = 'ai' OR prediction_id IS NULL", name='workflow_ai_prediction'),
    sa.CheckConstraint("mode IN ('manual','ai')", name='workflow_mode'),
    sa.CheckConstraint("status IN ('pending','approved','corrected','rejected')", name='workflow_status'),
    sa.CheckConstraint("status NOT IN ('approved','corrected') OR bcs_record_id IS NOT NULL", name='workflow_final_label'),
    sa.ForeignKeyConstraint(['bcs_record_id'], ['bcs_records.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['cow_id'], ['cows.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['image_cow_id', 'cow_id'], ['image_cows.id', 'image_cows.cow_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['prediction_id'], ['ai_predictions.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['scoring_standard'], ['scoring_standards.name'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('bcs_record_id'),
    sa.UniqueConstraint('created_by', 'request_key', name='workflow_request_unique'),
    sa.UniqueConstraint('image_cow_id'),
    sa.UniqueConstraint('prediction_id')
    )
    op.create_index('ix_workflow_cow_created', 'assessment_workflows', ['cow_id', 'created_at'], unique=False)
    op.create_index('ix_workflow_status_created', 'assessment_workflows', ['status', 'created_at'], unique=False)
    # ### end Alembic commands ###

def downgrade():
    if not op.get_context().as_sql:
        count = op.get_bind().scalar(sa.text('SELECT count(*) FROM assessment_workflows'))
        if count:
            raise RuntimeError('Cannot downgrade while assessment workflows exist; preserve their audit links')
    op.drop_index('ix_workflow_status_created', table_name='assessment_workflows')
    op.drop_index('ix_workflow_cow_created', table_name='assessment_workflows')
    op.drop_table('assessment_workflows')
    # ### end Alembic commands ###
