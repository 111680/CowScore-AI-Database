import csv
import pytest
from sqlalchemy import select, func
from app import models as m
from app.datasets import import_csv, export_dataset
from test_api import bcs

def write_csv(path, fields, rows):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

def test_csv_repeat_and_atomicity(session, tmp_path):
    path = tmp_path / 'cows.csv'
    fields = ['external_key', 'cow_identifier', 'registration_date']
    rows = [{'external_key': 'test:1', 'cow_identifier': 'SYNTHETIC-CSV-1', 'registration_date': '2025-01-01'}]
    write_csv(path, fields, rows)
    assert import_csv(session, 'cows', path) == {'inserted': 1, 'skipped': 0}
    assert import_csv(session, 'cows', path) == {'inserted': 0, 'skipped': 1}
    rows[0]['cow_identifier'] = 'SYNTHETIC-CHANGED'
    write_csv(path, fields, rows)
    with pytest.raises(ValueError, match='Changed content'):
        import_csv(session, 'cows', path)
    write_csv(path, fields, [dict(external_key='test:2', cow_identifier='SYNTHETIC-CSV-2', registration_date='2025-01-01'), dict(external_key='test:3', cow_identifier='', registration_date='2025-01-01')])
    with pytest.raises(ValueError):
        import_csv(session, 'cows', path)
    assert session.scalar(select(func.count()).select_from(m.Cow)) == 1

def test_export_leakage_reproducibility_and_missing_labels(client, session, linked, tmp_path):
    cow, _, association = linked
    assert client.post('/bcs', json=bcs(cow['id'], association['id'], review_status='approved')).status_code == 201
    for i in range(1, 12):
        c = client.post('/cows', json={'cow_identifier': f'SYNTHETIC-{i:03}'}).json()
        for j in range(2):
            image = client.post('/images', json={'image_path': f'original/synthetic-{i}-{j}.jpg', 'captured_at': '2025-01-01T00:00:00Z', 'source': 'synthetic-test'}).json()
            a = client.post('/image-cows', json={'cow_id': c['id'], 'image_id': image['id']}).json()
            assert client.post('/bcs', json=bcs(c['id'], a['id'], review_status='approved' if i < 11 else 'pending')).status_code == 201
    a, b = tmp_path / 'a.csv', tmp_path / 'b.csv'
    export_dataset(session, a, seed=42)
    export_dataset(session, b, seed=42)
    assert a.read_bytes() == b.read_bytes()
    rows = list(csv.DictReader(a.open()))
    splits = {}
    for row in rows:
        splits.setdefault(row['cow_identifier'], set()).add(row['dataset_split'])
        assert row['bcs_score'] == ''
    assert all(len(v) == 1 for v in splits.values())
    assert 'SYNTHETIC-011' not in splits
    assert {row['dataset_split'] for row in rows} == {'train', 'validation', 'test'}

def test_shared_original_stays_together(client, session, linked, tmp_path):
    cow, image, a = linked
    other = client.post('/cows', json={'cow_identifier': 'SYNTHETIC-SHARED'}).json()
    second = client.post('/image-cows', json={'cow_id': other['id'], 'image_id': image['id']}).json()
    for c, association in [(cow, a), (other, second)]:
        client.post('/bcs', json=bcs(c['id'], association['id'], review_status='approved'))
    path = tmp_path / 'shared.csv'
    export_dataset(session, path, train=0.5, validation=0)
    assert len({r['dataset_split'] for r in csv.DictReader(path.open())}) == 1

def test_empty_export(session, tmp_path):
    path = tmp_path / 'empty.csv'
    assert export_dataset(session, path)['rows'] == 0
    assert list(csv.DictReader(path.open())) == []

def test_all_csv_resources(client, session, linked, tmp_path):
    cow, image, association = linked
    cases = [
        ('images', dict(image_path='original/synthetic-csv.jpg', captured_at='2025-01-01T00:00:00Z', source='synthetic-test')),
        ('image_cows', dict(cow_id=cow['id'], image_id=image['id'], crop_path='cropped/synthetic.csv.jpg')),
        ('bcs_records', bcs(cow['id'], association['id'])),
        ('weight_records', dict(cow_id=cow['id'], weight_kg=123, measurement_timestamp='2025-01-01T00:00:00Z', measurement_context='routine', measurement_method='synthetic-test')),
        ('feeding_records', dict(cow_id=cow['id'], feeding_timestamp='2025-01-01T00:00:00Z', feed_type='synthetic', quantity_offered_kg=3)),
    ]
    for resource, values in cases:
        if resource == 'image_cows':
            values['image_id'] = session.scalar(select(m.Image.id).where(m.Image.image_path == 'original/synthetic-csv.jpg'))
        path = tmp_path / f'{resource}.csv'
        values['external_key'] = f'synthetic:{resource}:1'
        write_csv(path, list(values), [values])
        assert import_csv(session, resource, path)['inserted'] == 1
        assert import_csv(session, resource, path)['skipped'] == 1
