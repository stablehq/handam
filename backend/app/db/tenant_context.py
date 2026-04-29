"""
Tenant context management for multi-tenant isolation.
Uses ContextVar to store current tenant_id per-request.
"""
from contextvars import ContextVar
from typing import Optional
from sqlalchemy.orm import Session, Query
from sqlalchemy import event
from app.diag_logger import diag

# Current request's tenant_id — set by FastAPI dependency, read by query helpers
current_tenant_id: ContextVar[Optional[int]] = ContextVar("current_tenant_id", default=None)

# Explicit bypass flag for scheduler/migration contexts
bypass_tenant_filter: ContextVar[bool] = ContextVar("bypass_tenant_filter", default=False)



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
    diag("tenant_context.model_registered", level="verbose", model=cls.__name__)
    return cls


@event.listens_for(Query, "before_compile", retval=True)
def _apply_tenant_filter_on_select(query):
    """Auto-apply WHERE tenant_id = X on all SELECT queries for tenant models."""
    import logging
    _logger = logging.getLogger(__name__)

    # Prevent infinite recursion: .filter() creates a new query that triggers before_compile again
    if query._execution_options.get("_tenant_filtered", False):
        return query

    # Bypass must short-circuit before reading current_tenant_id — otherwise a stale
    # tid leaked from a sibling task (e.g. naver_sync looping tenants while a
    # schedule job triggers in the same coroutine context) silently re-applies
    # WHERE tenant_id=<stale>, masking bypass=True. See schedule.execute.fetch_miss.
    if bypass_tenant_filter.get():
        return query

    tid = current_tenant_id.get()
    if tid is None:
        # Fail-closed: block queries on tenant models without context
        for desc in query.column_descriptions:
            entity = desc.get("entity")
            if entity is not None and entity in TENANT_MODELS:
                raise RuntimeError(
                    f"SECURITY: Query on tenant model {entity.__name__} "
                    "without tenant context. Use get_tenant_scoped_db() "
                    "or set bypass_tenant_filter for cross-tenant queries."
                )
        return query

    # Mark query as processed to prevent re-entrance from .filter() calls
    query = query.execution_options(_tenant_filtered=True)

    # Track which models have already been filtered to avoid duplicates
    filtered_models = set()

    # Check each entity/column in the query
    for desc in query.column_descriptions:
        entity = desc.get("entity")
        if entity is not None and entity in TENANT_MODELS and entity not in filtered_models:
            # db.query(Model) pattern — entity is the model class
            query = query.enable_assertions(False).filter(entity.tenant_id == tid)
            filtered_models.add(entity)
        elif entity is None:
            # db.query(Model.column) or db.query(func.count()).select_from(Model) pattern
            # Try to resolve model from the expression
            expr = desc.get("expr")
            if expr is not None:
                model = _resolve_model_from_expr(expr)
                if model is not None and model in TENANT_MODELS and model not in filtered_models:
                    query = query.enable_assertions(False).filter(model.tenant_id == tid)
                    filtered_models.add(model)

    # Fallback: check select_from() tables for bare func expressions
    # e.g., db.query(func.count()).select_from(Reservation)
    # column_descriptions won't resolve the model, but froms will
    if hasattr(query, 'selectable') and hasattr(query.selectable, 'froms'):
        for from_clause in query.selectable.froms:
            for model in TENANT_MODELS:
                if hasattr(model, '__table__') and model.__table__ is from_clause and model not in filtered_models:
                    query = query.enable_assertions(False).filter(model.tenant_id == tid)
                    filtered_models.add(model)

    return query


def _resolve_model_from_expr(expr):
    """Resolve a SQLAlchemy mapped class from a column expression."""
    # InstrumentedAttribute (e.g., Model.column) has a 'class_' attribute
    if hasattr(expr, 'class_'):
        return expr.class_
    # For func expressions, try the underlying table via .table
    if hasattr(expr, 'table'):
        for model in TENANT_MODELS:
            if hasattr(model, '__table__') and model.__table__ is expr.table:
                return model
    return None
