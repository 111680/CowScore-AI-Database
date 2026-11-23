"""Authenticated HTTP wrapper; selection and splitting remain in datasets.py."""
import logging
from pathlib import Path
from secrets import compare_digest
from tempfile import TemporaryDirectory
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .datasets import export_dataset
from .db import get_session, settings

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False, scheme_name='DatasetExportToken')

def authorize_export(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    token = settings.dataset_export_token
    if token is None or not token.get_secret_value():
        raise HTTPException(503, 'Dataset export access is not configured')
    if credentials is None or not compare_digest(credentials.credentials.encode(), token.get_secret_value().encode()):
        raise HTTPException(401, 'Valid dataset export bearer token required', headers={'WWW-Authenticate': 'Bearer'})

router = APIRouter(prefix='/datasets', tags=['Datasets'], dependencies=[Depends(authorize_export)])

class ExportQuery(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    seed: int = 42
    train_frac: float = Field(default=0.8, gt=0, lt=1)
    val_frac: float = Field(default=0.1, ge=0, lt=1)

    @model_validator(mode='after')
    def reserve_test_fraction(self):
        if self.train_frac + self.val_frac >= 1:
            raise ValueError('train_frac + val_frac must be less than 1')
        return self

class TemporaryCSVResponse(FileResponse):
    """Own temporary artifacts until transfer completes, fails, or is cancelled."""
    def __init__(self, directory, path, checksum):
        self.directory = directory
        super().__init__(path, media_type='text/csv', filename='training.csv', headers={
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'X-Dataset-SHA256': checksum,
        })

    async def __call__(self, scope, receive, send):
        # Avoid deferred pathsend reads racing cleanup; send CSV bytes ourselves.
        scope = {**scope, 'extensions': {key: value for key, value in scope.get('extensions', {}).items()
                                       if key != 'http.response.pathsend'}}
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(self.directory.cleanup)

@router.get('/export', response_class=FileResponse,
            summary='Download an approved training dataset CSV',
            description='Requires the configured dataset export bearer token. Uses approved labels '
                        'under veterinary-approved standards only. Reuses cow/shared-image splitting. '
                        'Empty datasets return CSV headers. Temporary CSV and manifest are cleaned '
                        'after transfer. X-Dataset-SHA256 supplies the CSV checksum.',
            responses={200: {'description': 'CSV attachment', 'content': {'text/csv': {}},
                             'headers': {'X-Dataset-SHA256': {'schema': {'type': 'string'}}}},
                       401: {'description': 'Missing or invalid bearer token'},
                       503: {'description': 'Export unavailable or access not configured'}})
def download_dataset(query: Annotated[ExportQuery, Query()], session: Session = Depends(get_session)):
    directory = None
    try:
        directory = TemporaryDirectory(prefix='cowscore-export-')
        output = Path(directory.name) / 'training.csv'
        manifest = export_dataset(session, output, seed=query.seed, train=query.train_frac,
                                  validation=query.val_frac, approved_only=True)
        return TemporaryCSVResponse(directory, output, manifest['sha256'])
    except Exception as exc:
        if directory is not None:
            directory.cleanup()
        logger.exception('Dataset export failed')
        raise HTTPException(503, 'Dataset export is temporarily unavailable') from exc
