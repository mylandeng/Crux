from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from curx.core.config import Settings
from curx.core.security import (
    InvalidAccessKeyFormat,
    access_key_prefix,
    generate_access_key,
    generate_session_token,
    hash_access_key,
    hash_session_token,
    verify_access_key,
)
from curx.domain.auth_schemas import AccessKeyCreateRequest, KnowledgeSpaceCreateRequest
from curx.domain.models import (
    AccessKey,
    AccessKeyKnowledgeSpaceGrant,
    AuditLog,
    BrowserSession,
    KeyBinding,
    KnowledgeSpace,
    Role,
    Tenant,
    User,
    UserKnowledgeSpaceGrant,
    utc_now,
)

ROLE_PERMISSIONS = {
    "member": ["chat:use", "knowledge:read"],
    "operator": [
        "chat:use",
        "knowledge:read",
        "knowledge:write",
        "feedback:manage",
    ],
    "admin": ["*"],
}


class IdentityError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RequestMetadata:
    ip_address: str | None
    user_agent: str | None


@dataclass(frozen=True)
class AuthenticatedIdentity:
    tenant: Tenant
    user: User
    role: Role
    browser_session: BrowserSession
    binding: KeyBinding
    access_key: AccessKey


@dataclass(frozen=True)
class BoundSession:
    identity: AuthenticatedIdentity
    raw_session_token: str


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def normalize_username(username: str) -> str:
    return username.strip().lower()


def record_audit(
    db: Session,
    *,
    action: str,
    outcome: str,
    metadata: RequestMetadata,
    tenant_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    subject: str | None = None,
    details: dict[str, object] | None = None,
) -> AuditLog:
    log = AuditLog(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        subject=subject,
        outcome=outcome,
        ip_address=metadata.ip_address,
        user_agent=metadata.user_agent,
        details=details or {},
    )
    db.add(log)
    return log


def ensure_role(db: Session, tenant_id: UUID, name: str) -> Role:
    if name not in ROLE_PERMISSIONS:
        raise IdentityError(422, "invalid_role", "Unsupported role.")
    role = db.scalar(
        select(Role).where(Role.tenant_id == tenant_id, Role.name == name)
    )
    if role is not None:
        return role
    role = Role(
        tenant_id=tenant_id,
        name=name,
        permissions=ROLE_PERMISSIONS[name],
    )
    db.add(role)
    db.flush()
    return role


def access_key_status(access_key: AccessKey, now: datetime | None = None) -> str:
    checked_at = now or utc_now()
    if access_key.revoked_at is not None:
        return "revoked"
    if as_utc(access_key.expires_at) <= checked_at:
        return "expired"
    if as_utc(access_key.active_from) > checked_at:
        return "scheduled"
    return "active"


def _login_failure_count(
    db: Session,
    username: str,
    settings: Settings,
    metadata: RequestMetadata,
) -> int:
    cutoff = utc_now() - timedelta(seconds=settings.auth_attempt_window_seconds)
    conditions = [
        AuditLog.action == "auth.bind",
        AuditLog.outcome == "failure",
        AuditLog.subject == username,
        AuditLog.created_at >= cutoff,
    ]
    if metadata.ip_address is not None:
        conditions.append(AuditLog.ip_address == metadata.ip_address)
    return int(
        db.scalar(
            select(func.count(AuditLog.id)).where(*conditions)
        )
        or 0
    )


def _reject_login(
    db: Session,
    *,
    username: str,
    metadata: RequestMetadata,
    reason: str,
    tenant_id: UUID | None = None,
    key_prefix: str | None = None,
) -> NoReturn:
    record_audit(
        db,
        tenant_id=tenant_id,
        action="auth.bind",
        outcome="failure",
        subject=username,
        metadata=metadata,
        details={"reason": reason, "key_prefix": key_prefix},
    )
    db.commit()
    raise IdentityError(
        401,
        "invalid_credentials",
        "Username or Curx access key is invalid.",
    )


