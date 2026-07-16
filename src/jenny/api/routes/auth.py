"""auth Google + email + JWT."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlencode
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from jenny.api.auth.email_verification import (
    MAX_VERIFY_ATTEMPTS,
    RESEND_COOLDOWN_SECONDS,
    code_expiry,
    generate_code,
    hash_code,
    is_expired,
    ttl_minutes,
    verify_code,
)
from jenny.api.auth.jwt_utils import create_access_token, decode_token
from jenny.api.auth.password_utils import hash_password, verify_password
from jenny.api.dependencies import CurrentUser, DbSession  # noqa: TC001
from jenny.core.config import get_settings
from jenny.core.logging import get_logger
from jenny.domain.models.business import Business
from jenny.domain.models.business_member import BusinessMember
from jenny.domain.models.user import User
from jenny.notifications.email_sender import EmailSender
from jenny.notifications.verification_email import build_reset_email, build_verification_email

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])


def _slugify(value: str) -> str:
    """texte vers slug."""
    slug = _re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "business"


async def _ensure_business_for_user(db, user: User, display_name: str | None) -> UUID:
    """crée un business si besoin."""
    r = await db.execute(
        select(BusinessMember.business_id).where(BusinessMember.user_id == user.id).limit(1)
    )
    existing = r.scalar_one_or_none()
    if existing is not None:
        return existing

    base = _slugify(display_name or (user.email.split("@")[0] if user.email else "business"))
    slug = f"{base}-{uuid4().hex[:6]}"
    business = Business(
        name=display_name or (user.full_name or "Mon entreprise"),
        slug=slug,
        email=user.email,
    )
    db.add(business)
    await db.flush()
    db.add(BusinessMember(user_id=user.id, business_id=business.id, role="owner"))
    await db.flush()
    logger.info("auth.business_created", user_id=str(user.id), business_id=str(business.id))
    return business.id


async def _issue_token_for_user(db, user: User) -> str:
    """émet un JWT."""
    r = await db.execute(
        select(BusinessMember.business_id).where(BusinessMember.user_id == user.id)
    )
    business_ids = [row[0] for row in r.all()]
    if not business_ids:
        business_ids = [await _ensure_business_for_user(db, user, user.full_name)]
        await db.commit()
    return create_access_token(user.id, user.email, business_ids)


async def _send_verification_email(user: User, code: str) -> None:
    """envoie l'email de confirmation."""
    try:
        msg = build_verification_email(
            to=user.email,
            code=code,
            full_name=user.full_name,
            ttl_minutes=ttl_minutes(),
        )
        await EmailSender().send(msg)
    except Exception as e:
        logger.error("auth.verification_email_failed", error=str(e), to=user.email)


async def _send_reset_email(user: User, code: str) -> None:
    """envoie l'email de reset."""
    try:
        msg = build_reset_email(
            to=user.email,
            code=code,
            full_name=user.full_name,
            ttl_minutes=ttl_minutes(),
        )
        await EmailSender().send(msg)
    except Exception as e:
        logger.error("auth.reset_email_failed", error=str(e), to=user.email)


# schemas


import re as _re  # noqa: E402


