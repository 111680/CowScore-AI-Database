import os
os.environ['DATABASE_URL'] = 'sqlite://'

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from app.db import Base, get_session, settings, WorkflowCredential
from hashlib import sha256
from app.main import app

@pytest.fixture
def session():
    url = os.environ.get('TEST_DATABASE_URL', 'sqlite://')
    kwargs = {'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}} if url == 'sqlite://' else {}
    engine = create_engine(url, **kwargs)
    if url.startswith('sqlite'):
        @event.listens_for(engine, 'connect')
        def enable_fk(conn, _):
            conn.execute('PRAGMA foreign_keys=ON')
    # TEST_DATABASE_URL must refer to a disposable, dedicated test database.
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()

@pytest.fixture
def client(session, monkeypatch):
    tokens = {
        'test-vet': ('synthetic-test-veterinarian-token-32', 'veterinarian', True),
        'test-limited-vet': ('synthetic-limited-veterinarian-token', 'veterinarian', False),
        'test-ai-service': ('synthetic-ai-service-token-32', 'ai_service', False),
    }
    monkeypatch.setattr(settings, 'workflow_credentials', {
        subject: WorkflowCredential(token_sha256=sha256(token.encode()).hexdigest(), role=role, can_approve=approve)
        for subject, (token, role, approve) in tokens.items()
    })
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer synthetic-test-veterinarian-token-32'
        yield client
    app.dependency_overrides.clear()

@pytest.fixture
def linked(client):
    cow = client.post('/cows', json={'cow_identifier': 'SYNTHETIC-TEST-001'}).json()
    image = client.post('/images', json={'image_path': 'original/synthetic-test.jpg', 'captured_at': '2025-01-01T12:00:00Z', 'source': 'synthetic-test'}).json()
    association = client.post('/image-cows', json={'cow_id': cow['id'], 'image_id': image['id']}).json()
    standard = {'name': 'SYNTHETIC-TEST-ONLY', 'approved_by': 'Synthetic fixture; no veterinary approval', 'approved_at': '2025-01-01T00:00:00Z', 'categories': ['Low', 'Normal', 'High']}
    assert client.post('/scoring-standards', json=standard).status_code == 201
    return cow, image, association
