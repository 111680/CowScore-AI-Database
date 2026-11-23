from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from . import models as m

def require(session, model, identity):
    obj = session.get(model, identity)
    if obj is None:
        raise HTTPException(404, f'{model.__tablename__} record not found')
    return obj

def validate_record(session, model, data):
    if 'cow_id' in data:
        require(session, m.Cow, data['cow_id'])
    if model is m.ImageCow:
        require(session, m.Image, data['image_id'])
    if data.get('image_cow_id') is not None:
        association = require(session, m.ImageCow, data['image_cow_id'])
        if association.cow_id != data['cow_id']:
            raise HTTPException(422, 'Image association belongs to a different cow')
    if model in (m.BCSRecord, m.AIPrediction):
        standard = session.scalar(select(m.ScoringStandard).where(m.ScoringStandard.name == data['scoring_standard']))
        if standard is None:
            raise HTTPException(422, 'Register a scoring standard first')
        if model is m.BCSRecord and data.get('review_status') == 'approved' and standard.approved_by is None:
            raise HTTPException(422, 'Assessments using a draft scoring standard cannot be approved')
        score = data.get('bcs_score', data.get('predicted_bcs_score'))
        if score is not None and ((standard.minimum_score is not None and score < standard.minimum_score) or (standard.maximum_score is not None and score > standard.maximum_score)):
            raise HTTPException(422, 'Score is outside the configured scoring standard')
        category = data.get('bcs_category', data.get('predicted_category'))
        if category is not None and session.scalar(select(m.BCSCategory.id).where(m.BCSCategory.scoring_standard == standard.name, m.BCSCategory.category == category)) is None:
            raise HTTPException(422, 'Category is not configured for this scoring standard')

def create(session, model, data):
    validate_record(session, model, data)
    obj = model(**data)
    session.add(obj)
    session.flush()
    return obj

def commit(session):
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, 'Duplicate record or database constraint violation') from exc
