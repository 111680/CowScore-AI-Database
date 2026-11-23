from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import TypeDecorator, DateTime
from datetime import timezone
from pydantic import Field, SecretStr, BaseModel, ConfigDict, field_validator, model_validator
from typing import Literal

class WorkflowCredential(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token_sha256: SecretStr
    role: Literal['veterinarian', 'ai_service']
    can_approve: bool = False

    @field_validator('token_sha256')
    @classmethod
    def digest(cls, value):
        import re
        if not re.fullmatch('[0-9a-f]{64}', value.get_secret_value()):
            raise ValueError('token_sha256 must be a lowercase SHA-256 digest')
        return value

    @model_validator(mode='after')
    def permissions(self):
        if self.role != 'veterinarian' and self.can_approve:
            raise ValueError('Only veterinarian credentials may approve')
        return self

class UTCDateTime(TypeDecorator):
    """PostgreSQL timestamptz; normalize SQLite test results to UTC too."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError('Timezone-aware timestamp required')
            return value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value

class Settings(BaseSettings):
    database_url: str = 'postgresql+psycopg://cowscore:CHANGE_ME@localhost:5432/cowscore'
    storage_root: Path = Path('dataset')
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_image_pixels: int = Field(default=20_000_000, gt=0)
    dataset_export_token: SecretStr | None = None
    workflow_credentials: dict[str, WorkflowCredential] = Field(default_factory=dict)
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    @field_validator('workflow_credentials')
    @classmethod
    def credential_identities(cls, value):
        import re
        if any(not re.fullmatch(r'[A-Za-z0-9_.:@-]{1,120}', subject) for subject in value):
            raise ValueError('Credential identities must be stable nonblank identifiers of at most 120 characters')
        hashes = [item.token_sha256.get_secret_value() for item in value.values()]
        if len(hashes) != len(set(hashes)):
            raise ValueError('Each identity must have a distinct credential')
        return value

settings = Settings()

class Base(DeclarativeBase):
    pass

def make_engine(url):
    engine = create_engine(url, pool_pre_ping=True)
    if url.startswith('sqlite'):
        @event.listens_for(engine, 'connect')
        def foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
    return engine

engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(engine, expire_on_commit=False)

def get_session():
    with SessionLocal() as session:
        yield session