def _check_password_strength(password: str) -> str | None:
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if not _re.search(r"[A-Z]", password):
        return "Password must contain an uppercase letter"
    if not _re.search(r"[0-9]", password):
        return "Password must contain a number"
    if not _re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]~`/\\]', password):
        return "Password must contain a special character"
    return None


class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


# signup / login email


@router.post("/register")
async def register(body: RegisterRequest, db: DbSession) -> JSONResponse:
    pw_err = _check_password_strength(body.password)
    if pw_err:
        raise HTTPException(422, pw_err)

    r = await db.execute(select(User).where(User.email == body.email))
    if r.scalar_one_or_none() is not None:
        raise HTTPException(409, "An account already exists with this email")

    now = datetime.now(UTC)
    code = generate_code()
    user = User(
        email=body.email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        email_verified=False,
        email_verification_code_hash=hash_code(code),
        email_verification_expires_at=code_expiry(now),
        email_verification_attempts=0,
        email_verification_sent_at=now,
    )
    db.add(user)
    await db.flush()

    await _ensure_business_for_user(db, user, body.full_name)
    await db.commit()

    await _send_verification_email(user, code)
    logger.info("auth.register.code_sent", user_id=str(user.id), email=user.email)

    payload: dict = {"status": "verification_required", "email": user.email}
    if get_settings().is_test:
        payload["debug_code"] = code
    return JSONResponse(payload, status_code=202)


@router.post("/login")
async def login(body: LoginRequest, db: DbSession) -> JSONResponse:
    r = await db.execute(select(User).where(User.email == body.email))
    user = r.scalar_one_or_none()
    if user is None or not user.password_hash:
        raise HTTPException(401, "Email ou mot de passe incorrect")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Email ou mot de passe incorrect")
    if not user.email_verified:
        raise HTTPException(403, "email_not_verified")

    token = await _issue_token_for_user(db, user)
    return JSONResponse({"access_token": token, "token_type": "bearer"})


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=4, max_length=12)


class ResendCodeRequest(BaseModel):
    email: EmailStr


@router.post("/verify-email")
async def verify_email(body: VerifyEmailRequest, db: DbSession) -> JSONResponse:
    """valide le code et connecte."""
    r = await db.execute(select(User).where(User.email == body.email))
    user = r.scalar_one_or_none()
    if user is None:
        raise HTTPException(400, "Code invalide ou expiré")

    # déjà vérifié : re-token
    if user.email_verified:
        token = await _issue_token_for_user(db, user)
        return JSONResponse({"access_token": token, "token_type": "bearer"})

    if is_expired(user.email_verification_expires_at):
        raise HTTPException(400, "Code invalide ou expiré")

    if user.email_verification_attempts >= MAX_VERIFY_ATTEMPTS:
        raise HTTPException(429, "Trop de tentatives. Demandez un nouveau code.")

    if not verify_code(body.code.strip(), user.email_verification_code_hash):
        user.email_verification_attempts += 1
        # persiste le compteur avant
        await db.commit()
        raise HTTPException(400, "Code invalide")

    user.email_verified = True
    user.email_verification_code_hash = None
    user.email_verification_expires_at = None
    user.email_verification_attempts = 0
    await db.flush()
    token = await _issue_token_for_user(db, user)
    await db.commit()
    logger.info("auth.email_verified", user_id=str(user.id), email=user.email)
    return JSONResponse({"access_token": token, "token_type": "bearer"})


@router.post("/resend-code")
async def resend_code(body: ResendCodeRequest, db: DbSession) -> JSONResponse:
    """renvoie un code (cooldown)."""
    r = await db.execute(select(User).where(User.email == body.email))
    user = r.scalar_one_or_none()
    if user is None or user.email_verified:
        return JSONResponse({"status": "sent"})

    now = datetime.now(UTC)
    last = user.email_verification_sent_at
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        elapsed = (now - last).total_seconds()
        if elapsed < RESEND_COOLDOWN_SECONDS:
            raise HTTPException(429, "Veuillez patienter avant de redemander un code.")

    code = generate_code()
    user.email_verification_code_hash = hash_code(code)
    user.email_verification_expires_at = code_expiry(now)
    user.email_verification_attempts = 0
    user.email_verification_sent_at = now
    await db.commit()

    await _send_verification_email(user, code)
    logger.info("auth.resend.code_sent", user_id=str(user.id), email=user.email)

    payload: dict = {"status": "sent"}
    if get_settings().is_test:
        payload["debug_code"] = code
    return JSONResponse(payload)


# mot de passe oublié


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=4, max_length=10)
    new_password: str = Field(..., min_length=8, max_length=128)


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, db: DbSession) -> JSONResponse:
    """envoie un code de reset."""
    r = await db.execute(select(User).where(User.email == body.email))
    user = r.scalar_one_or_none()
    if user is None or not user.password_hash:
        return JSONResponse({"status": "sent"})

    now = datetime.now(UTC)
    code = generate_code()
    user.password_reset_code_hash = hash_code(code)
    user.password_reset_expires_at = code_expiry(now)
    await db.commit()

    await _send_reset_email(user, code)
    logger.info("auth.forgot_password.code_sent", user_id=str(user.id))

    payload: dict = {"status": "sent"}
    if get_settings().is_test:
        payload["debug_code"] = code
    return JSONResponse(payload)


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, db: DbSession) -> JSONResponse:
    """reset via code email."""
    r = await db.execute(select(User).where(User.email == body.email))
    user = r.scalar_one_or_none()
    if user is None or not user.password_reset_code_hash:
        raise HTTPException(400, "Code invalide ou expiré")
    if is_expired(user.password_reset_expires_at):
        raise HTTPException(400, "Code expiré, redemandez-en un")
    if not verify_code(body.code.strip(), user.password_reset_code_hash):
        raise HTTPException(400, "Code invalide")
    pw_err = _check_password_strength(body.new_password)
    if pw_err:
        raise HTTPException(400, pw_err)

    user.password_hash = hash_password(body.new_password)
    user.password_reset_code_hash = None
    user.password_reset_expires_at = None
    user.email_verified = True  # adresse prouvée par email
    await db.commit()
    logger.info("auth.reset_password.done", user_id=str(user.id))
    return JSONResponse({"status": "reset"})


class UpdateMeRequest(BaseModel):
    """maj profil utilisateur."""

    full_name: str | None = Field(None, min_length=1, max_length=255)
    current_password: str | None = Field(None, min_length=1, max_length=128)
    new_password: str | None = Field(None, min_length=8, max_length=128)


async def _me_payload(db, user: User) -> dict:
    """payload du profil."""
    r_m = await db.execute(
        select(BusinessMember).where(BusinessMember.user_id == user.id).limit(1)
    )
    member = r_m.scalar_one_or_none()
    if member is None:
        # user sans business : on crée
        business_id = await _ensure_business_for_user(db, user, user.full_name)
        await db.commit()
        role = "owner"
    else:
        business_id = member.business_id
        role = member.role

    business_name = ""
    if business_id is not None:
        rb = await db.execute(select(Business.name).where(Business.id == business_id))
        business_name = rb.scalar_one_or_none() or ""

    return {
        "id": str(user.id),
        "full_name": user.full_name or "",
        "email": user.email,
        "role": role,
        "status": "online",
        "business_id": str(business_id) if business_id is not None else None,
        "business_name": business_name,
        "is_superuser": bool(user.is_superuser),
    }


@router.get("/me")
async def auth_me(
    db: DbSession,
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict:
    """profil depuis le JWT."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Authorization Bearer requis")
    raw = authorization[7:].strip()
    try:
        payload = decode_token(raw)
    except Exception:
        raise HTTPException(401, "Token invalide") from None
    try:
        uid = UUID(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(401, "Token invalide") from None

    r = await db.execute(select(User).where(User.id == uid))
    user = r.scalar_one_or_none()
    if user is None:
        raise HTTPException(401, "Utilisateur introuvable")

    return await _me_payload(db, user)


@router.patch("/me")
async def update_me(body: UpdateMeRequest, db: DbSession, principal: CurrentUser) -> dict:
    """maj nom et/ou mot de passe."""
    r = await db.execute(select(User).where(User.id == principal.user_id))
    user = r.scalar_one_or_none()
    if user is None:
        raise HTTPException(401, "Utilisateur introuvable")

    if body.full_name is not None:
        user.full_name = body.full_name.strip()

    if body.new_password is not None:
        if not user.password_hash:
            raise HTTPException(
                400, "Aucun mot de passe défini sur ce compte (connexion Google)"
            )
        if not body.current_password or not verify_password(
            body.current_password, user.password_hash
        ):
            raise HTTPException(400, "Mot de passe actuel incorrect")
        pw_err = _check_password_strength(body.new_password)
        if pw_err:
            raise HTTPException(422, pw_err)
        user.password_hash = hash_password(body.new_password)

    await db.commit()
    logger.info("auth.me_updated", user_id=str(user.id))
    return await _me_payload(db, user)


@router.get("/google/login")
async def google_login() -> RedirectResponse:
    settings = get_settings()
    if not settings.google_oauth_client_id:
        raise HTTPException(503, "Google OAuth non configuré")
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "include_granted_scopes": "true",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return RedirectResponse(url)


@router.get("/google/callback")
async def google_callback(
    code: str,
    db: DbSession,
) -> JSONResponse:
    settings = get_settings()
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise HTTPException(503, "Google OAuth non configuré")

    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "redirect_uri": settings.google_oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=30.0,
        )
        if token_res.status_code != 200:
            logger.error("auth.google.token_error", body=token_res.text)
            raise HTTPException(400, "Échange de code Google échoué")
        tokens = token_res.json()
        access = tokens.get("access_token")
        if not access:
            raise HTTPException(400, "Pas d'access_token")

        ui = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access}"},
            timeout=15.0,
        )
        if ui.status_code != 200:
            raise HTTPException(400, "Userinfo Google échoué")
        profile = ui.json()

    sub = profile.get("sub")
    email = profile.get("email")
    name = profile.get("name")
    if not sub or not email:
        raise HTTPException(400, "Profil Google incomplet")

    r = await db.execute(select(User).where(User.google_sub == sub))
    user = r.scalar_one_or_none()
    if user is None:
        r2 = await db.execute(select(User).where(User.email == email))
        user = r2.scalar_one_or_none()
        if user:
            user.google_sub = sub
            user.email_verified = True  # déjà vérifié par Google
            if name:
                user.full_name = name
        else:
            user = User(
                email=email,
                full_name=name,
                google_sub=sub,
                email_verified=True,  # déjà vérifié par Google
            )
            db.add(user)
        await db.flush()
    elif name:
        user.full_name = name

    r3 = await db.execute(select(BusinessMember.business_id).where(BusinessMember.user_id == user.id))
    business_ids = [row[0] for row in r3.all()]
    await db.commit()

    token = create_access_token(user.id, user.email, business_ids)
    return JSONResponse({"access_token": token, "token_type": "bearer"})
