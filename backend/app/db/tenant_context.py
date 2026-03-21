"""
Tenant context management for multi-tenant isolation.
Uses ContextVar to store current tenant_id per-request.
"""
from contextvars import ContextVar
from typing import Optional
from sqlalchemy.orm import Session, Query
from sqlalchemy import event

# Current request's tenant_id — set by FastAPI dependency, read by query helpers
current_tenant_id: ContextVar[Optional[int]] = ContextVar("current_tenant_id", default=None)

# Explicit bypass flag for scheduler/migration contexts
bypass_tenant_filter: ContextVar[bool] = ContextVar("bypass_tenant_filter", default=False)


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
    import logging
    _logger = logging.getLogger(__name__)

    tid = current_tenant_id.get()
    if tid is None:
        # Warn if querying tenant models without context (fail-open but detectable)
        if not bypass_tenant_filter.get():
            for desc in query.column_descriptions:
                entity = desc.get("entity")
                if entity is not None and entity in TENANT_MODELS:
                    _logger.warning(
                        f"Query on tenant model {entity.__name__} without tenant context! "
                        "Set current_tenant_id or bypass_tenant_filter for intentional cross-tenant queries."
                    )
                    break
        return query

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
