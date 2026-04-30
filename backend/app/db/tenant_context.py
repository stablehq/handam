"""
Tenant context management for multi-tenant isolation (옵션 C 완성판).

옵션 C 핵심:
- tenant 컨텍스트는 `session.info['tenant_id']` 와 `session.info['bypass_tenant']` 에 저장
- session 이 곧 tenant 컨텍스트 자체 — ContextVar sibling-task 누수 영향 없음
- tenant 격리가 필요한 모든 진입점은 `session_for_tenant(tid)` / `session_bypass()` 사용
  (db/database.py 참고)

before_flush / before_compile 이벤트가 session.info 를 읽어 자동 격리:
- INSERT 시 `tenant_id` 자동 주입 (session.info 의 tenant_id)
- SELECT 시 `WHERE tenant_id = X` 자동 추가
- bypass=True 면 자동 필터 우회 (cross-tenant 운영 작업)
- 컨텍스트 없이 tenant 모델 query 시 RuntimeError (fail-closed)
"""
from typing import Optional, Tuple
from sqlalchemy.orm import Session, Query
from sqlalchemy import event
from app.diag_logger import diag


def _resolve_tenant_context(session) -> Tuple[Optional[int], bool]:
    """현재 세션의 tenant 컨텍스트 결정.

    옵션 C: session.info 만 사용. ContextVar fallback 없음.

    Returns:
        (tenant_id, bypass_flag) 튜플.
    """
    return (
        session.info.get('tenant_id'),
        session.info.get('bypass_tenant', False),
    )


def get_session_tenant_id(session) -> Optional[int]:
    """주어진 session 의 현재 tenant_id 반환 (옵션 C 외부 helper).

    Use cases:
        service / API endpoint 에서 session 인자로 받은 tenant 추출.
    """
    return session.info.get('tenant_id')


def is_session_bypass(session) -> bool:
    """주어진 session 이 bypass 모드인지 반환 (옵션 C 외부 helper)."""
    return session.info.get('bypass_tenant', False)


# Auto-inject tenant_id on INSERT
@event.listens_for(Session, "before_flush")
def _set_tenant_on_new_objects(session, flush_context, instances):
    """Automatically set tenant_id on new objects if not already set."""
    tid, _ = _resolve_tenant_context(session)
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
    # Prevent infinite recursion: .filter() creates a new query that triggers before_compile again
    if query._execution_options.get("_tenant_filtered", False):
        return query

    session = query.session
    tid, bypass = _resolve_tenant_context(session)

    if bypass:
        return query

    if tid is None:
        # Fail-closed: block queries on tenant models without context
        for desc in query.column_descriptions:
            entity = desc.get("entity")
            if entity is not None and entity in TENANT_MODELS:
                raise RuntimeError(
                    f"SECURITY: Query on tenant model {entity.__name__} "
                    "without tenant context. Use session_for_tenant(tid) "
                    "or session_bypass() for cross-tenant queries."
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
