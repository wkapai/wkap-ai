from __future__ import annotations


VALID_WOW_TYPES = {
    "candidate_wow",
    "trackable_wow",
    "scoreable_signal",
    "thesis_wow",
    "status_update",
}

WOW_TYPE_DEFAULT_STATUS = {
    "candidate_wow": "active_candidate",
    "trackable_wow": "active_trackable",
    "scoreable_signal": "pending_scoreable",
    "thesis_wow": "active_thesis",
}

ALLOWED_STATUS_TRANSITIONS = {
    "candidate_wow": {
        "active_candidate": {
            "active_candidate",
            "promoted_trackable",
            "promoted_scoreable",
            "killed",
            "stale",
        },
        "stale": {"active_candidate", "killed", "stale"},
    },
    "trackable_wow": {
        "active_trackable": {
            "active_trackable",
            "promoted_scoreable",
            "killed",
            "stale",
        },
        "stale": {"active_trackable", "killed", "stale"},
    },
    "scoreable_signal": {
        "pending_scoreable": {
            "pending_scoreable",
            "resolved_correct",
            "resolved_incorrect",
            "unresolved",
            "invalid_test",
            "voided",
        },
        "unresolved": {
            "resolved_correct",
            "resolved_incorrect",
            "invalid_test",
            "unresolved",
            "voided",
        },
    },
    "thesis_wow": {
        "active_thesis": {
            "active_thesis",
            "supported",
            "weakened",
            "retired",
        },
        "supported": {"supported", "weakened", "retired"},
        "weakened": {"supported", "weakened", "retired"},
    },
}

TERMINAL_STATUSES = {
    "promoted_trackable",
    "promoted_scoreable",
    "killed",
    "resolved_correct",
    "resolved_incorrect",
    "invalid_test",
    "voided",
    "retired",
}

UPDATE_TYPE_TO_NEW_STATUS = {
    "promotion": {"promoted_trackable", "promoted_scoreable"},
    "resolution": {"resolved_correct", "resolved_incorrect", "unresolved"},
    "killed": {"killed"},
    "stale": {"stale"},
    "voided": {"voided"},
    "invalid_test": {"invalid_test"},
    "thesis_update": {"supported", "weakened", "retired"},
    "evidence": {
        "active_candidate",
        "active_trackable",
        "pending_scoreable",
        "active_thesis",
        "stale",
        "supported",
        "weakened",
        "unresolved",
    },
    "other": set(),
}


def allowed_new_statuses(target_wow_type: str, previous_status: str) -> set[str]:
    return ALLOWED_STATUS_TRANSITIONS.get(target_wow_type, {}).get(previous_status, set())


def validate_status_transition(
    *,
    target_wow_type: str,
    previous_status: str,
    new_status: str,
    update_type: str,
) -> str:
    if target_wow_type not in ALLOWED_STATUS_TRANSITIONS:
        return f"target_wow_type must be one of: {', '.join(sorted(ALLOWED_STATUS_TRANSITIONS))}"
    allowed = allowed_new_statuses(target_wow_type, previous_status)
    if not allowed:
        return f"{target_wow_type} cannot transition from {previous_status}"
    if new_status not in allowed:
        return (
            f"{target_wow_type} cannot transition from {previous_status} to {new_status}; "
            f"allowed: {', '.join(sorted(allowed))}"
        )
    update_allowed = UPDATE_TYPE_TO_NEW_STATUS.get(update_type)
    if update_allowed is None:
        return f"update_type must be one of: {', '.join(sorted(UPDATE_TYPE_TO_NEW_STATUS))}"
    if new_status == previous_status and update_type != "evidence":
        return f"same-status updates must use update_type evidence, not {update_type}"
    if update_type == "evidence" and new_status != previous_status:
        return "update_type evidence requires new_status to equal previous_status"
    if update_allowed and new_status not in update_allowed:
        return f"update_type {update_type} does not allow new_status {new_status}"
    return ""