def _validate_key_is_active(access_key: AccessKey, now: datetime) -> bool:
    return (
        access_key.revoked_at is None
        and as_utc(access_key.active_from) <= now
        and as_utc(access_key.expires_at) > now
    )


def _grant_user_spaces(
    db: Session,
    *,
    user: User,
    role_name: str,
    access_key: AccessKey,
) -> None:
    if access_key.all_spaces:
        space_ids = list(
            db.scalars(
                select(KnowledgeSpace.id).where(
                    KnowledgeSpace.tenant_id == access_key.tenant_id,
                    KnowledgeSpace.status == "active",
                )
            )
        )
    else:
        space_ids = [grant.knowledge_space_id for grant in access_key.space_grants]

    for space_id in space_ids:
        grant = db.scalar(
            select(UserKnowledgeSpaceGrant).where(
                UserKnowledgeSpaceGrant.user_id == user.id,
                UserKnowledgeSpaceGrant.knowledge_space_id == space_id,
            )
        )
        can_write = role_name in {"operator", "admin"}
        can_manage = role_name == "admin"
        if grant is None:
            db.add(
                UserKnowledgeSpaceGrant(
                    tenant_id=user.tenant_id,
                    user_id=user.id,
                    knowledge_space_id=space_id,
                    can_read=True,
                    can_write=can_write,
                    can_manage=can_manage,
                )
            )
        else:
            grant.can_read = True
            grant.can_write = grant.can_write or can_write
            grant.can_manage = grant.can_manage or can_manage


