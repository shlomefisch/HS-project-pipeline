from fastapi import APIRouter

from ..config import settings
from ..rules import constants as C

router = APIRouter(tags=["meta"])


@router.get("/config")
def public_config():
    """What the sign-in screen needs before anyone is signed in."""
    return {
        "google_client_id": settings.google_client_id,
        "allowed_domain": settings.allowed_domain,
        "dev_login": settings.dev_login,
    }


@router.get("/meta")
def meta():
    """The fixed lists, so the app never hard-codes them."""
    return {
        "classes": C.CLASSES,
        "showrooms": C.SHOWROOMS,
        "user_roles": C.USER_ROLES,
        "role_caps": C.ROLE_CAPS,
        "role_labels": C.ROLE_LABELS,
        "lead_sources": C.LEAD_SOURCES,
        "project_types": C.PROJECT_TYPES,
        "playbook_for_type": C.PLAYBOOK_FOR_TYPE,
        "loss_reasons": C.LOSS_REASONS,
        "candidate_sources": C.CANDIDATE_SOURCES,
        "event_kinds": C.EVENT_KINDS,
        "channels": C.CHANNELS,
        "severities": list(C.SEVERITIES),
    }
