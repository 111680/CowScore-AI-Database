"""All credentials, images, standards and assessments in this module are synthetic."""
import csv
import json
from hashlib import sha256

import pytest
from sqlalchemy import select, func
from sqlalchemy.exc import OperationalError

from app import models as m
from app.db import settings, WorkflowCredential
from app.datasets import export_dataset
from test_api import bcs
from test_uploads import image_bytes
from test_standards import DRAFT

AI = {'Authorization': 'Bearer synthetic-ai-service-token-32'}
LIMITED = {'Authorization': 'Bearer synthetic-limited-veterinarian-token'}

@pytest.fixture
def setup(client, linked, tmp_path, monkeypatch, session):
    monkeypatch.setattr(settings, 'storage_root', tmp_path / 'images')
    standard = session.scalar(select(m.ScoringStandard).where(m.ScoringStandard.name == 'SYNTHETIC-TEST-ONLY'))
    # Synthetic range only, configured explicitly; not a veterinary recommendation.
    standard.minimum_score, standard.maximum_score = 1, 5
    session.commit()
    return linked

def start(client, setup, mode='manual', changes=None, headers=None, content=None):
    cow, _, _ = setup
    payload = dict(mode=mode, request_key='synthetic-request-1', cow_id=cow['id'],
        image={'captured_at': '2025-01-01T00:00:00Z', 'source': 'synthetic-workflow'},
        scoring_standard='SYNTHETIC-TEST-ONLY')
    if mode == 'manual':
        payload.update(bcs_score=3, bcs_category='Normal')
    payload.update(changes or {})
    return client.post('/assessment-workflows',
        data={'payload': json.dumps(payload)}, files={'file': ('synthetic.png', content if content is not None else image_bytes(), 'image/png')},
        headers=headers or {})

def real_prediction(client, workflow_id, **changes):
    payload = dict(model_name='synthetic-test-only', model_version='test-v1',
        predicted_bcs_score=2.5, predicted_category='Normal', confidence_score=0.85,
        prediction_timestamp='2025-01-01T00:00:00Z')
    payload.update(changes)
    return client.post(f'/assessment-workflows/{workflow_id}/prediction', json=payload, headers=AI)

def count(session, model):
    return session.scalar(select(func.count()).select_from(model))

def test_manual_existing_cow(client, setup, session):
    response = start(client, setup)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['cow_id'] == setup[0]['id']
    assert result['status'] == result['review_status'] == 'approved'
    assert result['finalized_by'] == result['assessment']['evaluator'] == 'test-vet'
    assert result['bcs_record_id'] == result['assessment']['id']
    assert result['image_id'] != setup[1]['id']
    assert result['assessment']['evaluation_method'] == 'veterinary'
    assert result['prediction'] is None
    assert (settings.storage_root / result['image_path']).is_file()
    assert count(session, m.AssessmentWorkflow) == 1

def test_manual_new_cow(client, setup, session):
    response = start(client, setup, changes={'cow_id': None, 'new_cow': {'cow_identifier': 'SYNTHETIC-NEW-WORKFLOW'}})
    assert response.status_code == 201, response.text
    assert response.json()['cow_id'] != setup[0]['id']
    assert count(session, m.Cow) == 2

def test_ai_stays_pending_without_predictions(client, setup, session):
    response = start(client, setup, mode='ai')
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['status'] == result['review_status'] == 'pending'
    assert result['inference_status'] == 'awaiting_prediction'
    assert result['bcs_record_id'] is None and result['prediction_id'] is None
    assert count(session, m.BCSRecord) == count(session, m.AIPrediction) == 0
    assert client.post(f"/assessment-workflows/{result['id']}/review", json={'action': 'approve'}).status_code == 409
    assert client.get(f"/assessment-workflows/{result['id']}", headers=AI).status_code == 200

