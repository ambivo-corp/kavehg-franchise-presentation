"""
JWT Authentication — matching ambivo_api token structure
"""
import jwt
import logging
from typing import Dict, Any
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings

logger = logging.getLogger(__name__)
security = HTTPBearer()


class JWTAuth:
    def __init__(self):
        self.secret_key = settings.jwt_secret_key
        self.algorithm = settings.jwt_algorithm

    def decode_token(self, token: str) -> Dict[str, Any]:
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])

            user_id = payload.get("user_id") or payload.get("userid")
            tenant_id = payload.get("tenant_id")

            if not user_id or not tenant_id:
                raise HTTPException(status_code=401, detail="Invalid token: missing required fields")

            return {
                "userid": user_id,
                "tenant_id": tenant_id,
                "scopes": payload.get("scopes", []),
            }

        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token has expired")
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid JWT token: {e}")
            raise HTTPException(status_code=401, detail="Invalid token")


jwt_auth = JWTAuth()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Dict[str, Any]:
    return jwt_auth.decode_token(credentials.credentials)
