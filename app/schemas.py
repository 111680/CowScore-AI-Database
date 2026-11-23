from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, model_validator, field_validator, computed_field

Text = Annotated[str, Field(min_length=1, max_length=120)]
Amount = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=3)]
Score = Annotated[Decimal, Field(max_digits=8, decimal_places=3)]
ID = Annotated[int, Field(gt=0)]
PathText = Annotated[str, Field(min_length=1, max_length=1000)]

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, allow_inf_nan=False)

    @field_validator('*', mode='after')
    @classmethod
    def safe_paths(cls, value, info):
        if info.field_name.endswith('_path') and value is not None:
            from pathlib import PurePosixPath
            normalized = value.replace('\\', '/')
            if PurePosixPath(normalized).is_absolute() or '..' in normalized.split('/') or ':' in normalized:
                raise ValueError('Storage paths must be relative and cannot contain traversal or drive names')
            normalized = str(PurePosixPath(normalized))
            if normalized == '.':
                raise ValueError('Storage paths must identify a file')
            return normalized
        return value

class CowCreate(Input):
    cow_identifier: Text
    breed: Text | None = None
    sex: Literal['female', 'male', 'unknown'] | None = None
    birth_date: date | None = None
    registration_date: date = Field(default_factory=date.today)
    notes: str | None = None

    @model_validator(mode='after')
    def dates(self):
        if self.registration_date > date.today() or (self.birth_date and self.birth_date > self.registration_date):
            raise ValueError('Birth must precede registration; registration cannot be in the future')
        return self

class CowUpdate(Input):
    cow_identifier: Text | None = None
    breed: Text | None = None
    sex: Literal['female', 'male', 'unknown'] | None = None
    birth_date: date | None = None
    registration_date: date | None = None
    notes: str | None = None

class ImageCreate(Input):
    image_path: PathText
    captured_at: AwareDatetime
    camera_angle: Text | None = None
    source: Text
    quality_status: Literal['unreviewed', 'accepted', 'rejected'] = 'unreviewed'

class ImageCowCreate(Input):
    image_id: ID
    cow_id: ID
    crop_path: PathText | None = None
    segmentation_mask_path: PathText | None = None
    bounding_box: dict[str, float] | None = None

    @field_validator('bounding_box')
    @classmethod
    def box(cls, v):
        import math
        if v is not None and (set(v) != {'x', 'y', 'width', 'height'} or any(not math.isfinite(n) for n in v.values()) or v['x'] < 0 or v['y'] < 0 or v['width'] <= 0 or v['height'] <= 0):
            raise ValueError('Bounding box requires nonnegative x,y and positive width,height in pixels')
        return v

class ImageCowUpdate(Input):
    crop_path: PathText | None = None
    segmentation_mask_path: PathText | None = None
    bounding_box: dict[str, float] | None = None

class StandardCreate(Input):
    name: Text
    description: str | None = None
    approved_by: Text | None = None
    approved_at: AwareDatetime | None = None
    minimum_score: Score | None = None
    maximum_score: Score | None = None
    categories: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(min_length=1)

    @model_validator(mode='after')
    def ranges(self):
        if (self.approved_by is None) != (self.approved_at is None):
            raise ValueError('Supply both approved_by and approved_at, or leave both null for a draft')
        if len(set(self.categories)) != len(self.categories):
            raise ValueError('Categories must be unique')
        if self.minimum_score is not None and self.maximum_score is not None and self.minimum_score > self.maximum_score:
            raise ValueError('Invalid score range')
        return self

class BCSCreate(Input):
    cow_id: ID
    image_cow_id: ID | None = None
    bcs_score: Score | None = None
    bcs_category: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    scoring_standard: Text
    evaluator: Text
    evaluation_method: Literal['manual', 'veterinary']
    evaluation_date: AwareDatetime
    review_status: Literal['pending', 'approved', 'rejected'] = 'pending'
    notes: str | None = None

    @model_validator(mode='after')
    def label(self):
        if self.bcs_score is None and self.bcs_category is None:
            raise ValueError('A numeric score or category is required')
        return self

