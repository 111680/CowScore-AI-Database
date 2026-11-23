import csv
import pytest
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from app import models as m
from app.datasets import export_dataset
from test_api import bcs

DRAFT = dict(name='DRAFT-1-5', approved_by=None, approved_at=None,
             minimum_score=1, maximum_score=5, categories=['Unclassified'])

def test_draft_create_and_list(client):
    result = client.post('/scoring-standards', json=DRAFT)
    assert result.status_code == 201, result.text
    assert result.json()['approval_status'] == 'draft'
    assert result.json()['approved_by'] is None
    assert result.json()['approved_at'] is None
    assert client.get('/scoring-standards').json()[0]['approval_status'] == 'draft'
    omitted = {k: v for k, v in DRAFT.items() if k not in ('approved_by', 'approved_at')}
    omitted['name'] = 'DRAFT-OMITTED'
    assert client.post('/scoring-standards', json=omitted).json()['approval_status'] == 'draft'

@pytest.mark.parametrize('change', [
    {'categories': []}, {'categories': None}, {'categories': ['']},
    {'categories': ['   ']}, {'categories': ['Low', 'Low']},
    {'approved_by': 'Synthetic reviewer'},
    {'approved_at': '2025-01-01T00:00:00Z'},
    {'approval_status': 'veterinary_approved'},
])
def test_invalid_standard(client, change):
    assert client.post('/scoring-standards', json={**DRAFT, **change}).status_code == 422

def test_missing_categories(client):
    assert client.post('/scoring-standards', json={'name': 'missing'}).status_code == 422

def test_approved_status(client, linked):
    assert client.get('/scoring-standards').json()[0]['approval_status'] == 'veterinary_approved'

def test_draft_label_review_and_export(client, session, linked, tmp_path):
    cow, _, association = linked
    assert client.post('/scoring-standards', json=DRAFT).status_code == 201
    payload = bcs(cow['id'], association['id'])
    payload.update(scoring_standard=DRAFT['name'], bcs_category='Unclassified', bcs_score=3)
    result = client.post('/bcs', json=payload)
    assert result.status_code == 201, result.text
    assert client.patch(f"/bcs/{result.json()['id']}", json={'review_status': 'approved'}).status_code == 422
    payload['review_status'] = 'approved'
    assert client.post('/bcs', json=payload).status_code == 422
    # Even a direct SQL/ORM writer bypassing services cannot leak draft labels
    # into the default approved training export.
    label = session.get(m.BCSRecord, result.json()['id'])
    label.review_status = 'approved'
    session.commit()
    path = tmp_path / 'draft.csv'
    assert export_dataset(session, path)['rows'] == 0
    assert list(csv.DictReader(path.open())) == []

def test_database_rejects_partial_approval(session):
    session.add(m.ScoringStandard(name='invalid-pair', approved_by='Synthetic', approved_at=None))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

def test_draft_prediction_allowed(client, linked):
    cow, _, association = linked
    client.post('/scoring-standards', json=DRAFT)
    response = client.post('/predictions', json=dict(cow_id=cow['id'], image_cow_id=association['id'], model_name='synthetic', model_version='test', scoring_standard=DRAFT['name'], predicted_bcs_score=3, predicted_category='Unclassified', prediction_timestamp='2025-01-01T00:00:00Z'))
    assert response.status_code == 201, response.text
