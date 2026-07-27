"""Idempotent demo-user seeding (Phase 9, ADR 0009). Run once at every
startup (app.main's startup event) — inserts only the accounts that don't
already exist by email, so it's safe to call on every container start,
including against a persistent dev volume that already has these rows.

Every account here is a documented, local-development-only credential (see
.env.example) — never a real one. Also seeds a scoped `ops`-role service
account other backend processes authenticate as for machine-to-machine
calls against this gateway's protected routes (failure-lab's GatewayClient,
the only current caller — see DECISIONS.md "Phase 9").
"""

import logging

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User
from app.security import hash_password

logger = logging.getLogger("api_gateway.seed")


def seed_demo_users(db: Session) -> None:
    settings = get_settings()
    if not settings.seed_demo_users:
        return

    seed_accounts = [
        (settings.seed_admin_email, settings.seed_admin_password, "admin"),
        (settings.seed_ops_email, settings.seed_ops_password, "ops"),
        (settings.seed_viewer_email, settings.seed_viewer_password, "viewer"),
        (settings.seed_service_email, settings.seed_service_password, "ops"),
    ]
    for email, password, role in seed_accounts:
        existing = db.query(User).filter(User.email == email).one_or_none()
        if existing is not None:
            continue
        db.add(User(email=email, password_hash=hash_password(password), role=role))
        logger.info("seeded demo user", extra={"email": email, "role": role})
    db.commit()