class BCSUpdate(Input):
    bcs_score: Score | None = None
    bcs_category: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    evaluator: Text | None = None
    evaluation_method: Literal['manual', 'veterinary'] | None = None
    evaluation_date: AwareDatetime | None = None
    review_status: Literal['pending', 'approved', 'rejected'] | None = None
    notes: str | None = None

class WeightCreate(Input):
    cow_id: ID
    weight_kg: Amount
    measurement_timestamp: AwareDatetime
    measurement_context: Literal['before_feeding', 'after_feeding', 'routine']
    measurement_method: Text
    notes: str | None = None

class FeedingCreate(Input):
    cow_id: ID
    feeding_timestamp: AwareDatetime
    feed_type: Text
    quantity_offered_kg: Amount
    quantity_consumed_kg: Amount | None = None
    notes: str | None = None

    @model_validator(mode='after')
    def consumed(self):
        if self.quantity_consumed_kg is not None and self.quantity_consumed_kg > self.quantity_offered_kg:
            raise ValueError('Consumed quantity cannot exceed offered quantity')
        return self

class HealthCreate(Input):
    cow_id: ID
    observation_date: AwareDatetime
    observation_type: Text
    symptoms_or_observations: Annotated[str, Field(min_length=1)]
    veterinarian_notes: str | None = None
    follow_up_status: Annotated[str, Field(min_length=1, max_length=80)] = 'pending'

class MilkCreate(Input):
    cow_id: ID
    measurement_timestamp: AwareDatetime
    milk_quantity_liters: Amount
    milking_session: Annotated[str, Field(min_length=1, max_length=80)]
    notes: str | None = None

class PredictionCreate(Input):
    cow_id: ID
    image_cow_id: ID
    model_name: Text
    model_version: Text
    predicted_bcs_score: Score | None = None
    predicted_category: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    scoring_standard: Text
    confidence_score: Annotated[Decimal, Field(ge=0, le=1, max_digits=8, decimal_places=6)] | None = None
    prediction_timestamp: AwareDatetime

    @model_validator(mode='after')
    def label(self):
        if self.predicted_bcs_score is None and self.predicted_category is None:
            raise ValueError('A prediction score or category is required')
        return self

# Responses include persisted server fields and validate ORM objects.
from pydantic import create_model
from datetime import datetime

def response(name, schema, *, created=False, updated=False):
    fields = {'id': (int, ...)}
    if created:
        fields['created_at'] = (datetime, ...)
    if updated:
        fields['updated_at'] = (datetime, ...)
    result = create_model(name, __base__=schema, **fields)
    result.model_config = ConfigDict(from_attributes=True, extra='ignore')
    result.model_rebuild(force=True)
    return result

CowOut = response('CowOut', CowCreate, created=True, updated=True)
ImageOut = response('ImageOut', ImageCreate, created=True)
class ImageUploadOut(ImageOut):
    image_format: Literal['JPEG', 'PNG']
    width: int
    height: int
    size_bytes: int

ImageCowOut = response('ImageCowOut', ImageCowCreate, created=True)
BCSOut = response('BCSOut', BCSCreate, created=True)
WeightOut = response('WeightOut', WeightCreate)
FeedingOut = response('FeedingOut', FeedingCreate)
HealthOut = response('HealthOut', HealthCreate, created=True)
MilkOut = response('MilkOut', MilkCreate)
PredictionOut = response('PredictionOut', PredictionCreate)
class StandardOut(response('StandardResponseFields', StandardCreate, created=True)):
    @computed_field
    @property
    def approval_status(self) -> Literal['draft', 'veterinary_approved']:
        return 'draft' if self.approved_by is None else 'veterinary_approved'
