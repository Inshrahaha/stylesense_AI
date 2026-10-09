"""
Audit logging — append-only log of security-relevant actions.
"""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import hash_ip
from app.db.models.models import AuditLog

logger = get_logger("audit")


async def log_audit_event(
    db: AsyncSession,
    action: str,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    meta: dict | None = None,
) -> None:
    """
    Record a security-relevant event to the audit log.

    Actions: login, login_failed, logout, register, password_change,
    token_refresh, token_reuse_detected, data_export, account_delete,
    consent_change, media_upload, media_delete, admin_action
    """
    entry = AuditLog(
        user_id=user_id,
        action=action,
        ip_hash=hash_ip(ip_address) if ip_address else None,
        meta=meta,
    )
    db.add(entry)
    # Don't commit here — let the caller's transaction handle it
    logger.info(
        f"Audit: {action}",
        extra={
            "user_id": str(user_id) if user_id else None,
            "action": action,
        },
    )
