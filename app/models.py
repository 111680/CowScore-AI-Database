"""Relational entities. Restrictive foreign keys deliberately preserve history."""
from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import (String, Text, Date, DateTime, Numeric, JSON, ForeignKey,
                        ForeignKeyConstraint, UniqueConstraint, CheckConstraint, Index)
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, UTCDateTime

def now():
    return datetime.now(timezone.utc)

class Identity:
    id: Mapped[int] = mapped_column(primary_key=True)

class Created:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)

class Cow(Identity, Created, Base):
    __tablename__ = 'cows'
    cow_identifier: Mapped[str] = mapped_column(String(120), unique=True)
    breed: Mapped[str | None] = mapped_column(String(120))
    sex: Mapped[str | None] = mapped_column(String(30))
    birth_date: Mapped[date | None] = mapped_column(Date)
    registration_date: Mapped[date] = mapped_column(Date, default=date.today)
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now, onupdate=now)
    __table_args__ = (CheckConstraint('birth_date IS NULL OR birth_date <= registration_date', name='cow_dates'),)

class Image(Identity, Created, Base):
    __tablename__ = 'images'
    image_path: Mapped[str] = mapped_column(String(1000), unique=True)
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    camera_angle: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(120))
    quality_status: Mapped[str] = mapped_column(String(30), default='unreviewed')

class ImageCow(Identity, Created, Base):
    __tablename__ = 'image_cows'
    image_id: Mapped[int] = mapped_column(ForeignKey('images.id', ondelete='RESTRICT'), index=True)
    cow_id: Mapped[int] = mapped_column(ForeignKey('cows.id', ondelete='RESTRICT'), index=True)
    crop_path: Mapped[str | None] = mapped_column(String(1000))
    segmentation_mask_path: Mapped[str | None] = mapped_column(String(1000))
    bounding_box: Mapped[dict | None] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint('image_id', 'cow_id'), UniqueConstraint('id', 'cow_id'))

class ScoringStandard(Identity, Created, Base):
    __tablename__ = 'scoring_standards'
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(120))
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    minimum_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    maximum_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    __table_args__ = (
        CheckConstraint('minimum_score IS NULL OR maximum_score IS NULL OR minimum_score <= maximum_score', name='standard_range'),
        CheckConstraint('(approved_by IS NULL AND approved_at IS NULL) OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)', name='standard_approval_pair'),
    )

class BCSCategory(Identity, Base):
    __tablename__ = 'bcs_categories'
    scoring_standard: Mapped[str] = mapped_column(ForeignKey('scoring_standards.name', ondelete='RESTRICT'))
    category: Mapped[str] = mapped_column(String(80))
    __table_args__ = (UniqueConstraint('scoring_standard', 'category'),)

class BCSRecord(Identity, Created, Base):
    __tablename__ = 'bcs_records'
    cow_id: Mapped[int] = mapped_column(ForeignKey('cows.id', ondelete='RESTRICT'))
    image_cow_id: Mapped[int | None] = mapped_column()
    bcs_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    bcs_category: Mapped[str | None] = mapped_column(String(80))
    scoring_standard: Mapped[str] = mapped_column(ForeignKey('scoring_standards.name', ondelete='RESTRICT'))
    evaluator: Mapped[str] = mapped_column(String(120))
    evaluation_method: Mapped[str] = mapped_column(String(80))
    evaluation_date: Mapped[datetime] = mapped_column(UTCDateTime())
    review_status: Mapped[str] = mapped_column(String(30), default='pending')
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        ForeignKeyConstraint(['image_cow_id', 'cow_id'], ['image_cows.id', 'image_cows.cow_id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['scoring_standard', 'bcs_category'], ['bcs_categories.scoring_standard', 'bcs_categories.category'], ondelete='RESTRICT'),
        CheckConstraint('bcs_score IS NOT NULL OR bcs_category IS NOT NULL', name='bcs_label_required'),
        CheckConstraint("review_status IN ('pending','approved','rejected')", name='bcs_review'),
        CheckConstraint("evaluation_method IN ('manual','veterinary')", name='manual_bcs_only'),
        Index('ix_bcs_cow_date', 'cow_id', 'evaluation_date'))

class WeightRecord(Identity, Base):
    __tablename__ = 'weight_records'
    cow_id: Mapped[int] = mapped_column(ForeignKey('cows.id', ondelete='RESTRICT'))
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    measurement_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    measurement_context: Mapped[str] = mapped_column(String(30))
    measurement_method: Mapped[str] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint('weight_kg >= 0', name='weight_nonnegative'), CheckConstraint("measurement_context IN ('before_feeding','after_feeding','routine')", name='weight_context'), Index('ix_weight_cow_time', 'cow_id', 'measurement_timestamp'))

