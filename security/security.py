import os
from hmac import compare_digest

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer(auto_error=False)

def verify_token(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
    expected_token = os.getenv("TOKEN")

    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token da API não configurado.",
        )

    if not credentials or not compare_digest(credentials.credentials, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou não fornecido.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return credentials.credentials