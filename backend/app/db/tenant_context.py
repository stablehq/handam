"""
Tenant context management for multi-tenant isolation.
Uses ContextVar to store current tenant_id per-request.
"""
from contextvars import ContextVar
from typing import Optional, Generator
from sqlalchemy.orm import Session, Query
from sqlalchemy import event

# Current request's tenant_id — set by FastAPI dependency, read by query helpers
current_tenant_id: ContextVar[Optional[int]] = ContextVar("current_tenant_id", default=None)

# Explicit bypass flag for scheduler/migration contexts
bypass_tenant_filter: ContextVar[bool] = ContextVar("bypass_tenant_filter", default=False)


def tenant_query(db: Session, model):
    """
    Create a tenant-scoped query. Use this instead of db.query(Model) for tenant models.

    Usage:
        # Before: db.query(Reservation).filter(...)
        # After:  tenant_query(db, Reservation).filter(...)
    """
    tid = current_tenant_id.get()
    if tid is None and not bypass_tenant_filter.get():
        raise RuntimeError(
            f"tenant_query({model.__name__}): tenant context not set. "
            "Use get_tenant_scoped_db() or set bypass_tenant_filter for scheduler."
        )
    query = db.query(model)
    if tid is not None:
        query = query.filter(model.tenant_id == tid)
    return query


def tenant_filter(db: Session, model, base_query=None):
    """
    Apply tenant filter to an existing query or create filtered query.
    For use with aggregate queries like db.query(func.count()).select_from(Model).

    Usage:
        # Aggregate:
        q = db.query(func.count()).select_from(Reservation)
        q = tenant_filter(db, Reservation, q)
    """
    tid = current_tenant_id.get()
    if tid is None:
        if bypass_tenant_filter.get():
            return base_query if base_query else db.query(model)
        raise RuntimeError(f"tenant_filter: tenant context not set")
    if base_query is not None:
        return base_query.filter(model.tenant_id == tid)
    return db.query(model).filter(model.tenant_id == tid)


# Auto-inject tenant_id on INSERT
@event.listens_for(Session, "before_flush")
def _set_tenant_on_new_objects(session, flush_context, instances):
    """Automatically set tenant_id on new objects if not already set."""
    tid = current_tenant_id.get()
    if tid is None:
        return
    for obj in session.new:
        if hasattr(obj, 'tenant_id') and obj.tenant_id is None:
            obj.tenant_id = tid


# ---------------------------------------------------------------------------
# Automatic SELECT filtering for tenant models
# ---------------------------------------------------------------------------

# Track which models use TenantMixin
TENANT_MODELS: set = set()


def register_tenant_model(cls):
    """Register a model class as tenant-scoped for auto-filtering."""
    TENANT_MODELS.add(cls)
    return cls


@event.listens_for(Query, "before_compile", retval=True)
def _apply_tenant_filter_on_select(query):
    """Auto-apply WHERE tenant_id = X on all SELECT queries for tenant models."""
    tid = current_tenant_id.get()
    if tid is None:
        return query  # No tenant context (scheduler bypass or non-tenant endpoint)

    # Check each entity in the query
    for desc in query.column_descriptions:
        entity = desc.get("entity")
        if entity is not None and entity in TENANT_MODELS:
            query = query.enable_assertions(False).filter(entity.tenant_id == tid)

    return query
