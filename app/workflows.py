"""Transactional workflow orchestration using existing validation/storage services."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from . import models as m, schemas as s
from .auth import require_approval
from .services import create, require, validate_record
from .uploads import store_upload
from .workflow_schemas import WorkflowOut

def standard_for(session, name):
    standard = session.scalar(select(m.ScoringStandard).where(m.ScoringStandard.name == name).with_for_update())
    if standard is None:
        raise HTTPException(422, 'Register the selected scoring standard first')
    return standard

def is_approved(standard):
    return standard.approved_by is not None and standard.approved_at is not None

def present(session, workflow):
    association = require(session, m.ImageCow, workflow.image_cow_id)
    image = require(session, m.Image, association.image_id)
    label = session.get(m.BCSRecord, workflow.bcs_record_id) if workflow.bcs_record_id else None
    prediction = session.get(m.AIPrediction, workflow.prediction_id) if workflow.prediction_id else None
    return WorkflowOut(
        **{key: getattr(workflow, key) for key in ['id', 'cow_id', 'image_cow_id', 'scoring_standard', 'mode', 'status', 'created_by', 'request_key', 'created_at', 'finalized_by', 'finalized_at', 'review_notes', 'bcs_record_id', 'prediction_id']},
        image_id=image.id, image_path=image.image_path,
        review_status=label.review_status if label else ('rejected' if workflow.status == 'rejected' else 'pending'),
        assessment=s.BCSOut.model_validate(label) if label else None,
        prediction=s.PredictionOut.model_validate(prediction) if prediction else None,
        inference_status='not_requested' if workflow.mode == 'manual' else 'prediction_available' if prediction else 'awaiting_prediction',
    )

def start(session, file, payload, principal):
    previous = session.scalar(select(m.AssessmentWorkflow.id).where(m.AssessmentWorkflow.created_by == principal.subject, m.AssessmentWorkflow.request_key == payload.request_key))
    if previous is not None:
        raise HTTPException(409, {'message': 'Request key already used; retrieve the existing workflow', 'workflow_id': previous})
    standard = standard_for(session, payload.scoring_standard)
    if payload.cow_id is not None:
        require(session, m.Cow, payload.cow_id)

    def attach(image):
        cow = require(session, m.Cow, payload.cow_id) if payload.cow_id else create(session, m.Cow, payload.new_cow.model_dump())
        association = create(session, m.ImageCow, dict(cow_id=cow.id, image_id=image.id))
        workflow = m.AssessmentWorkflow(cow_id=cow.id, image_cow_id=association.id,
            mode=payload.mode, scoring_standard=standard.name, created_by=principal.subject,
            request_key=payload.request_key, status='pending')
        if payload.mode == 'manual':
            approved = principal.can_approve and is_approved(standard)
            label = s.BCSCreate(cow_id=cow.id, image_cow_id=association.id,
                scoring_standard=standard.name, bcs_score=payload.bcs_score,
                bcs_category=payload.bcs_category, evaluator=principal.subject,
                evaluation_method='veterinary', evaluation_date=m.now(),
                review_status='approved' if approved else 'pending', notes=payload.notes)
            record = create(session, m.BCSRecord, label.model_dump())
            workflow.bcs_record_id = record.id
            if approved:
                workflow.status = 'approved'
                workflow.finalized_by, workflow.finalized_at = principal.subject, m.now()
        session.add(workflow)
        session.flush()
        return present(session, workflow)

    return store_upload(file, payload.image.model_dump(), session, after_create=attach)

def locked_pending(session, identity):
    workflow = session.scalar(select(m.AssessmentWorkflow).where(m.AssessmentWorkflow.id == identity)
        .with_for_update().execution_options(populate_existing=True))
    if workflow is None:
        raise HTTPException(404, 'Assessment workflow not found')
    if workflow.status != 'pending':
        raise HTTPException(409, 'Assessment workflow is already finalized')
    return workflow

def finish_transaction(session, operation):
    try:
        result = operation()
        session.commit()
        return result
    except Exception as exc:
        session.rollback()
        if isinstance(exc, IntegrityError):
            raise HTTPException(409, 'Duplicate workflow operation or conflicting record') from exc
        if isinstance(exc, SQLAlchemyError):
            raise HTTPException(503, 'Workflow database is unavailable') from exc
        raise

def submit_prediction(session, identity, payload):
    def operation():
        workflow = locked_pending(session, identity)
        if workflow.mode != 'ai':
            raise HTTPException(409, 'Manual workflow cannot receive an AI prediction')
        if workflow.prediction_id is not None:
            raise HTTPException(409, 'A prediction is already stored for this workflow')
        # Ownership and standard come from the workflow, not the AI caller.
        validated = s.PredictionCreate(**payload.model_dump(), cow_id=workflow.cow_id,
            image_cow_id=workflow.image_cow_id, scoring_standard=workflow.scoring_standard)
        prediction = create(session, m.AIPrediction, validated.model_dump())
        workflow.prediction_id = prediction.id
        session.flush()
        return present(session, workflow)
    return finish_transaction(session, operation)

def review(session, identity, payload, principal):
    require_approval(principal)
    def operation():
        workflow = locked_pending(session, identity)
        label = session.get(m.BCSRecord, workflow.bcs_record_id) if workflow.bcs_record_id else None
        if payload.action == 'reject':
            if label:
                label.review_status = 'rejected'
            workflow.status = 'rejected'
        else:
            standard = standard_for(session, workflow.scoring_standard)
            if not is_approved(standard):
                raise HTTPException(422, 'Veterinary-approved scoring standard required to finalize')
            prediction = session.get(m.AIPrediction, workflow.prediction_id) if workflow.prediction_id else None
            if workflow.mode == 'ai' and prediction is None:
                raise HTTPException(409, 'Awaiting a real AI prediction; no assessment can be approved yet')
            score = payload.bcs_score if payload.action == 'correct' else prediction.predicted_bcs_score if prediction else label.bcs_score
            category = payload.bcs_category if payload.action == 'correct' else prediction.predicted_category if prediction else label.bcs_category
            data = s.BCSCreate(cow_id=workflow.cow_id, image_cow_id=workflow.image_cow_id,
                scoring_standard=standard.name, bcs_score=score, bcs_category=category,
                evaluator=principal.subject, evaluation_method='veterinary', evaluation_date=m.now(),
                review_status='approved', notes=payload.notes)
            if label:
                validate_record(session, m.BCSRecord, data.model_dump())
                for key, value in data.model_dump().items():
                    setattr(label, key, value)
            else:
                label = create(session, m.BCSRecord, data.model_dump())
                workflow.bcs_record_id = label.id
            workflow.status = 'corrected' if payload.action == 'correct' else 'approved'
        workflow.finalized_by, workflow.finalized_at = principal.subject, m.now()
        workflow.review_notes = payload.notes
        session.flush()
        return present(session, workflow)
    return finish_transaction(session, operation)
