"""Shared HTTP dependencies for authenticated domain routes."""

import hmac

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings

bearer_scheme = HTTPBearer(auto_error=False)


def require_api_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    """Require a constant-time checked bearer token for data-changing routes."""

    configured_token = get_settings().api_token
    if configured_token is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configure CV_AUTOMATION_API_TOKEN para habilitar a API de domínio.",
        )

    if credentials is None or not credentials.credentials.isascii() or not hmac.compare_digest(
        credentials.credentials,
        configured_token.get_secret_value(),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de API ausente ou inválido.",
            headers={"WWW-Authenticate": "Bearer"},
        )
