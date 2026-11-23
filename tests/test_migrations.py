from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from app.db import settings

def test_initial_migration_roundtrip(tmp_path, monkeypatch):
    url = 'sqlite:///' + (tmp_path / 'migration.db').as_posix()
    monkeypatch.setattr(settings, 'database_url', url)
    config = Config('alembic.ini')
    command.upgrade(config, 'head')
    engine = create_engine(url)
    assert 'ai_predictions' in inspect(engine).get_table_names()
    command.check(config)
    command.downgrade(config, 'base')
    assert inspect(engine).get_table_names() == ['alembic_version']
    engine.dispose()

def test_draft_migration_preserves_existing_standard(tmp_path, monkeypatch):
    from sqlalchemy import text
    url = 'sqlite:///' + (tmp_path / 'existing.db').as_posix()
    monkeypatch.setattr(settings, 'database_url', url)
    config = Config('alembic.ini')
    command.upgrade(config, '75bf68f6980a')
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO scoring_standards (id,name,approved_by,approved_at,created_at) VALUES (1,'Existing','Synthetic fixture','2025-01-01 00:00:00','2025-01-01 00:00:00')"))
    command.upgrade(config, 'head')
    command.check(config)
    with engine.begin() as conn:
        assert conn.execute(text('SELECT name,approved_by FROM scoring_standards WHERE id=1')).one() == ('Existing', 'Synthetic fixture')
        conn.execute(text("INSERT INTO scoring_standards (id,name,created_at) VALUES (2,'Draft','2025-01-01 00:00:00')"))
    import pytest
    with pytest.raises(RuntimeError, match='Cannot downgrade'):
        command.downgrade(config, '75bf68f6980a')
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT count(*) FROM scoring_standards')) == 2
    engine.dispose()

def test_workflow_migration_preserves_existing_data(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from app import models as m
    import pytest
    url = 'sqlite:///' + (tmp_path / 'workflow-upgrade.db').as_posix()
    monkeypatch.setattr(settings, 'database_url', url)
    config = Config('alembic.ini')
    command.upgrade(config, 'draft_standards_approval')
    engine = create_engine(url)
    with Session(engine) as session:
        cow = m.Cow(cow_identifier='SYNTHETIC-EXISTING-MIGRATION')
        image = m.Image(image_path='original/synthetic-migration.png', captured_at=datetime.now(timezone.utc), source='synthetic')
        standard = m.ScoringStandard(name='Synthetic migration standard')
        session.add_all([cow, image, standard])
        session.flush()
        association = m.ImageCow(cow_id=cow.id, image_id=image.id)
        session.add(association)
        session.commit()
    command.upgrade(config, 'head')
    command.check(config)
    with engine.begin() as conn:
        assert conn.scalar(text('SELECT count(*) FROM cows')) == 1
        assert conn.scalar(text('SELECT count(*) FROM images')) == 1
        assert conn.scalar(text('SELECT count(*) FROM image_cows')) == 1
        conn.execute(text("INSERT INTO assessment_workflows (cow_id,image_cow_id,scoring_standard,mode,status,created_by,request_key,created_at) VALUES (1,1,'Synthetic migration standard','ai','pending','test-vet','synthetic-request','2025-01-01 00:00:00')"))
    with pytest.raises(RuntimeError, match='Cannot downgrade'):
        command.downgrade(config, 'draft_standards_approval')
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT count(*) FROM assessment_workflows')) == 1
    engine.dispose()
