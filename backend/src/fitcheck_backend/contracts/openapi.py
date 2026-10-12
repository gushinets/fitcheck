from copy import deepcopy
import re
from fastapi import FastAPI
from pydantic.json_schema import models_json_schema
from fitcheck_backend.api.errors import ErrorEnvelope
from fitcheck_backend.contracts.operations import PLANNED_OPERATIONS, LEGACY_ERROR_STATUS

ERRORS = {400: "invalid_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found",
          409: "conflict", 413: "body_too_large", 415: "unsupported_content_type", 429: "rate_limited",
          500: "internal_error", 502: "upstream_failure", 503: "service_unavailable", 504: "timeout"}
SECURITY = {
    "public": [], "web": [{"webSession": []}],
    "account": [{"webSession": []}],
    "identity": [{"webSession": []}, {"guestSession": []}],
    "claim": [{"webSession": [], "guestSession": []}],
}


def ref(model):
    return {"$ref": f"#/components/schemas/{model.__name__}"}


def security_schemes():
    return {
        'webSession': {'type':'apiKey','in':'cookie','name':'__Host-fitcheck_session',
                       'description':'Secure HttpOnly SameSite=Lax Path=/, no Domain; separate dev HTTP cookie. Cookie mutations require verified Origin and CSRF.'},
        'guestSession': {'type':'apiKey','in':'cookie','name':'__Host-fitcheck_guest',
                         'description':'Server-issued guest session, never a client-supplied guestId; separate dev HTTP cookie.'},
    }


def _omit_absent_defaults(value):
    if isinstance(value, dict):
        # Optional non-nullable fields omit the value rather than promise a null default.
        if value.get("default", 1) is None and "anyOf" not in value and value.get("type") != "null":
            value.pop("default")
        for child in value.values():
            _omit_absent_defaults(child)
    elif isinstance(value, list):
        for child in value:
            _omit_absent_defaults(child)


def export_openapi(app: FastAPI) -> dict:
    document = deepcopy(app.openapi())
    models = {ErrorEnvelope}
    for operation in PLANNED_OPERATIONS:
        models.update(m for m in [operation.request, operation.response] if m is not None)
    _, schema = models_json_schema([(m, "validation") for m in sorted(models, key=lambda m: m.__name__)],
                                  ref_template="#/components/schemas/{model}")
    document.setdefault("components", {}).setdefault("schemas", {}).update(schema.get("$defs", {}))
    _omit_absent_defaults(document["components"]["schemas"])
    document["components"]["securitySchemes"] = security_schemes()
    document["x-fitcheck-legacy-error-status"] = LEGACY_ERROR_STATUS
    for item in document["paths"].values():
        for operation in item.values():
            operation["x-fitcheck-implementation"] = "implemented"
            operation.setdefault("x-fitcheck-owner-task", "ANY-643")
    for operation in PLANNED_OPERATIONS:
        if operation.method in document['paths'].get(operation.path, {}):
            continue
        parameters = [{"name": name, "in": "path", "required": True,
                       "schema": {"type": "string", "minLength": 1, "maxLength": 200}}
                      for name in re.findall(r"\{(\w+)\}", operation.path)]
        if operation.idempotent:
            parameters.append({"name": "Idempotency-Key", "in": "header", "required": True,
                               "schema": {"type": "string", "minLength": 1, "maxLength": 200},
                               "description": "Identity-scoped atomic admission; same key/body replays, different body conflicts (409)."})
        if operation.operation_id == "getHistory":
            parameters.extend([
                {"name": "cursor", "in": "query", "schema": {"type": "string", "minLength": 1, "maxLength": 2000}},
                {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}},
                {"name": "verdict", "in": "query", "schema": {"type": "string", "enum": ["GO", "NO_GO"]}},
                {"name": "applicationStatus", "in": "query", "schema": {"type": "string", "enum": ["not_applied", "applied", "replied", "interview", "rejected", "hired"]}},
            ])
        responses = {str(status): {"description": code, "content": {"application/json": {"schema": ref(ErrorEnvelope)}}} for status, code in ERRORS.items()}
        responses[str(operation.status)] = {"description": "Planned success response; route is not implemented"}
        if operation.response:
            responses[str(operation.status)]["content"] = {"application/json": {"schema": ref(operation.response)}}
        entry = {"operationId": operation.operation_id, "x-fitcheck-implementation": "planned",
                 "x-fitcheck-owner-task": operation.owner, "parameters": parameters,
                 "security": SECURITY[operation.access], "responses": responses}
        if operation.request:
            entry["requestBody"] = {"required": True, "content": {"application/json": {"schema": ref(operation.request)}}}
        if operation.method != "get" and operation.access != "public":
            entry["x-fitcheck-cookie-mutation"] = {"originRequired": True, "csrfHeader": "X-CSRF-Token"}
        if operation.access == "public" and operation.method != "get":
            entry["x-fitcheck-origin-policy"] = "Verify trusted Origin for browser mutations; use anti-CSRF bootstrap for cookie-producing flows"
        document["paths"].setdefault(operation.path, {})[operation.method] = entry
    return document
