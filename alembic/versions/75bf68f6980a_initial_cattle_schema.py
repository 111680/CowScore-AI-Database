"""initial cattle schema"""
from alembic import op
import sqlalchemy as sa

revision = '75bf68f6980a'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Frozen initial schema; independent of future ORM model changes.
    op.create_table('cows',
    sa.Column('cow_identifier', sa.String(length=120), nullable=False),
    sa.Column('breed', sa.String(length=120), nullable=True),
    sa.Column('sex', sa.String(length=30), nullable=True),
    sa.Column('birth_date', sa.Date(), nullable=True),
    sa.Column('registration_date', sa.Date(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('birth_date IS NULL OR birth_date <= registration_date', name='cow_dates'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cow_identifier')
    )
    op.create_table('images',
    sa.Column('image_path', sa.String(length=1000), nullable=False),
    sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('camera_angle', sa.String(length=100), nullable=True),
    sa.Column('source', sa.String(length=120), nullable=False),
    sa.Column('quality_status', sa.String(length=30), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('image_path')
    )
    op.create_index(op.f('ix_images_captured_at'), 'images', ['captured_at'], unique=False)
    op.create_table('import_rows',
    sa.Column('resource', sa.String(length=80), nullable=False),
    sa.Column('external_key', sa.String(length=200), nullable=False),
    sa.Column('payload_hash', sa.String(length=64), nullable=False),
    sa.Column('record_id', sa.Integer(), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('resource', 'external_key')
    )
    op.create_table('scoring_standards',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('approved_by', sa.String(length=120), nullable=False),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('minimum_score', sa.Numeric(precision=8, scale=3), nullable=True),
    sa.Column('maximum_score', sa.Numeric(precision=8, scale=3), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('minimum_score IS NULL OR maximum_score IS NULL OR minimum_score <= maximum_score', name='standard_range'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('bcs_categories',
    sa.Column('scoring_standard', sa.String(length=120), nullable=False),
    sa.Column('category', sa.String(length=80), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['scoring_standard'], ['scoring_standards.name'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('scoring_standard', 'category')
    )
    op.create_table('feeding_records',
    sa.Column('cow_id', sa.Integer(), nullable=False),
    sa.Column('feeding_timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('feed_type', sa.String(length=120), nullable=False),
    sa.Column('quantity_offered_kg', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('quantity_consumed_kg', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.CheckConstraint('quantity_consumed_kg IS NULL OR (quantity_consumed_kg >= 0 AND quantity_consumed_kg <= quantity_offered_kg)', name='consumed_range'),
    sa.CheckConstraint('quantity_offered_kg >= 0', name='offered_nonnegative'),
    sa.ForeignKeyConstraint(['cow_id'], ['cows.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_feeding_cow_time', 'feeding_records', ['cow_id', 'feeding_timestamp'], unique=False)
    op.create_table('health_records',
    sa.Column('cow_id', sa.Integer(), nullable=False),
    sa.Column('observation_date', sa.DateTime(timezone=True), nullable=False),
    sa.Column('observation_type', sa.String(length=120), nullable=False),
    sa.Column('symptoms_or_observations', sa.Text(), nullable=False),
    sa.Column('veterinarian_notes', sa.Text(), nullable=True),
    sa.Column('follow_up_status', sa.String(length=80), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['cow_id'], ['cows.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_health_cow_date', 'health_records', ['cow_id', 'observation_date'], unique=False)
    op.create_table('image_cows',
    sa.Column('image_id', sa.Integer(), nullable=False),
    sa.Column('cow_id', sa.Integer(), nullable=False),
    sa.Column('crop_path', sa.String(length=1000), nullable=True),
    sa.Column('segmentation_mask_path', sa.String(length=1000), nullable=True),
    sa.Column('bounding_box', sa.JSON(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['cow_id'], ['cows.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['image_id'], ['images.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'cow_id'),
    sa.UniqueConstraint('image_id', 'cow_id')
    )
    op.create_index(op.f('ix_image_cows_cow_id'), 'image_cows', ['cow_id'], unique=False)
    op.create_index(op.f('ix_image_cows_image_id'), 'image_cows', ['image_id'], unique=False)
    op.create_table('milk_production',
    sa.Column('cow_id', sa.Integer(), nullable=False),
    sa.Column('measurement_timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('milk_quantity_liters', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('milking_session', sa.String(length=80), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.CheckConstraint('milk_quantity_liters >= 0', name='milk_nonnegative'),
    sa.ForeignKeyConstraint(['cow_id'], ['cows.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_milk_cow_time', 'milk_production', ['cow_id', 'measurement_timestamp'], unique=False)
    op.create_table('weight_records',
    sa.Column('cow_id', sa.Integer(), nullable=False),
    sa.Column('weight_kg', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('measurement_timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('measurement_context', sa.String(length=30), nullable=False),
    sa.Column('measurement_method', sa.String(length=120), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.CheckConstraint("measurement_context IN ('before_feeding','after_feeding','routine')", name='weight_context'),
    sa.CheckConstraint('weight_kg >= 0', name='weight_nonnegative'),
    sa.ForeignKeyConstraint(['cow_id'], ['cows.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_weight_cow_time', 'weight_records', ['cow_id', 'measurement_timestamp'], unique=False)
    op.create_table('ai_predictions',
    sa.Column('cow_id', sa.Integer(), nullable=False),
    sa.Column('image_cow_id', sa.Integer(), nullable=False),
    sa.Column('model_name', sa.String(length=120), nullable=False),
    sa.Column('model_version', sa.String(length=120), nullable=False),
    sa.Column('predicted_bcs_score', sa.Numeric(precision=8, scale=3), nullable=True),
    sa.Column('predicted_category', sa.String(length=80), nullable=True),
    sa.Column('scoring_standard', sa.String(length=120), nullable=False),
    sa.Column('confidence_score', sa.Numeric(precision=8, scale=6), nullable=True),
    sa.Column('prediction_timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.CheckConstraint('confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)', name='confidence_range'),
    sa.CheckConstraint('predicted_bcs_score IS NOT NULL OR predicted_category IS NOT NULL', name='prediction_required'),
    sa.ForeignKeyConstraint(['cow_id'], ['cows.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['image_cow_id', 'cow_id'], ['image_cows.id', 'image_cows.cow_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['scoring_standard', 'predicted_category'], ['bcs_categories.scoring_standard', 'bcs_categories.category'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['scoring_standard'], ['scoring_standards.name'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_prediction_cow_time', 'ai_predictions', ['cow_id', 'prediction_timestamp'], unique=False)
    op.create_table('bcs_records',
    sa.Column('cow_id', sa.Integer(), nullable=False),
    sa.Column('image_cow_id', sa.Integer(), nullable=True),
    sa.Column('bcs_score', sa.Numeric(precision=8, scale=3), nullable=True),
    sa.Column('bcs_category', sa.String(length=80), nullable=True),
    sa.Column('scoring_standard', sa.String(length=120), nullable=False),
    sa.Column('evaluator', sa.String(length=120), nullable=False),
    sa.Column('evaluation_method', sa.String(length=80), nullable=False),
    sa.Column('evaluation_date', sa.DateTime(timezone=True), nullable=False),
    sa.Column('review_status', sa.String(length=30), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("evaluation_method IN ('manual','veterinary')", name='manual_bcs_only'),
    sa.CheckConstraint("review_status IN ('pending','approved','rejected')", name='bcs_review'),
    sa.CheckConstraint('bcs_score IS NOT NULL OR bcs_category IS NOT NULL', name='bcs_label_required'),
    sa.ForeignKeyConstraint(['cow_id'], ['cows.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['image_cow_id', 'cow_id'], ['image_cows.id', 'image_cows.cow_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['scoring_standard', 'bcs_category'], ['bcs_categories.scoring_standard', 'bcs_categories.category'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['scoring_standard'], ['scoring_standards.name'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_bcs_cow_date', 'bcs_records', ['cow_id', 'evaluation_date'], unique=False)


def downgrade():
    # Frozen initial schema; independent of future ORM model changes.
    op.drop_index('ix_bcs_cow_date', table_name='bcs_records')
    op.drop_table('bcs_records')
    op.drop_index('ix_prediction_cow_time', table_name='ai_predictions')
    op.drop_table('ai_predictions')
    op.drop_index('ix_weight_cow_time', table_name='weight_records')
    op.drop_table('weight_records')
    op.drop_index('ix_milk_cow_time', table_name='milk_production')
    op.drop_table('milk_production')
    op.drop_index(op.f('ix_image_cows_image_id'), table_name='image_cows')
    op.drop_index(op.f('ix_image_cows_cow_id'), table_name='image_cows')
    op.drop_table('image_cows')
    op.drop_index('ix_health_cow_date', table_name='health_records')
    op.drop_table('health_records')
    op.drop_index('ix_feeding_cow_time', table_name='feeding_records')
    op.drop_table('feeding_records')
    op.drop_table('bcs_categories')
    op.drop_table('scoring_standards')
    op.drop_table('import_rows')
    op.drop_index(op.f('ix_images_captured_at'), table_name='images')
    op.drop_table('images')
    op.drop_table('cows')


