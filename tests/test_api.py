import pytest
from sqlalchemy.exc import IntegrityError
from app import models as m

def bcs(cow_id, image_cow_id, **extra):
    return dict(cow_id=cow_id, image_cow_id=image_cow_id, bcs_category='Normal', scoring_standard='SYNTHETIC-TEST-ONLY', evaluator='Synthetic test fixture', evaluation_method='manual', evaluation_date='2025-01-02T12:00:00Z', **extra)

def test_cows(client):
    response = client.post('/cows', json={'cow_identifier': 'SYNTHETIC-1'})
    assert response.status_code == 201
    identity = response.json()['id']
    assert client.get(f'/cows/{identity}').json()['cow_identifier'] == 'SYNTHETIC-1'
    assert client.patch(f'/cows/{identity}', json={'breed': 'Synthetic'}).json()['breed'] == 'Synthetic'
    assert client.post('/cows', json={'cow_identifier': 'SYNTHETIC-1'}).status_code == 409

def test_images_bcs_and_history(client, linked):
    cow, image, association = linked
    assert client.get(f"/cows/{cow['id']}/images").json()[0]['id'] == image['id']
    result = client.patch(f"/image-cows/{association['id']}", json={'crop_path': 'cropped/synthetic.jpg', 'segmentation_mask_path': 'masks/synthetic.png'})
    assert result.status_code == 200
    result = client.post('/bcs', json=bcs(cow['id'], association['id']))
    assert result.status_code == 201, result.text
    assert client.patch(f"/bcs/{result.json()['id']}", json={'review_status': 'approved'}).json()['review_status'] == 'approved'
    assert len(client.get(f"/cows/{cow['id']}/bcs").json()) == 1
    other = client.post('/cows', json={'cow_identifier': 'SYNTHETIC-2'}).json()
    assert client.post('/bcs', json=bcs(other['id'], association['id'])).status_code == 422
    bad = bcs(cow['id'], association['id'])
    bad['bcs_category'] = 'Unconfigured'
    assert client.post('/bcs', json=bad).status_code == 422

@pytest.mark.parametrize('path,body', [
    ('weights', {'weight_kg': 200, 'measurement_timestamp': '2025-01-02T12:00:00Z', 'measurement_context': 'before_feeding', 'measurement_method': 'synthetic scale'}),
    ('feeding', {'feeding_timestamp': '2025-01-02T12:00:00Z', 'feed_type': 'synthetic feed', 'quantity_offered_kg': 4}),
    ('health-records', {'observation_date': '2025-01-02T12:00:00Z', 'observation_type': 'synthetic', 'symptoms_or_observations': 'Synthetic test only'}),
    ('milk', {'measurement_timestamp': '2025-01-02T12:00:00Z', 'milk_quantity_liters': 2, 'milking_session': 'synthetic'}),
])
def test_measurements(client, linked, path, body):
    cow, _, _ = linked
    body['cow_id'] = cow['id']
    response = client.post('/' + path, json=body)
    assert response.status_code == 201, response.text
    history = client.get(f"/cows/{cow['id']}/{path}").json()
    assert len(history) == 1
    if path == 'feeding':
        assert history[0]['quantity_consumed_kg'] is None
    if path == 'weights':
        body['measurement_context'] = 'after_feeding'
        assert client.post('/weights', json=body).status_code == 201

@pytest.mark.parametrize('path,body', [
    ('cows', {'cow_identifier': ' '}),
    ('cows', {'cow_identifier': 'synthetic', 'birth_date': '2025-02-02', 'registration_date': '2025-01-01'}),
    ('images', {'image_path': '../bad.jpg', 'captured_at': '2025-01-01T00:00:00Z', 'source': 'synthetic'}),
    ('images', {'image_path': 'original/a.jpg', 'captured_at': '2025-01-01T00:00:00', 'source': 'synthetic'}),
    ('weights', {'cow_id': 1, 'weight_kg': -1, 'measurement_timestamp': '2025-01-01T00:00:00Z', 'measurement_context': 'routine', 'measurement_method': 'synthetic'}),
    ('feeding', {'cow_id': 1, 'feeding_timestamp': '2025-01-01T00:00:00Z', 'feed_type': 'synthetic', 'quantity_offered_kg': 2, 'quantity_consumed_kg': 3}),
])
def test_invalid_data(client, path, body):
    assert client.post('/' + path, json=body).status_code == 422

def test_predictions_separate(client, linked):
    cow, _, association = linked
    body = dict(cow_id=cow['id'], image_cow_id=association['id'], model_name='synthetic', model_version='test', predicted_category='Normal', scoring_standard='SYNTHETIC-TEST-ONLY', confidence_score=0.8, prediction_timestamp='2025-01-01T00:00:00Z')
    assert client.post('/predictions', json=body).status_code == 201
    assert client.get(f"/cows/{cow['id']}/bcs").json() == []
    body['confidence_score'] = 1.1
    assert client.post('/predictions', json=body).status_code == 422

def test_database_constraints(session, linked):
    cow, image, association = linked
    other = m.Cow(cow_identifier='SYNTHETIC-OTHER')
    session.add(other)
    session.commit()
    from datetime import datetime, timezone
    session.add(m.BCSRecord(cow_id=other.id, image_cow_id=association['id'], bcs_category='Normal', scoring_standard='SYNTHETIC-TEST-ONLY', evaluator='synthetic', evaluation_method='manual', evaluation_date=datetime.now(timezone.utc)))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.delete(session.get(m.Cow, cow['id']))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

def test_not_found_and_openapi(client):
    assert client.get('/cows/999/weights').status_code == 404
    assert client.get('/openapi.json').status_code == 200
    assert client.get('/docs').status_code == 200
