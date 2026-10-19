"""The fixed lists the business runs on. One place, so screens and rules agree."""

CLASSES = ["Brooklyn Projects", "Brooklyn Showroom", "Monsey Showroom", "NYC Projects"]

SHOWROOMS = ["Brooklyn", "Monsey"]

USER_ROLES = ["pending", "rep", "back_office", "management", "viewer"]
WRITER_ROLES = {"rep", "back_office", "management"}

# Customer-side roles and how many may be active at once. None = no limit.
# Raising a cap later is a change here, not a schema change.
ROLE_CAPS: dict[str, int | None] = {
    "owner": 1,
    "designer": 1,
    "contractor": 1,
    "installer": 1,
    "pm": 1,
    "other": None,
}
ROLE_LABELS = {
    "owner": "Owner",
    "designer": "Designer",
    "contractor": "Contractor",
    "installer": "Installer",
    "pm": "PM (customer's project manager)",
    "other": "Other",
}

LEAD_SOURCES = {
    "designer": "Designer",
    "contractor": "Contractor",
    "installer": "Installer",
    "recommendation": "Recommendation",
    "walk_in": "Walk-in",
}

PROJECT_TYPES = {
    "single_family": "Single-family",
    "multi_unit": "Multi-unit",
    "commercial": "Commercial",
    "retail": "Retail",
    "school": "School",
    "shul_mikvah": "Shul / mikvah",
}
# Six types, two playbooks.
PLAYBOOK_FOR_TYPE = {
    "single_family": "single_family",
    "multi_unit": "projects",
    "commercial": "projects",
    "retail": "projects",
    "school": "projects",
    "shul_mikvah": "projects",
}

LOSS_REASONS = {
    "price": "Price",
    "timing": "Timing",
    "competitor": "Went to a competitor",
    "cancelled": "Project cancelled",
    "bought_direct": "Bought direct",
    "other": "Other",
}

CANDIDATE_SOURCES = {"stock": "Our stock", "local": "Local supply", "overseas": "Overseas"}

EVENT_KINDS = {"contact": "Contact", "showroom_visit": "Showroom visit", "site_visit": "Site visit"}
CHANNELS = ["phone", "text", "email", "whatsapp", "in_person"]

TASK_OPEN = ("open", "blocked")
TASK_OUTCOMES = ("done", "blocked", "bad_answer", "skipped")
SEVERITIES = ("silent", "notify", "interrupt")