@pytest.mark.parametrize('action,score,status', [('approve', None, 'approved'), ('correct', 4, 'corrected')])
def test_ai_review_and_preserved_prediction(client, setup, session, action, score, status):
    result = start(client, setup, mode='ai').json()
    prediction = real_prediction(client, result['id'])
    assert prediction.status_code == 201, prediction.text
    predicted = prediction.json()
    assert predicted['status'] == 'pending' and predicted['assessment'] is None
    assert float(predicted['prediction']['predicted_bcs_score']) == 2.5
    assert predicted['inference_status'] == 'prediction_available'
    body = {'action': action}
    if score is not None:
        body.update(bcs_score=score, notes='Synthetic vet correction')
    final = client.post(f"/assessment-workflows/{result['id']}/review", json=body)
    assert final.status_code == 200, final.text
    saved = final.json()
    assert saved['status'] == status and saved['review_status'] == 'approved'
    assert float(saved['assessment']['bcs_score']) == (score or 2.5)
    assert saved['assessment']['evaluator'] == saved['finalized_by'] == 'test-vet'
    assert float(saved['prediction']['predicted_bcs_score']) == 2.5
    if action == 'correct':
        assert saved['assessment']['bcs_category'] is None  # No invented threshold mapping.
    assert count(session, m.BCSRecord) == count(session, m.AIPrediction) == 1

def test_limited_vet_cannot_finalize(client, setup):
    result = start(client, setup, headers=LIMITED).json()
    assert result['status'] == 'pending'
    response = client.post(f"/assessment-workflows/{result['id']}/review", json={'action': 'approve'}, headers=LIMITED)
    assert response.status_code == 403
    assert client.post(f"/assessment-workflows/{result['id']}/review", json={'action': 'approve'}).json()['status'] == 'approved'

def test_unauthenticated_and_ai_cannot_act_as_vet(client, setup, session):
    client.headers.pop('Authorization')
    assert start(client, setup).status_code == 401
    assert start(client, setup, headers=AI).status_code == 403
    assert count(session, m.AssessmentWorkflow) == 0
    assert not settings.storage_root.exists()

def test_unconfigured_auth_fails_closed(client, setup, monkeypatch):
    monkeypatch.setattr(settings, 'workflow_credentials', {})
    assert start(client, setup).status_code == 503

def test_ai_service_cannot_finalize(client, setup):
    result = start(client, setup, mode='ai').json()
    assert real_prediction(client, result['id']).status_code == 201
    assert client.post(f"/assessment-workflows/{result['id']}/review", json={'action': 'approve'}, headers=AI).status_code == 403

def test_unknown_standard_and_cow_selection(client, setup):
    assert start(client, setup, changes={'scoring_standard': 'not-registered'}).status_code == 422
    assert start(client, setup, changes={'cow_id': None}).status_code == 422
    assert start(client, setup, changes={'new_cow': {'cow_identifier': 'SYNTHETIC-BOTH'}}).status_code == 422

