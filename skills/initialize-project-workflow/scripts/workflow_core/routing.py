from .schema import pretty_json


ROUTES = {
    "plan": {"role": "pm", "model": "gpt-5.6-sol", "requested_efforts": ["ultra", "max", "xhigh", "high"], "cli_efforts": ["xhigh", "high"]},
    "plan-review": {"role": "plan-reviewer", "model": "gpt-5.6-sol", "requested_efforts": ["ultra", "max", "xhigh", "high"], "cli_efforts": ["xhigh", "high"]},
    "code": {"role": "builder", "model": "gpt-5.6-terra", "requested_efforts": ["xhigh", "high", "medium"], "cli_efforts": ["xhigh", "high", "medium"]},
    "text": {"role": "writer", "model": "gpt-5.6-luna", "requested_efforts": ["xhigh", "high", "medium"], "cli_efforts": ["xhigh", "high", "medium"]},
    "explore": {"role": "explorer", "model": "gpt-5.6-luna", "requested_efforts": ["high", "medium"], "cli_efforts": ["high", "medium"]},
    "test": {"role": "tester", "model": "gpt-5.6-terra", "requested_efforts": ["xhigh", "high"], "cli_efforts": ["xhigh", "high"]},
    "code-review": {"role": "code-reviewer", "model": "gpt-5.6-terra", "requested_efforts": ["xhigh", "high"], "cli_efforts": ["xhigh", "high"]},
    "risk": {"role": "risk-reviewer", "model": "gpt-5.6-sol", "requested_efforts": ["ultra", "max", "xhigh", "high"], "cli_efforts": ["xhigh", "high"]},
    "other": {"role": "explorer", "model": "gpt-5.6-terra", "requested_efforts": ["high", "medium"], "cli_efforts": ["high", "medium"]},
}
ROLE_TO_KIND = {value["role"]: key for key, value in ROUTES.items()}
ROLE_ROUTES = {
    "reporter": {
        "role": "reporter",
        "model": "gpt-5.6-luna",
        "requested_efforts": ["xhigh", "high", "medium"],
        "cli_efforts": ["xhigh", "high", "medium"],
    },
}

UNSUPPORTED_EFFORT_MARKERS = ("unsupported reasoning effort", "unsupported effort", "effort is not supported", "model does not support effort", "invalid reasoning effort", "unknown variant.*ultra", "unknown variant.*max")
BLOCKING_ERROR_MARKERS = ("authentication", "unauthorized", "account_deactivated", "token_invalidated", "rate limit", "429", "401", "403", "408", "500", "502", "503", "504", "quota", "timeout", "network", "connection reset", "provider", "model not found", "model_not_found", "unknown model", "does not exist", "permission denied")


def classify_worker_error(message):
    text = str(message).lower()
    import re
    if any(marker in text for marker in BLOCKING_ERROR_MARKERS):
        return "blocked_external"
    if any(re.search(marker, text) for marker in UNSUPPORTED_EFFORT_MARKERS):
        return "unsupported_effort"
    return "worker_failure"


def next_effort(route, current_effort, error_message):
    if classify_worker_error(error_message) != "unsupported_effort":
        return None
    chain = route.get("requested_efforts", [])
    try:
        return chain[chain.index(current_effort) + 1]
    except (ValueError, IndexError):
        return None


def select_backend(route, native_capabilities=None):
    """Select native only when both requested model and effort are proven."""
    native_capabilities = native_capabilities or {}
    model_caps = native_capabilities.get(route["requested_model"], {})
    supported_efforts = set(model_caps.get("reasoning_efforts", []))
    if route["requested_model"] in native_capabilities and route["requested_effort"] in supported_efforts:
        return {"backend": "native", "model": route["requested_model"], "effort": route["requested_effort"], "verified": True}
    return {"backend": "codex-exec", "model": route["requested_model"], "effort": route["effective_effort"], "verified": False, "reason": "native_capability_not_proven"}
def resolve_route(kind):
    role_only = kind in ROLE_ROUTES
    if role_only:
        source = ROLE_ROUTES[kind]
        route_kind = "text"
    else:
        if kind in ROLE_TO_KIND:
            kind = ROLE_TO_KIND[kind]
        if kind not in ROUTES:
            raise ValueError(f"unsupported task kind or role: {kind}")
        source = ROUTES[kind]
        route_kind = kind
    route = dict(source)
    route["kind"] = route_kind
    route["role"] = source["role"]
    route["requested_model"] = source["model"]
    route["requested_effort"] = source["requested_efforts"][0]
    route["effective_effort"] = source["cli_efforts"][0]
    route["effort_fallback_reason"] = "cli_parser_unsupported" if route["requested_effort"] != route["effective_effort"] else None
    route["backend_policy"] = "native-if-capable-otherwise-codex-exec"
    route["model_verification"] = "record requested/configured/provider_observed separately; provider attestation may be unavailable"
    route["route_decision_required"] = route_kind == "other"
    if route_kind == "other":
        route["route_decision"] = {
            "selected": "explore",
            "reason": "classification is uncertain; gather read-only evidence before selecting a write role",
            "candidates": ["plan", "code", "text", "explore", "test", "code-review", "risk"],
        }
    return route


def route_command(args):
    try:
        return 0, resolve_route(args.kind)
    except ValueError as exc:
        return 2, {"error": "route_invalid", "message": str(exc)}