class FeedingRecord(Identity, Base):
    __tablename__ = 'feeding_records'
    cow_id: Mapped[int] = mapped_column(ForeignKey('cows.id', ondelete='RESTRICT'))
    feeding_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    feed_type: Mapped[str] = mapped_column(String(120))
    quantity_offered_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    quantity_consumed_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint('quantity_offered_kg >= 0', name='offered_nonnegative'), CheckConstraint('quantity_consumed_kg IS NULL OR (quantity_consumed_kg >= 0 AND quantity_consumed_kg <= quantity_offered_kg)', name='consumed_range'), Index('ix_feeding_cow_time', 'cow_id', 'feeding_timestamp'))

class HealthRecord(Identity, Created, Base):
    __tablename__ = 'health_records'
    cow_id: Mapped[int] = mapped_column(ForeignKey('cows.id', ondelete='RESTRICT'))
    observation_date: Mapped[datetime] = mapped_column(UTCDateTime())
    observation_type: Mapped[str] = mapped_column(String(120))
    symptoms_or_observations: Mapped[str] = mapped_column(Text)
    veterinarian_notes: Mapped[str | None] = mapped_column(Text)
    follow_up_status: Mapped[str] = mapped_column(String(80), default='pending')
    __table_args__ = (Index('ix_health_cow_date', 'cow_id', 'observation_date'),)

class MilkProduction(Identity, Base):
    __tablename__ = 'milk_production'
    cow_id: Mapped[int] = mapped_column(ForeignKey('cows.id', ondelete='RESTRICT'))
    measurement_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    milk_quantity_liters: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    milking_session: Mapped[str] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint('milk_quantity_liters >= 0', name='milk_nonnegative'), Index('ix_milk_cow_time', 'cow_id', 'measurement_timestamp'))

class AIPrediction(Identity, Base):
    __tablename__ = 'ai_predictions'
    cow_id: Mapped[int] = mapped_column(ForeignKey('cows.id', ondelete='RESTRICT'))
    image_cow_id: Mapped[int] = mapped_column()
    model_name: Mapped[str] = mapped_column(String(120))
    model_version: Mapped[str] = mapped_column(String(120))
    predicted_bcs_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    predicted_category: Mapped[str | None] = mapped_column(String(80))
    scoring_standard: Mapped[str] = mapped_column(ForeignKey('scoring_standards.name', ondelete='RESTRICT'))
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    prediction_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    __table_args__ = (
        ForeignKeyConstraint(['image_cow_id', 'cow_id'], ['image_cows.id', 'image_cows.cow_id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['scoring_standard', 'predicted_category'], ['bcs_categories.scoring_standard', 'bcs_categories.category'], ondelete='RESTRICT'),
        CheckConstraint('predicted_bcs_score IS NOT NULL OR predicted_category IS NOT NULL', name='prediction_required'),
        CheckConstraint('confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)', name='confidence_range'),
        Index('ix_prediction_cow_time', 'cow_id', 'prediction_timestamp'))

class ImportRow(Identity, Base):
    __tablename__ = 'import_rows'
    resource: Mapped[str] = mapped_column(String(80))
    external_key: Mapped[str] = mapped_column(String(200))
    payload_hash: Mapped[str] = mapped_column(String(64))
    record_id: Mapped[int]
    __table_args__ = (UniqueConstraint('resource', 'external_key'),)

class AssessmentWorkflow(Identity, Created, Base):
    __tablename__ = 'assessment_workflows'
    cow_id: Mapped[int] = mapped_column(ForeignKey('cows.id', ondelete='RESTRICT'))
    image_cow_id: Mapped[int] = mapped_column(unique=True)
    scoring_standard: Mapped[str] = mapped_column(ForeignKey('scoring_standards.name', ondelete='RESTRICT'))
    mode: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default='pending')
    created_by: Mapped[str] = mapped_column(String(120))
    request_key: Mapped[str] = mapped_column(String(120))
    bcs_record_id: Mapped[int | None] = mapped_column(ForeignKey('bcs_records.id', ondelete='RESTRICT'), unique=True)
    prediction_id: Mapped[int | None] = mapped_column(ForeignKey('ai_predictions.id', ondelete='RESTRICT'), unique=True)
    finalized_by: Mapped[str | None] = mapped_column(String(120))
    finalized_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    review_notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        ForeignKeyConstraint(['image_cow_id', 'cow_id'], ['image_cows.id', 'image_cows.cow_id'], ondelete='RESTRICT'),
        UniqueConstraint('created_by', 'request_key', name='workflow_request_unique'),
        CheckConstraint("mode IN ('manual','ai')", name='workflow_mode'),
        CheckConstraint("status IN ('pending','approved','corrected','rejected')", name='workflow_status'),
        CheckConstraint("(status = 'pending' AND finalized_by IS NULL AND finalized_at IS NULL) OR (status <> 'pending' AND finalized_by IS NOT NULL AND finalized_at IS NOT NULL)", name='workflow_finalizer'),
        CheckConstraint("status NOT IN ('approved','corrected') OR bcs_record_id IS NOT NULL", name='workflow_final_label'),
        CheckConstraint("mode = 'ai' OR prediction_id IS NULL", name='workflow_ai_prediction'),
        Index('ix_workflow_status_created', 'status', 'created_at'),
        Index('ix_workflow_cow_created', 'cow_id', 'created_at'),
    )

