"""
Authentication endpoints: register, login, forgot/reset password.
"""

import random
from fastapi import APIRouter, HTTPException, status
from database.connection import get_pool
from database.models import UserRegister, UserLogin, TokenResponse, ForgotPasswordRequest, ResetPasswordRequest
import database.queries as q
from auth.utils import hash_password, verify_password, create_access_token
from services.email_service import send_password_reset_email

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

    async with pool.acquire() as conn:
        await q.update_user_last_visited(conn, user["id"])

    token = create_access_token(user["id"], user["email"])
    return TokenResponse(access_token=token)


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await q.get_user_by_email(conn, body.email)
        if not user:
            return {"ok": True}  # don't reveal whether email exists
        code = str(random.randint(100000, 999999))
        await q.create_reset_token(conn, user["id"], code)
    try:
        await send_password_reset_email(recipient=body.email, code=code)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to send email. Try again later.")
    return {"ok": True}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest) -> dict:
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await q.get_user_by_email(conn, body.email)
        if not user:
            raise HTTPException(status_code=400, detail="Invalid code.")
        token = await q.get_valid_reset_token(conn, user["id"], body.code.strip())
        if not token:
            raise HTTPException(status_code=400, detail="Invalid or expired code.")
        await q.update_user_password(conn, user["id"], hash_password(body.new_password))
        await q.mark_reset_token_used(conn, user["id"])
    return {"ok": True}
