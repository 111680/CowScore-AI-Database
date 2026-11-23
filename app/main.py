from fastapi import FastAPI, Depends, Query, HTTPException, Request, UploadFile, File, Form
from typing import Annotated, Literal
from pydantic import AwareDatetime
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .db import get_session
from . import models as m, schemas as s
from .services import require, create, commit, validate_record
from .uploads import store_upload
from .dataset_routes import router as dataset_router
from .workflow_routes import router as workflow_router
from .auth import Principal, authenticate, veterinarian, require_approval

app = FastAPI(title='CowScore AI', version='1.0.0', description='Cattle history and dataset metadata API. BCS categories require an explicitly configured veterinary standard.')
app.include_router(dataset_router)
app.include_router(workflow_router)

@app.post('/images/upload', response_model=s.ImageUploadOut, status_code=201,
          tags=['Images'], summary='Upload a validated JPEG or PNG image',
          description='Multipart image upload. Required fields: file, captured_at (with timezone), source. '
                      'Validates actual format, full decoding, byte and pixel limits. Stores a unique '
                      'relative original/ path and image metadata; no AI processing. '
                      'Defaults: 10 MiB and 20 million pixels, configurable via environment.',
          responses={413: {'description': 'Byte or pixel limit exceeded'},
                     415: {'description': 'Unsupported or mismatched format'},
                     422: {'description': 'Invalid metadata or corrupt image'},
                     409: {'description': 'Metadata conflict'},
                     503: {'description': 'Storage or database unavailable'}})
def upload_image(
    file: Annotated[UploadFile, File(description='Single JPG, JPEG or PNG image')],
    captured_at: Annotated[AwareDatetime, Form()],
    source: Annotated[str, Form(min_length=1, max_length=120, pattern=r'.*\S.*')],
    principal: Annotated[Principal, Depends(veterinarian)],
    camera_angle: Annotated[str | None, Form(min_length=1, max_length=120, pattern=r'.*\S.*')] = None,
    quality_status: Annotated[Literal['unreviewed', 'accepted', 'rejected'], Form()] = 'unreviewed',
    session: Session = Depends(get_session),
):
    return store_upload(file, dict(captured_at=captured_at, source=source,
                                 camera_angle=camera_angle, quality_status=quality_status), session)

@app.exception_handler(IntegrityError)
async def integrity_error(request: Request, exc):
    return JSONResponse(status_code=409, content={'detail': 'Duplicate record or database constraint violation'})

@app.get('/health')
def health(session: Session = Depends(get_session)):
    session.execute(text('SELECT 1'))
    return {'status': 'ok'}

@app.post('/cows', response_model=s.CowOut, status_code=201)
def create_cow(payload: s.CowCreate, session: Session = Depends(get_session)):
    obj = create(session, m.Cow, payload.model_dump())
    commit(session)
    return obj

@app.get('/cows', response_model=list[s.CowOut])
def cows(offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000), session: Session = Depends(get_session)):
    return session.scalars(select(m.Cow).order_by(m.Cow.id).offset(offset).limit(limit)).all()

@app.get('/cows/{cow_id}', response_model=s.CowOut)
def cow(cow_id: int, session: Session = Depends(get_session)):
    return require(session, m.Cow, cow_id)

def patch(session, model, identity, payload, full_schema):
    obj = require(session, model, identity)
    data = {name: getattr(obj, name) for name in full_schema.model_fields}
    data.update(payload.model_dump(exclude_unset=True))
    try:
        validated = full_schema.model_validate(data).model_dump()
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    validate_record(session, model, validated)
    for name, value in validated.items():
        setattr(obj, name, value)
    commit(session)
    return obj

@app.patch('/cows/{cow_id}', response_model=s.CowOut)
def update_cow(cow_id: int, payload: s.CowUpdate, session: Session = Depends(get_session)):
    return patch(session, m.Cow, cow_id, payload, s.CowCreate)

@app.patch('/bcs/{record_id}', response_model=s.BCSOut)
def update_bcs(record_id: int, payload: s.BCSUpdate, principal: Annotated[Principal, Depends(veterinarian)], session: Session = Depends(get_session)):
    record = session.scalar(select(m.BCSRecord).where(m.BCSRecord.id == record_id).with_for_update())
    if record is None:
        raise HTTPException(404, 'BCS record not found')
    if session.scalar(select(m.AssessmentWorkflow.id).where(m.AssessmentWorkflow.bcs_record_id == record_id)):
        raise HTTPException(409, 'Use the workflow review endpoint for this assessment')
    if record.review_status in ('approved', 'rejected'):
        raise HTTPException(409, 'Finalized assessment is immutable; submit a new assessment')
    if payload.review_status == 'approved':
        require_approval(principal)
    payload = payload.model_copy(update={'evaluator': principal.subject, 'evaluation_date': m.now(), 'evaluation_method': 'veterinary'})
    return patch(session, m.BCSRecord, record_id, payload, s.BCSCreate)

