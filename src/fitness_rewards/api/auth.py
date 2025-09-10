"""Authentication utilities for the Fitness Rewards API."""

from fastapi import HTTPException, Header
from ..config import API_KEY


def verify_api_key(x_api_key: str = Header(..., description="API Key for authentication")):
    """Authentication dependency to verify API key."""
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key
