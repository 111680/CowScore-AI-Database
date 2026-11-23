"""Server-provisioned machine/user credentials; identities never come from requests."""
from dataclasses import dataclass
from hashlib import sha256
from secrets import compare_digest
from typing import Annotated
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .db import settings

bearer = HTTPBearer(auto_error=False, scheme_name='WorkflowCredentials')

@dataclass(frozen=True)
class Principal:
    subject: str
    role: str
    can_approve: bool

def authenticate(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Principal:
    if not settings.workflow_credentials:
        raise HTTPException(503, 'Veterinary workflow credentials are not configured')
    if credentials is not None:
        digest = sha256(credentials.credentials.encode()).hexdigest()
        for subject, config in settings.workflow_credentials.items():
            if compare_digest(digest, config.token_sha256.get_secret_value()):
                return Principal(subject, config.role, config.can_approve)
    raise HTTPException(401, 'Valid workflow bearer credential required', headers={'WWW-Authenticate': 'Bearer'})

def veterinarian(principal: Annotated[Principal, Depends(authenticate)]) -> Principal:
    if principal.role != 'veterinarian':
        raise HTTPException(403, 'Veterinarian authorization required')
    return principal

def inference_service(principal: Annotated[Principal, Depends(authenticate)]) -> Principal:
    if principal.role != 'ai_service':
        raise HTTPException(403, 'AI service authorization required')
    return principal

def require_approval(principal: Principal):
    if principal.role != 'veterinarian' or not principal.can_approve:
        raise HTTPException(403, 'Veterinary approval permission required')
