import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_


DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


def current_tenant_id(current_user: Any | None = None):
    tenant_id = getattr(current_user, "tenant_id", None) if current_user is not None else None
    return tenant_id or DEFAULT_TENANT_ID


def tenant_id_from(*objects: Any, current_user: Any | None = None):
    for obj in objects:
        tenant_id = getattr(obj, "tenant_id", None)
        if tenant_id:
            return tenant_id
    return current_tenant_id(current_user)


def stamp_tenant(obj: Any, *sources: Any, current_user: Any | None = None) -> Any:
    if hasattr(obj, "tenant_id"):
        obj.tenant_id = tenant_id_from(*sources, current_user=current_user)
    return obj


def filter_by_tenant(query, model, current_user: Any | None = None, *, include_null: bool = False):
    if current_user is not None and getattr(current_user, "rol", None) == "admin":
        return query
    if not hasattr(model, "tenant_id"):
        return query

    tenant_id = current_tenant_id(current_user)
    if include_null:
        return query.filter(or_(model.tenant_id == tenant_id, model.tenant_id.is_(None)))
    return query.filter(model.tenant_id == tenant_id)


def assert_same_tenant(obj: Any, current_user: Any | None = None, *, detail: str = "No autorizado para este tenant") -> None:
    if current_user is not None and getattr(current_user, "rol", None) == "admin":
        return
    obj_tenant = getattr(obj, "tenant_id", None)
    if obj_tenant and str(obj_tenant) != str(current_tenant_id(current_user)):
        raise HTTPException(status_code=403, detail=detail)