def test_workflow_flush_failure_cleans_image(client, setup, session, monkeypatch):
    real_flush = session.flush
    def fail_on_workflow(*args, **kwargs):
        if any(isinstance(record, m.AssessmentWorkflow) for record in session.new):
            raise OperationalError('synthetic workflow flush failure', {}, Exception('test'))
        return real_flush(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(session, 'flush', fail_on_workflow)
        assert start(client, setup).status_code == 503
    assert count(session, m.AssessmentWorkflow) == count(session, m.BCSRecord) == 0
    assert count(session, m.Image) == 1
    assert not list(settings.storage_root.rglob('*.png'))

def test_credential_config_does_not_allow_role_escalation():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        WorkflowCredential(token_sha256=sha256(b'synthetic').hexdigest(), role='ai_service', can_approve=True)

def test_workflow_request_key_constraint(session, client, setup):
    from sqlalchemy.exc import IntegrityError
    first = start(client, setup, mode='ai').json()
    second = start(client, setup, mode='ai', changes={'request_key': 'synthetic-request-2'}).json()
    session.get(m.AssessmentWorkflow, second['id']).request_key = first['request_key']
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

def test_vet_cannot_submit_ai_prediction(client, setup):
    result = start(client, setup, mode='ai').json()
    response = client.post(f"/assessment-workflows/{result['id']}/prediction", json={
        'model_name': 'synthetic', 'model_version': 'test', 'predicted_bcs_score': 3,
        'prediction_timestamp': '2025-01-01T00:00:00Z'})
    assert response.status_code == 403

def test_duplicate_start_prediction_and_approval(client, setup, session):
    result = start(client, setup, mode='ai').json()
    assert start(client, setup, mode='ai').status_code == 409
    assert real_prediction(client, result['id']).status_code == 201
    assert real_prediction(client, result['id']).status_code == 409
    url = f"/assessment-workflows/{result['id']}/review"
    assert client.post(url, json={'action': 'approve'}).status_code == 200
    assert client.post(url, json={'action': 'approve'}).status_code == 409
    assert client.post(url, json={'action': 'correct', 'bcs_score': 4}).status_code == 409
    assert real_prediction(client, result['id']).status_code == 409
    assert count(session, m.AssessmentWorkflow) == count(session, m.BCSRecord) == count(session, m.AIPrediction) == 1
    assert len(list((settings.storage_root / 'original').iterdir())) == 1

@pytest.mark.parametrize('score', [0, 6, 'NaN'])
def test_invalid_manual_scores_rollback(client, setup, session, score):
    assert start(client, setup, changes={'bcs_score': score}).status_code == 422
    assert count(session, m.AssessmentWorkflow) == count(session, m.BCSRecord) == 0
    assert count(session, m.Image) == 1  # Existing linked fixture preserved.
    assert not list(settings.storage_root.rglob('*.png'))

def test_draft_standard_pending_and_no_approval(client, setup, session, tmp_path):
    assert client.post('/scoring-standards', json=DRAFT).status_code == 201
    result = start(client, setup, changes={'scoring_standard': DRAFT['name'], 'bcs_category': 'Unclassified'}).json()
    assert result['status'] == 'pending'
    assert client.post(f"/assessment-workflows/{result['id']}/review", json={'action': 'approve'}).status_code == 422
    output = tmp_path / 'draft.csv'
    assert export_dataset(session, output)['rows'] == 0

def test_reject_workflow(client, setup, session, tmp_path):
    result = start(client, setup, mode='ai').json()
    assert real_prediction(client, result['id']).status_code == 201
    response = client.post(f"/assessment-workflows/{result['id']}/review", json={'action': 'reject', 'notes': 'Synthetic rejection'})
    assert response.status_code == 200
    assert response.json()['status'] == response.json()['review_status'] == 'rejected'
    assert response.json()['finalized_by'] == 'test-vet'
    assert response.json()['assessment'] is None
    assert export_dataset(session, tmp_path / 'rejected.csv')['rows'] == 0

def test_invalid_prediction_and_correction(client, setup, session):
    result = start(client, setup, mode='ai').json()
    assert real_prediction(client, result['id'], predicted_bcs_score=9).status_code == 422
    assert real_prediction(client, result['id'], predicted_bcs_score=None, predicted_category=None).status_code == 422
    assert count(session, m.AIPrediction) == 0
    assert real_prediction(client, result['id']).status_code == 201
    assert client.post(f"/assessment-workflows/{result['id']}/review", json={'action': 'correct', 'bcs_score': 9}).status_code == 422
    assert client.get(f"/assessment-workflows/{result['id']}").json()['status'] == 'pending'
    assert count(session, m.BCSRecord) == 0

def test_database_failure_rolls_back_new_cow_image_and_workflow(client, setup, session, monkeypatch):
    def fail():
        raise OperationalError('synthetic failure', {}, Exception('test'))
    with monkeypatch.context() as patch:
        patch.setattr(session, 'commit', fail)
        response = start(client, setup, changes={'cow_id': None, 'new_cow': {'cow_identifier': 'SYNTHETIC-ROLLBACK'}})
    assert response.status_code == 503, response.text
    assert count(session, m.AssessmentWorkflow) == count(session, m.BCSRecord) == 0
    assert count(session, m.Cow) == count(session, m.Image) == count(session, m.ImageCow) == 1
    assert not list(settings.storage_root.rglob('*.png'))

def test_invalid_image_and_unknown_cow(client, setup, session):
    assert start(client, setup, content=b'not-an-image').status_code == 422
    assert start(client, setup, changes={'cow_id': 99999}).status_code == 404
    assert count(session, m.AssessmentWorkflow) == 0

def test_client_identity_flags_rejected(client, setup):
    for change in [{'evaluator': 'forged'}, {'approved': True}, {'role': 'veterinarian'}, {'review_status': 'approved'}]:
        assert start(client, setup, changes=change).status_code == 422

def test_legacy_approval_cannot_bypass_auth_or_workflow(client, setup):
    result = start(client, setup, mode='ai').json()
    payload = bcs(result['cow_id'], result['image_cow_id'], review_status='approved')
    assert client.post('/bcs', json=payload).status_code == 409
    assert client.patch(f"/image-cows/{result['image_cow_id']}", json={'crop_path': 'cropped/changed.png'}).status_code == 409
    assert client.post('/bcs', json=bcs(setup[0]['id'], setup[2]['id'], review_status='approved'), headers=LIMITED).status_code == 403
    client.headers.pop('Authorization')
    assert client.post('/bcs', json=payload).status_code == 401

def test_existing_apis_authenticated_compatibility(client, setup):
    payload = bcs(setup[0]['id'], setup[2]['id'])
    payload['evaluator'] = 'forged-client-id'
    response = client.post('/bcs', json=payload)
    assert response.status_code == 201
    assert response.json()['evaluator'] == 'test-vet'
    url = f"/bcs/{response.json()['id']}"
    assert client.patch(url, json={'review_status': 'approved'}).status_code == 200
    assert client.patch(url, json={'review_status': 'approved'}).status_code == 409
    assert client.get(f"/cows/{setup[0]['id']}/bcs").status_code == 200

def test_standard_approval_identity_from_server(client, setup):
    response = client.post('/scoring-standards', json={'name': 'SYNTHETIC-FORGED-APPROVER', 'approved_by': 'forged', 'approved_at': '2025-01-01T00:00:00Z', 'categories': ['Unclassified']})
    assert response.status_code == 201
    assert response.json()['approved_by'] == 'test-vet'
    assert client.post('/scoring-standards', json={'name': 'SYNTHETIC-LIMITED', 'approved_by': 'forged', 'approved_at': '2025-01-01T00:00:00Z', 'categories': ['Unclassified']}, headers=LIMITED).status_code == 403

def test_export_only_final_labels(client, setup, session, tmp_path):
    final = start(client, setup, mode='ai').json()
    assert export_dataset(session, tmp_path / 'before.csv')['rows'] == 0
    real_prediction(client, final['id'])
    assert export_dataset(session, tmp_path / 'predicted.csv')['rows'] == 0
    client.post(f"/assessment-workflows/{final['id']}/review", json={'action': 'correct', 'bcs_score': 4})
    output = tmp_path / 'after.csv'
    assert export_dataset(session, output)['rows'] == 1
    rows = list(csv.DictReader(output.open()))
    assert float(rows[0]['bcs_score']) == 4

def test_workflow_swagger(client):
    spec = client.get('/openapi.json').json()
    assert 'StartWorkflow' in spec['components']['schemas']
    assert 'WorkflowOut' in spec['components']['schemas']
    assert 'multipart/form-data' in spec['paths']['/assessment-workflows']['post']['requestBody']['content']
