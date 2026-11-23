import asyncio
import csv
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError
from app import dataset_routes, models as m
from app.db import settings
from app.db import WorkflowCredential
from test_api import bcs
from test_standards import DRAFT

@pytest.fixture(autouse=True)
def export_access(client, monkeypatch):
    monkeypatch.setattr(settings, 'dataset_export_token', SecretStr('synthetic-test-export-token'))
    monkeypatch.setattr(settings, 'workflow_credentials', {**settings.workflow_credentials,
        'test-dataset-setup': WorkflowCredential(token_sha256=hashlib.sha256(b'synthetic-test-export-token').hexdigest(), role='veterinarian', can_approve=True)})
    client.headers['Authorization'] = 'Bearer synthetic-test-export-token'

@pytest.fixture
def export_directories(tmp_path, monkeypatch):
    paths = []
    def temporary(**kwargs):
        directory = TemporaryDirectory(dir=tmp_path, **kwargs)
        paths.append(Path(directory.name))
        return directory
    monkeypatch.setattr(dataset_routes, 'TemporaryDirectory', temporary)
    return paths

def test_successful_download(client, linked, export_directories, monkeypatch):
    cow, _, association = linked
    assert client.post('/bcs', json=bcs(cow['id'], association['id'], review_status='approved')).status_code == 201
    real_export = dataset_routes.export_dataset
    calls = []
    def observe(session, output, **kwargs):
        calls.append(kwargs)
        manifest = real_export(session, output, **kwargs)
        assert output.is_file()
        assert output.with_suffix('.csv.manifest.json').is_file()
        return manifest
    monkeypatch.setattr(dataset_routes, 'export_dataset', observe)
    result = client.get('/datasets/export?seed=7&train_frac=0.7&val_frac=0.2')
    assert result.status_code == 200, result.text
    assert result.headers['content-type'].startswith('text/csv')
    assert result.headers['content-disposition'] == 'attachment; filename="training.csv"'
    assert result.headers['cache-control'] == 'no-store'
    assert result.headers['x-dataset-sha256'] == hashlib.sha256(result.content).hexdigest()
    rows = list(csv.DictReader(result.text.splitlines()))
    assert len(rows) == 1 and rows[0]['cow_identifier'] == cow['cow_identifier']
    assert calls == [dict(seed=7, train=0.7, validation=0.2, approved_only=True)]
    assert len(export_directories) == 1 and not export_directories[0].exists()

@pytest.mark.parametrize('query', [
    'train_frac=0', 'train_frac=-0.1', 'train_frac=1', 'val_frac=-0.1',
    'train_frac=0.8&val_frac=0.2', 'train_frac=0.8&val_frac=0.3',
    'train_frac=nan', 'val_frac=inf', 'train_frac=invalid', 'seed=abc',
    'include_unapproved=true', 'approved_only=false', 'output=C:/outside.csv',
])
def test_invalid_query(client, export_directories, query):
    assert client.get('/datasets/export?' + query).status_code == 422
    assert export_directories == []

def test_empty_defaults_unique_directories(client, export_directories, monkeypatch):
    real_export = dataset_routes.export_dataset
    def observe(session, output, **kwargs):
        assert kwargs == dict(seed=42, train=0.8, validation=0.1, approved_only=True)
        return real_export(session, output, **kwargs)
    monkeypatch.setattr(dataset_routes, 'export_dataset', observe)
    for _ in range(2):
        response = client.get('/datasets/export')
        assert response.status_code == 200
        reader = csv.DictReader(response.text.splitlines())
        assert reader.fieldnames == ['image_or_crop_path', 'cow_identifier', 'bcs_score', 'bcs_category', 'scoring_standard', 'dataset_split']
        assert list(reader) == []
    assert len(set(export_directories)) == 2
    assert all(not path.exists() for path in export_directories)

def test_zero_validation_fraction(client, export_directories):
    assert client.get('/datasets/export?train_frac=0.8&val_frac=0').status_code == 200

def test_excludes_unapproved_and_draft_labels(client, session, linked, export_directories):
    cow, _, association = linked
    for review in ['pending', 'rejected']:
        assert client.post('/bcs', json=bcs(cow['id'], association['id'], review_status=review)).status_code == 201
    assert client.post('/scoring-standards', json=DRAFT).status_code == 201
    payload = bcs(cow['id'], association['id'])
    payload.update(scoring_standard=DRAFT['name'], bcs_category='Unclassified')
    response = client.post('/bcs', json=payload)
    assert response.status_code == 201
    session.get(m.BCSRecord, response.json()['id']).review_status = 'approved'
    session.commit()
    result = client.get('/datasets/export')
    assert result.status_code == 200
    assert list(csv.DictReader(result.text.splitlines())) == []
    assert all(not path.exists() for path in export_directories)

@pytest.mark.parametrize('database_failure', [False, True])
def test_export_failure_cleanup_and_safe_error(client, export_directories, monkeypatch, database_failure):
    def fail(session, output, **kwargs):
        output.write_text('partial export')
        output.with_suffix('.csv.manifest.json').write_text('partial manifest')
        if database_failure:
            raise OperationalError('sensitive database details', {}, Exception(str(output)))
        raise OSError(f'Failed at secret path {output}')
    monkeypatch.setattr(dataset_routes, 'export_dataset', fail)
    result = client.get('/datasets/export')
    assert result.status_code == 503
    assert result.json() == {'detail': 'Dataset export is temporarily unavailable'}
    assert len(export_directories) == 1 and not export_directories[0].exists()

@pytest.mark.parametrize('cancelled', [False, True])
def test_transfer_failure_cleanup(tmp_path, cancelled):
    directory = TemporaryDirectory(dir=tmp_path)
    path = Path(directory.name) / 'training.csv'
    path.write_text('test')
    response = dataset_routes.TemporaryCSVResponse(directory, path, 'checksum')
    async def send(message):
        if cancelled:
            raise asyncio.CancelledError()
        raise OSError('Simulated connection failure')
    async def receive():
        return {'type': 'http.request'}
    scope = {'type': 'http', 'method': 'GET', 'headers': [], 'asgi': {'spec_version': '2.4'},
             'extensions': {'http.response.pathsend': {}}}
    async def run():
        with pytest.raises(asyncio.CancelledError if cancelled else OSError):
            await response(scope, receive, send)
    asyncio.run(run())
    assert not path.parent.exists()

@pytest.mark.parametrize('authorization', [None, 'Bearer wrong-token', 'Basic invalid'])
def test_unauthorized(client, export_directories, authorization):
    client.headers.pop('Authorization')
    headers = {'Authorization': authorization} if authorization else {}
    response = client.get('/datasets/export', headers=headers)
    assert response.status_code == 401
    assert export_directories == []

def test_unconfigured_access_disabled(client, export_directories, monkeypatch):
    monkeypatch.setattr(settings, 'dataset_export_token', None)
    assert client.get('/datasets/export').status_code == 503
    assert export_directories == []

def test_export_openapi(client):
    operation = client.get('/openapi.json').json()['paths']['/datasets/export']['get']
    assert {item['name'] for item in operation['parameters']} == {'seed', 'train_frac', 'val_frac'}
    assert 'text/csv' in operation['responses']['200']['content']
    assert operation['security'] == [{'DatasetExportToken': []}]
