from typing import Annotated
from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import Json
from sqlalchemy.orm import Session
from .auth import Principal, authenticate, veterinarian, inference_service
from .db import get_session
from .services import require
from .models import AssessmentWorkflow
from .workflow_schemas import StartWorkflow, WorkflowReview, PredictionSubmission, WorkflowOut
from . import workflows

router = APIRouter(prefix='/assessment-workflows', tags=['Veterinary workflows'])

@router.post('', response_model=WorkflowOut, status_code=201,
    description='Multipart file plus payload JSON. Server derives veterinarian identity and approval permission. '
                'Manual submissions save a score; AI submissions stay pending without inventing predictions. '
                'request_key is unique per authenticated creator; retries return 409.')
def start_workflow(file: Annotated[UploadFile, File()],
    payload: Annotated[Json[StartWorkflow], Form(description='JSON StartWorkflow metadata; see WORKFLOWS.md')],
    principal: Annotated[Principal, Depends(veterinarian)], session: Session = Depends(get_session)):
    return workflows.start(session, file, payload, principal)

@router.get('/{workflow_id}', response_model=WorkflowOut)
def get_workflow(workflow_id: int, principal: Annotated[Principal, Depends(authenticate)], session: Session = Depends(get_session)):
    return workflows.present(session, require(session, AssessmentWorkflow, workflow_id))

@router.post('/{workflow_id}/prediction', response_model=WorkflowOut, status_code=201,
    description='AI-service credentials only. Submit a real prediction once; cow, image and standard are derived from the pending workflow.')
def prediction(workflow_id: int, payload: PredictionSubmission,
    principal: Annotated[Principal, Depends(inference_service)], session: Session = Depends(get_session)):
    return workflows.submit_prediction(session, workflow_id, payload)

@router.post('/{workflow_id}/review', response_model=WorkflowOut,
    description='Approving veterinarians only. Approve, correct, or reject a pending workflow exactly once. Original AI predictions remain unchanged.')
def review(workflow_id: int, payload: WorkflowReview,
    principal: Annotated[Principal, Depends(veterinarian)], session: Session = Depends(get_session)):
    return workflows.review(session, workflow_id, payload, principal)