def bind_access_key(
    db: Session,
    *,
    username: str,
    display_name: str | None,
    raw_access_key: str,
    settings: Settings,
    metadata: RequestMetadata,
) -> BoundSession:
    normalized_username = normalize_username(username)
    if (
        _login_failure_count(db, normalized_username, settings, metadata)
        >= settings.auth_attempt_limit
    ):
        record_audit(
            db,
            action="auth.bind",
            outcome="rate_limited",
            subject=normalized_username,
            metadata=metadata,
            details={"window_seconds": settings.auth_attempt_window_seconds},
        )
        db.commit()
        raise IdentityError(
            429,
            "too_many_attempts",
            "Too many failed attempts. Try again later.",
        )

    try:
        prefix = access_key_prefix(raw_access_key)
    except InvalidAccessKeyFormat:
        _reject_login(
            db,
            username=normalized_username,
            metadata=metadata,
            reason="invalid_format",
        )

    access_key = db.scalar(
        select(AccessKey)
        .options(
            selectinload(AccessKey.space_grants),
            selectinload(AccessKey.binding),
        )
        .where(AccessKey.prefix == prefix)
    )
    if access_key is None:
        _reject_login(
            db,
            username=normalized_username,
            metadata=metadata,
            reason="unknown_prefix",
            key_prefix=prefix,
        )

    now = utc_now()
    if not verify_access_key(raw_access_key, access_key.key_hash):
        _reject_login(
            db,
            username=normalized_username,
            metadata=metadata,
            reason="hash_mismatch",
            tenant_id=access_key.tenant_id,
            key_prefix=prefix,
        )
    if not _validate_key_is_active(access_key, now):
        _reject_login(
            db,
            username=normalized_username,
            metadata=metadata,
            reason=access_key_status(access_key, now),
            tenant_id=access_key.tenant_id,
            key_prefix=prefix,
        )

    binding = access_key.binding
    if binding is not None:
        user = db.get(User, binding.user_id)
        if (
            user is None
            or normalize_username(user.username) != normalized_username
            or binding.revoked_at is not None
            or as_utc(binding.valid_until) <= now
        ):
            _reject_login(
                db,
                username=normalized_username,
                metadata=metadata,
                reason="binding_mismatch",
                tenant_id=access_key.tenant_id,
                key_prefix=prefix,
            )
    else:
        user = db.scalar(
            select(User)
            .options(selectinload(User.role))
            .where(
                User.tenant_id == access_key.tenant_id,
                User.username == normalized_username,
            )
        )
        if user is None:
            role = ensure_role(db, access_key.tenant_id, access_key.granted_role)
            user = User(
                tenant_id=access_key.tenant_id,
                role_id=role.id,
                username=normalized_username,
                display_name=(display_name or normalized_username).strip(),
                authorization_version=1,
            )
            db.add(user)
            db.flush()
        elif user.role.name != access_key.granted_role:
            _reject_login(
                db,
                username=normalized_username,
                metadata=metadata,
                reason="role_mismatch",
                tenant_id=access_key.tenant_id,
                key_prefix=prefix,
            )

        binding = KeyBinding(
            tenant_id=access_key.tenant_id,
            access_key_id=access_key.id,
            user_id=user.id,
            authorization_version=1,
            valid_until=access_key.expires_at,
        )
        db.add(binding)
        db.flush()

    if user.status != "active":
        _reject_login(
            db,
            username=normalized_username,
            metadata=metadata,
            reason="inactive_user",
            tenant_id=access_key.tenant_id,
            key_prefix=prefix,
        )

    role = db.get(Role, user.role_id)
    tenant = db.get(Tenant, user.tenant_id)
    if role is None or tenant is None or tenant.status != "active":
        _reject_login(
            db,
            username=normalized_username,
            metadata=metadata,
            reason="inactive_tenant_or_role",
            tenant_id=access_key.tenant_id,
            key_prefix=prefix,
        )

    _grant_user_spaces(db, user=user, role_name=role.name, access_key=access_key)

    session_expires_at = min(
        now + timedelta(hours=settings.session_ttl_hours),
        as_utc(access_key.expires_at),
        as_utc(binding.valid_until),
    )
    raw_session_token = generate_session_token()
    browser_session = BrowserSession(
        tenant_id=user.tenant_id,
        user_id=user.id,
        key_binding_id=binding.id,
        token_hash=hash_session_token(raw_session_token),
        user_authorization_version=user.authorization_version,
        binding_authorization_version=binding.authorization_version,
        access_key_authorization_version=access_key.authorization_version,
        expires_at=session_expires_at,
        ip_address=metadata.ip_address,
        user_agent=metadata.user_agent,
    )
    user.last_login_at = now
    db.add(browser_session)
    db.flush()
    record_audit(
        db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="auth.bind",
        target_type="session",
        target_id=str(browser_session.id),
        subject=normalized_username,
        outcome="success",
        metadata=metadata,
        details={"key_prefix": prefix},
    )
    db.commit()

    identity = AuthenticatedIdentity(
        tenant=tenant,
        user=user,
        role=role,
        browser_session=browser_session,
        binding=binding,
        access_key=access_key,
    )
    return BoundSession(identity=identity, raw_session_token=raw_session_token)


def authenticate_session(
    db: Session,
    *,
    raw_session_token: str,
    metadata: RequestMetadata,
) -> AuthenticatedIdentity:
    browser_session = db.scalar(
        select(BrowserSession)
        .options(
            selectinload(BrowserSession.user).selectinload(User.role),
            selectinload(BrowserSession.user).selectinload(User.tenant),
            selectinload(BrowserSession.binding).selectinload(KeyBinding.access_key),
        )
        .where(BrowserSession.token_hash == hash_session_token(raw_session_token))
    )
    if browser_session is None:
        raise IdentityError(401, "invalid_session", "Authentication is required.")

    now = utc_now()
    user = browser_session.user
    role = user.role
    tenant = user.tenant
    binding = browser_session.binding
    access_key = binding.access_key
    valid = (
        browser_session.revoked_at is None
        and as_utc(browser_session.expires_at) > now
        and user.status == "active"
        and tenant.status == "active"
        and binding.revoked_at is None
        and as_utc(binding.valid_until) > now
        and _validate_key_is_active(access_key, now)
        and browser_session.user_authorization_version == user.authorization_version
        and browser_session.binding_authorization_version == binding.authorization_version
        and browser_session.access_key_authorization_version
        == access_key.authorization_version
    )
    if not valid:
        if browser_session.revoked_at is None:
            browser_session.revoked_at = now
            db.commit()
        raise IdentityError(401, "expired_session", "The session is no longer valid.")

    if now - as_utc(browser_session.last_seen_at) >= timedelta(minutes=1):
        browser_session.last_seen_at = now
        db.commit()

    return AuthenticatedIdentity(
        tenant=tenant,
        user=user,
        role=role,
        browser_session=browser_session,
        binding=binding,
        access_key=access_key,
    )


