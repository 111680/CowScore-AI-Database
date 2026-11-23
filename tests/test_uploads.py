from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from PIL import Image
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db import settings
from app.models import Image as ImageRecord
from app import uploads

def image_bytes(fmt='PNG'):
    stream = BytesIO()
    Image.new('RGB', (16, 12), color='brown').save(stream, format=fmt)
    return stream.getvalue()

@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    root = tmp_path / 'storage'
    monkeypatch.setattr(settings, 'storage_root', root)
    return root

def upload(client, content=None, filename='cow.png', mime='image/png', data=None):
    return client.post('/images/upload', files={'file': (filename, image_bytes() if content is None else content, mime)},
                       data=data if data is not None else {'captured_at': '2025-01-01T12:00:00+02:00', 'source': 'synthetic-upload-test'})

def assert_empty(session, storage):
    assert session.scalar(select(func.count()).select_from(ImageRecord)) == 0
    assert not list(storage.rglob('*.*'))

@pytest.mark.parametrize('fmt,filename,mime', [('PNG', 'cow.PNG', 'image/png'), ('JPEG', 'cow.jpg', 'image/jpeg'), ('JPEG', 'cow.jpeg', 'image/jpeg')])
def test_upload_success(client, session, storage, fmt, filename, mime):
    content = image_bytes(fmt)
    result = upload(client, content, filename, mime)
    assert result.status_code == 201, result.text
    data = result.json()
    assert data['image_format'] == fmt
    assert (data['width'], data['height'], data['size_bytes']) == (16, 12, len(content))
    assert data['quality_status'] == 'unreviewed'
    relative = Path(data['image_path'])
    assert relative.parts[0] == 'original'
    UUID(relative.stem)
    assert (storage / relative).read_bytes() == content
    record = session.get(ImageRecord, data['id'])
    assert record.image_path == data['image_path']
    assert record.source == 'synthetic-upload-test'

def test_safe_names_unique_and_existing_metadata_preserved(client, session, storage):
    existing = client.post('/images', json={'image_path': 'original/existing.jpg', 'captured_at': '2025-01-01T00:00:00Z', 'source': 'synthetic-existing'}).json()
    first = upload(client, filename='../../cow.png').json()
    second = upload(client, filename='C:\\outside\\cow.png').json()
    assert first['image_path'] != second['image_path']
    assert all((storage / r['image_path']).resolve().is_relative_to(storage.resolve()) for r in [first, second])
    assert session.get(ImageRecord, existing['id']).image_path == 'original/existing.jpg'
    assert session.scalar(select(func.count()).select_from(ImageRecord)) == 3

@pytest.mark.parametrize('content,filename,mime,status', [
    (b'', 'cow.png', 'image/png', 422),
    (b'not an image', 'cow.jpg', 'image/jpeg', 422),
    (b'\x89PNG\r\n\x1a\ninvalid', 'cow.png', 'image/png', 422),
    (image_bytes('JPEG')[:100], 'cow.jpg', 'image/jpeg', 422),
    (image_bytes('JPEG')[:-20], 'cow.jpg', 'image/jpeg', 422),
    (image_bytes('GIF'), 'cow.png', 'image/png', 415),
    (image_bytes(), 'cow.jpg', 'image/jpeg', 415),
    (image_bytes(), 'cow.png', 'image/jpeg', 415),
    (image_bytes(), 'cow.svg', 'image/png', 415),
])
def test_reject_invalid_files(client, session, storage, content, filename, mime, status):
    assert upload(client, content, filename, mime).status_code == status
    assert_empty(session, storage)

def test_oversize_and_exact_limit(client, session, storage, monkeypatch):
    content = image_bytes()
    monkeypatch.setattr(settings, 'max_upload_bytes', len(content) - 1)
    assert upload(client, content).status_code == 413
    assert_empty(session, storage)
    monkeypatch.setattr(settings, 'max_upload_bytes', len(content))
    assert upload(client, content).status_code == 201

def test_pixel_limit(client, session, storage, monkeypatch):
    monkeypatch.setattr(settings, 'max_image_pixels', 100)
    assert upload(client).status_code == 413
    assert_empty(session, storage)

@pytest.mark.parametrize('stage,status', [('flush', 409), ('commit', 503)])
def test_database_failure_removes_file(client, session, storage, monkeypatch, stage, status):
    def fail(*args, **kwargs):
        assert len(list((storage / 'original').glob('*'))) == 1
        if stage == 'flush':
            raise IntegrityError('synthetic failure', {}, Exception('test'))
        raise OperationalError('synthetic failure', {}, Exception('test'))
    with monkeypatch.context() as patch:
        patch.setattr(session, stage, fail)
        result = upload(client)
    assert result.status_code == status, result.text
    assert_empty(session, storage)

def test_partial_disk_failure_cleanup(client, session, storage, monkeypatch):
    original_open = Path.open
    class BrokenWriter:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def write(self, content):
            self.stream.write(content[:5])
            raise OSError('Synthetic disk-full failure')
        def __exit__(self, *args):
            self.stream.close()
    def open_file(path, mode='r', *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        return BrokenWriter(stream) if mode == 'xb' else stream
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'open', open_file)
        assert upload(client).status_code == 503
    assert_empty(session, storage)

@pytest.mark.parametrize('data', [
    {'captured_at': '2025-01-01T00:00:00', 'source': 'test'},
    {'captured_at': '2025-01-01T00:00:00Z', 'source': '   '},
    {'source': 'test'},
])
def test_metadata_validation_before_storage(client, session, storage, data):
    assert upload(client, data=data).status_code == 422
    assert_empty(session, storage)

def test_swagger_multipart_and_existing_json_endpoint(client):
    paths = client.get('/openapi.json').json()['paths']
    assert 'multipart/form-data' in paths['/images/upload']['post']['requestBody']['content']
    assert 'application/json' in paths['/images']['post']['requestBody']['content']

def test_filename_collision_does_not_overwrite(client, session, storage, monkeypatch):
    identity = UUID('12345678-1234-1234-1234-123456789abc')
    monkeypatch.setattr(uploads, 'uuid4', lambda: identity)
    directory = storage / 'original'
    directory.mkdir(parents=True)
    existing = directory / (identity.hex + '.png')
    existing.write_bytes(b'Existing file; never overwrite')
    assert upload(client).status_code == 503
    assert existing.read_bytes() == b'Existing file; never overwrite'
    assert session.scalar(select(func.count()).select_from(ImageRecord)) == 0
