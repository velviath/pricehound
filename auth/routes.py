"""
Authentication endpoints: register and login.
"""

from fastapi import APIRouter, HTTPException, status
from database.connection import get_pool
from database.models import UserRegister, UserLogin, TokenResponse
import database.queries as q
from auth.utils import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: UserRegister):
    """
    Create a new user account.
    Returns a JWT so the user is immediately logged in after registration.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await q.get_user_by_email(conn, body.email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email already exists.",
            )

        if len(body.password) < 8:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Password must be at least 8 characters.",
            )

        hashed = hash_password(body.password)
        user = await q.create_user(conn, body.email, hashed)

    token = create_access_token(user["id"], user["email"])
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(body: UserLogin):
    """
    Authenticate with email + password.
    Returns a JWT on success.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await q.get_user_by_email(conn, body.email)

    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    token = create_access_token(user["id"], user["email"])
    return TokenResponse(access_token=token)
