import logging
from datetime import datetime
from typing import Annotated

import sqlalchemy as sa
from activityual_common.problems import ProblemError, unauthenticated
from activityual_common.security import CurrentUser
from fastapi import APIRouter, Depends
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth_service.tokens import DUMMY_HASH, TokenIssuer, hash_password, verify_password

from .tables import app_user

log = logging.getLogger("auth")

class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=20)]

    @field_validator("email")
    @classmethod
    def _email_ok(cls, v: str) -> str:
        v = v.lower()
        if not 3 <= len(v) <= 254:
            raise ValueError("email must be 3-254 characters")
        return v

    @model_validator(mode="after")
    def _not_email(self):
        if self.password.lower() == self.email:
            raise ValueError("password must not be equal the email.")
        return self


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Annotated[str, Field(min_length=1, max_length=254)]
    password: Annotated[str, Field(min_length=8, max_length=20)]


def build_router(get_session, current_user, issuer: TokenIssuer) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    @router.post("/register", status_code=201)
    def register(
        body: RegisterRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict:
        try:
            row = session.execute(
                sa.insert(app_user)
                .values(email=body.email, password_hash=hash_password(body.password))
                .returning(app_user.c.id, app_user.c.email, app_user.c.created_at)
            ).one()
        except IntegrityError as exc:
            # insertion race handling
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise ProblemError(
                    "email-already-registered", 409, "Email already registered"
                ) from None
            raise
        return {
            "id": str(row.id),
            "email": row.email,
            "createdAt": _iso(row.created_at),
        }

    @router.post("/login")
    def login(
        body: LoginRequest, session: Annotated[Session, Depends(get_session)]
    ) -> dict:
        row = session.execute(
            sa.select(
                app_user.c.id, app_user.c.password_hash, app_user.c.is_active
            ).where(app_user.c.email == body.email.strip().lower())
        ).first()
        ok = verify_password(body.password, row.password_hash if row else DUMMY_HASH)
        if not (row and ok and row.is_active):
            log.warning("auth.login_failed")
            raise ProblemError("invalid_credentials", 401, "Invalid Credentails")
        return {
            "accessToken": issuer.issue(str(row.id)),
            "tokenType": "Bearer",
            "expiresIn": issuer.expires_in,
        }

    @router.get("/me")
    def me(
        session: Annotated[Session, Depends(get_session)],
        user: Annotated[CurrentUser, Depends(current_user)],
    ) -> dict:
        row = session.execute(
            sa.select(app_user.c.id, app_user.c.email, app_user.c.is_active).where(
                app_user.c.id == user.id
            )
        ).first()
        if row is None or not row.is_active:
            raise unauthenticated("Invalid or expired token")
        return {"id": str(row.id), "email": row.email}

    return router


def _iso(value: datetime) -> str:
    return value.isoformat()