def logout(
    db: Session,
    *,
    identity: AuthenticatedIdentity,
    metadata: RequestMetadata,
) -> None:
    identity.browser_session.revoked_at = utc_now()
    record_audit(
        db,
        tenant_id=identity.tenant.id,
        actor_user_id=identity.user.id,
        action="auth.logout",
        target_type="session",
        target_id=str(identity.browser_session.id),
        subject=identity.user.username,
        outcome="success",
        metadata=metadata,
    )
    db.commit()


def create_access_key(
    db: Session,
    *,
    actor: AuthenticatedIdentity,
    payload: AccessKeyCreateRequest,
    metadata: RequestMetadata,
) -> tuple[AccessKey, str]:
    now = utc_now()
    active_from = as_utc(payload.active_from) if payload.active_from else now
    expires_at = as_utc(payload.expires_at)
    if expires_at <= now or expires_at <= active_from:
        raise IdentityError(
            422,
            "invalid_expiry",
            "Access key expiry must be later than its activation time.",
        )
    if payload.all_spaces and payload.knowledge_space_ids:
        raise IdentityError(
            422,
            "ambiguous_space_scope",
            "Choose all spaces or an explicit list, not both.",
        )

    spaces: list[KnowledgeSpace] = []
    if payload.knowledge_space_ids:
        spaces = list(
            db.scalars(
                select(KnowledgeSpace).where(
                    KnowledgeSpace.id.in_(payload.knowledge_space_ids),
                    KnowledgeSpace.tenant_id == actor.tenant.id,
                    KnowledgeSpace.status == "active",
                )
            )
        )
        if len(spaces) != len(set(payload.knowledge_space_ids)):
            raise IdentityError(
                422,
                "invalid_space_scope",
                "One or more knowledge spaces are unavailable.",
            )

    raw_key, prefix = generate_access_key()
    access_key = AccessKey(
        tenant_id=actor.tenant.id,
        prefix=prefix,
        key_hash=hash_access_key(raw_key),
        label=payload.label.strip(),
        granted_role=payload.granted_role,
        all_spaces=payload.all_spaces,
        active_from=active_from,
        expires_at=expires_at,
        authorization_version=1,
        created_by_user_id=actor.user.id,
    )
    db.add(access_key)
    db.flush()
    for space in spaces:
        db.add(
            AccessKeyKnowledgeSpaceGrant(
                tenant_id=actor.tenant.id,
                access_key_id=access_key.id,
                knowledge_space_id=space.id,
            )
        )
    record_audit(
        db,
        tenant_id=actor.tenant.id,
        actor_user_id=actor.user.id,
        action="access_key.create",
        target_type="access_key",
        target_id=str(access_key.id),
        subject=prefix,
        outcome="success",
        metadata=metadata,
        details={
            "granted_role": payload.granted_role,
            "all_spaces": payload.all_spaces,
            "space_count": len(spaces),
            "expires_at": expires_at.isoformat(),
        },
    )
    db.commit()
    db.refresh(access_key)
    return access_key, raw_key


def list_access_keys(db: Session, actor: AuthenticatedIdentity) -> list[AccessKey]:
    return list(
        db.scalars(
            select(AccessKey)
            .options(
                selectinload(AccessKey.space_grants),
                selectinload(AccessKey.binding).selectinload(KeyBinding.user),
            )
            .where(AccessKey.tenant_id == actor.tenant.id)
            .order_by(AccessKey.created_at.desc())
        )
    )


