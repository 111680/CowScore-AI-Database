from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import Field, model_validator, ConfigDict, AwareDatetime
from .schemas import Input, Text, Score, ID, CowCreate, ImageCreate, BCSOut, PredictionOut

class WorkflowImage(Input):
    captured_at: AwareDatetime
    source: Text
    camera_angle: Text | None = None
    quality_status: Literal['unreviewed', 'accepted', 'rejected'] = 'unreviewed'

class StartWorkflow(Input):
    mode: Literal['manual', 'ai']
    request_key: Text
    cow_id: ID | None = None
    new_cow: CowCreate | None = None
    image: WorkflowImage
    scoring_standard: Text
    bcs_score: Score | None = None
    bcs_category: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    notes: str | None = None

    @model_validator(mode='after')
    def selection(self):
        if (self.cow_id is None) == (self.new_cow is None):
            raise ValueError('Select exactly one of cow_id and new_cow')
        if self.mode == 'manual' and self.bcs_score is None:
            raise ValueError('Manual workflow requires bcs_score')
        if self.mode == 'ai' and (self.bcs_score is not None or self.bcs_category is not None):
            raise ValueError('AI workflows start without an invented score or category')
        return self

class WorkflowReview(Input):
    action: Literal['approve', 'correct', 'reject']
    bcs_score: Score | None = None
    bcs_category: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    notes: str | None = None

    @model_validator(mode='after')
    def correction(self):
        if self.action == 'correct' and self.bcs_score is None:
            raise ValueError('Correction requires an explicit bcs_score')
        if self.action != 'correct' and (self.bcs_score is not None or self.bcs_category is not None):
            raise ValueError('Use correct to edit the proposed assessment')
        return self

class PredictionSubmission(Input):
    model_name: Text
    model_version: Text
    predicted_bcs_score: Score | None = None
    predicted_category: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    confidence_score: Annotated[Decimal, Field(ge=0, le=1, max_digits=8, decimal_places=6)] | None = None
    prediction_timestamp: AwareDatetime

    @model_validator(mode='after')
    def label(self):
        if self.predicted_bcs_score is None and self.predicted_category is None:
            raise ValueError('A real prediction score or category is required')
        return self

class WorkflowOut(Input):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cow_id: int
    image_id: int
    image_cow_id: int
    image_path: str
    scoring_standard: str
    mode: Literal['manual', 'ai']
    status: Literal['pending', 'approved', 'corrected', 'rejected']
    review_status: Literal['pending', 'approved', 'rejected']
    created_by: str
    request_key: str
    created_at: datetime
    finalized_by: str | None
    finalized_at: datetime | None
    review_notes: str | None
    bcs_record_id: int | None
    prediction_id: int | None
    assessment: BCSOut | None
    prediction: PredictionOut | None
    inference_status: Literal['not_requested', 'awaiting_prediction', 'prediction_available']