@app.patch('/image-cows/{record_id}', response_model=s.ImageCowOut)
def update_association(record_id: int, payload: s.ImageCowUpdate, session: Session = Depends(get_session)):
    if session.scalar(select(m.AssessmentWorkflow.id).where(m.AssessmentWorkflow.image_cow_id == record_id)):
        raise HTTPException(409, 'Workflow image associations are immutable')
    return patch(session, m.ImageCow, record_id, payload, s.ImageCowCreate)

@app.post('/scoring-standards', response_model=s.StandardOut, status_code=201)
def standard(payload: s.StandardCreate, principal: Annotated[Principal, Depends(veterinarian)], session: Session = Depends(get_session)):
    data = payload.model_dump(exclude={'categories'})
    if payload.approved_by is not None:
        require_approval(principal)
        data.update(approved_by=principal.subject, approved_at=m.now())
    obj = m.ScoringStandard(**data)
    session.add(obj)
    session.flush()
    session.add_all([m.BCSCategory(scoring_standard=obj.name, category=category) for category in payload.categories])
    commit(session)
    return {'id': obj.id, 'created_at': obj.created_at, **data, 'categories': payload.categories}

@app.post('/bcs', response_model=s.BCSOut, status_code=201)
def add_bcs(payload: s.BCSCreate, principal: Annotated[Principal, Depends(veterinarian)], session: Session = Depends(get_session)):
    if payload.image_cow_id and session.scalar(select(m.AssessmentWorkflow.id).where(m.AssessmentWorkflow.image_cow_id == payload.image_cow_id)):
        raise HTTPException(409, 'Use the workflow review endpoint for this image association')
    if payload.review_status == 'approved':
        require_approval(principal)
    data = payload.model_dump()
    data.update(evaluator=principal.subject, evaluation_date=m.now(), evaluation_method='veterinary')
    obj = create(session, m.BCSRecord, data)
    commit(session)
    return obj

@app.post('/predictions', response_model=s.PredictionOut, status_code=201)
def add_prediction(payload: s.PredictionCreate, principal: Annotated[Principal, Depends(authenticate)], session: Session = Depends(get_session)):
    if session.scalar(select(m.AssessmentWorkflow.id).where(m.AssessmentWorkflow.image_cow_id == payload.image_cow_id)):
        raise HTTPException(409, 'Use the workflow prediction endpoint for this image association')
    obj = create(session, m.AIPrediction, payload.model_dump())
    commit(session)
    return obj

@app.get('/scoring-standards', response_model=list[s.StandardOut])
def standards(session: Session = Depends(get_session)):
    return [{'id': obj.id, 'created_at': obj.created_at, 'name': obj.name, 'description': obj.description, 'approved_by': obj.approved_by, 'approved_at': obj.approved_at, 'minimum_score': obj.minimum_score, 'maximum_score': obj.maximum_score, 'categories': list(session.scalars(select(m.BCSCategory.category).where(m.BCSCategory.scoring_standard == obj.name)))} for obj in session.scalars(select(m.ScoringStandard).order_by(m.ScoringStandard.id))]

def register_resource(path, model, schema, output, timestamp):
    # Separate closures retain concrete annotations for FastAPI/OpenAPI.
    def add(payload, session: Session = Depends(get_session)):
        obj = create(session, model, payload.model_dump())
        commit(session)
        return obj
    add.__annotations__['payload'] = schema
    add.__name__ = 'create_' + model.__tablename__
    if model not in (m.BCSRecord, m.AIPrediction):
        app.post('/' + path, response_model=output, status_code=201)(add)

    if model is m.Image:
        return
    def history(cow_id: int, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000), session: Session = Depends(get_session)):
        require(session, m.Cow, cow_id)
        return session.scalars(select(model).where(model.cow_id == cow_id).order_by(getattr(model, timestamp).desc(), model.id.desc()).offset(offset).limit(limit)).all()
    history.__name__ = 'history_' + model.__tablename__
    app.get('/cows/{cow_id}/' + path, response_model=list[output])(history)

for config in [
    ('images', m.Image, s.ImageCreate, s.ImageOut, 'captured_at'),
    ('image-cows', m.ImageCow, s.ImageCowCreate, s.ImageCowOut, 'created_at'),
    ('bcs', m.BCSRecord, s.BCSCreate, s.BCSOut, 'evaluation_date'),
    ('weights', m.WeightRecord, s.WeightCreate, s.WeightOut, 'measurement_timestamp'),
    ('feeding', m.FeedingRecord, s.FeedingCreate, s.FeedingOut, 'feeding_timestamp'),
    ('health-records', m.HealthRecord, s.HealthCreate, s.HealthOut, 'observation_date'),
    ('milk', m.MilkProduction, s.MilkCreate, s.MilkOut, 'measurement_timestamp'),
    ('predictions', m.AIPrediction, s.PredictionCreate, s.PredictionOut, 'prediction_timestamp'),
]:
    register_resource(*config)

@app.get('/cows/{cow_id}/images', response_model=list[s.ImageOut])
def cow_images(cow_id: int, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000), session: Session = Depends(get_session)):
    require(session, m.Cow, cow_id)
    return session.scalars(select(m.Image).join(m.ImageCow).where(m.ImageCow.cow_id == cow_id).order_by(m.Image.captured_at.desc(), m.Image.id).offset(offset).limit(limit)).all()