def revoke_access_key(
    db: Session,
    *,
    actor: AuthenticatedIdentity,
    access_key_id: UUID,
    metadata: RequestMetadata,
) -> AccessKey:
    access_key = db.scalar(
        select(AccessKey)
        .options(
            selectinload(AccessKey.space_grants),
            selectinload(AccessKey.binding).selectinload(KeyBinding.user),
        )
        .where(
            AccessKey.id == access_key_id,
            AccessKey.tenant_id == actor.tenant.id,
        )
    )
    if access_key is None:
        raise IdentityError(404, "access_key_not_found", "Access key was not found.")

    if access_key.revoked_at is None:
        now = utc_now()
        access_key.revoked_at = now
        access_key.authorization_version += 1
        if access_key.binding is not None:
            access_key.binding.revoked_at = now
            access_key.binding.authorization_version += 1
            db.execute(
                update(BrowserSession)
                .where(
                    BrowserSession.key_binding_id == access_key.binding.id,
                    BrowserSession.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
        record_audit(
            db,
            tenant_id=actor.tenant.id,
            actor_user_id=actor.user.id,
            action="access_key.revoke",
            target_type="access_key",
            target_id=str(access_key.id),
            subject=access_key.prefix,
            outcome="success",
            metadata=metadata,
        )
        db.commit()
    return access_key


def create_knowledge_space(
    db: Session,
    *,
    actor: AuthenticatedIdentity,
    payload: KnowledgeSpaceCreateRequest,
    metadata: RequestMetadata,
) -> KnowledgeSpace:
    existing = db.scalar(
        select(KnowledgeSpace).where(
            KnowledgeSpace.tenant_id == actor.tenant.id,
            KnowledgeSpace.name == payload.name.strip(),
        )
    )
    if existing is not None:
        raise IdentityError(
            409,
            "knowledge_space_exists",
            "A knowledge space with this name already exists.",
        )

    space = KnowledgeSpace(
        tenant_id=actor.tenant.id,
        name=payload.name.strip(),
        description=payload.description.strip(),
        visibility=payload.visibility,
        color=payload.color,
        icon=payload.icon,
        created_by_user_id=actor.user.id,
    )
    db.add(space)
    db.flush()
    db.add(
        UserKnowledgeSpaceGrant(
            tenant_id=actor.tenant.id,
            user_id=actor.user.id,
            knowledge_space_id=space.id,
            can_read=True,
            can_write=True,
            can_manage=True,
        )
    )

    all_space_bindings = list(
        db.scalars(
            select(KeyBinding)
            .join(AccessKey, AccessKey.id == KeyBinding.access_key_id)
            .where(
                AccessKey.tenant_id == actor.tenant.id,
                AccessKey.all_spaces.is_(True),
                AccessKey.revoked_at.is_(None),
                KeyBinding.revoked_at.is_(None),
            )
        )
    )
    for binding in all_space_bindings:
        bound_user = db.get(User, binding.user_id)
        if bound_user is None or bound_user.id == actor.user.id:
            continue
        bound_role = db.get(Role, bound_user.role_id)
        if bound_role is None:
            continue
        db.add(
            UserKnowledgeSpaceGrant(
                tenant_id=actor.tenant.id,
                user_id=bound_user.id,
                knowledge_space_id=space.id,
                can_read=True,
                can_write=bound_role.name in {"operator", "admin"},
                can_manage=bound_role.name == "admin",
            )
        )

    record_audit(
        db,
        tenant_id=actor.tenant.id,
        actor_user_id=actor.user.id,
        action="knowledge_space.create",
        target_type="knowledge_space",
        target_id=str(space.id),
        subject=space.name,
        outcome="success",
        metadata=metadata,
    )
    db.commit()
    db.refresh(space)
    return space


def list_user_spaces(
    db: Session,
    identity: AuthenticatedIdentity,
) -> list[tuple[KnowledgeSpace, UserKnowledgeSpaceGrant]]:
    return list(
        db.execute(
            select(KnowledgeSpace, UserKnowledgeSpaceGrant)
            .join(
                UserKnowledgeSpaceGrant,
                UserKnowledgeSpaceGrant.knowledge_space_id == KnowledgeSpace.id,
            )
            .where(
                UserKnowledgeSpaceGrant.user_id == identity.user.id,
                UserKnowledgeSpaceGrant.can_read.is_(True),
                KnowledgeSpace.status == "active",
            )
            .order_by(KnowledgeSpace.name)
        ).all()
    )


def bootstrap_admin(
    db: Session,
    *,
    tenant_name: str,
    tenant_slug: str,
    username: str,
    display_name: str,
    expires_in_days: int,
    create_default_space: bool = True,
) -> tuple[Tenant, User, AccessKey, str]:
    normalized_slug = tenant_slug.strip().lower()
    tenant = db.scalar(select(Tenant).where(Tenant.slug == normalized_slug))
    if tenant is None:
        tenant = Tenant(name=tenant_name.strip(), slug=normalized_slug)
        db.add(tenant)
        db.flush()

    for role_name in ROLE_PERMISSIONS:
        ensure_role(db, tenant.id, role_name)
    admin_role = ensure_role(db, tenant.id, "admin")

    normalized_username = normalize_username(username)
    user = db.scalar(
        select(User).where(
            User.tenant_id == tenant.id,
            User.username == normalized_username,
        )
    )
    if user is None:
        user = User(
            tenant_id=tenant.id,
            role_id=admin_role.id,
            username=normalized_username,
            display_name=display_name.strip(),
            authorization_version=1,
        )
        db.add(user)
        db.flush()
    elif user.role_id != admin_role.id:
        raise IdentityError(
            409,
            "bootstrap_role_conflict",
            "The bootstrap username already exists with another role.",
        )

    if create_default_space:
        default_space = db.scalar(
            select(KnowledgeSpace).where(
                KnowledgeSpace.tenant_id == tenant.id,
                KnowledgeSpace.name == "默认知识空间",
            )
        )
        if default_space is None:
            default_space = KnowledgeSpace(
                tenant_id=tenant.id,
                name="默认知识空间",
                description="Curx 初始知识空间",
                visibility="private",
                created_by_user_id=user.id,
            )
            db.add(default_space)
            db.flush()
        existing_grant = db.scalar(
            select(UserKnowledgeSpaceGrant).where(
                UserKnowledgeSpaceGrant.user_id == user.id,
                UserKnowledgeSpaceGrant.knowledge_space_id == default_space.id,
            )
        )
        if existing_grant is None:
            db.add(
                UserKnowledgeSpaceGrant(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    knowledge_space_id=default_space.id,
                    can_read=True,
                    can_write=True,
                    can_manage=True,
                )
            )

    raw_key, prefix = generate_access_key()
    access_key = AccessKey(
        tenant_id=tenant.id,
        prefix=prefix,
        key_hash=hash_access_key(raw_key),
        label=f"Bootstrap admin key for {normalized_username}",
        granted_role="admin",
        all_spaces=True,
        active_from=utc_now(),
        expires_at=utc_now() + timedelta(days=expires_in_days),
        authorization_version=1,
        created_by_user_id=user.id,
    )
    db.add(access_key)
    db.flush()
    record_audit(
        db,
        tenant_id=tenant.id,
        actor_user_id=user.id,
        action="identity.bootstrap",
        target_type="access_key",
        target_id=str(access_key.id),
        subject=normalized_username,
        outcome="success",
        metadata=RequestMetadata(ip_address=None, user_agent="curx-cli"),
        details={"key_prefix": prefix},
    )
    db.commit()
    return tenant, user, access_key, raw_key
