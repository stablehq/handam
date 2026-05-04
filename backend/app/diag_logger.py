"""
Refactor-2026-04 진단 로그 인프라 v2.

## 목적
시스템 수정 후 3-5일 집중 감시 기간에 모든 사이드이펙트를 추적.
평상시 off, 감시 기간만 환경변수로 on.

## 사용법
평상시: DIAG_LEVEL=off (기본값)
수정 직후: DIAG_LEVEL=verbose (모든 이벤트)
안정화: DIAG_LEVEL=critical (이례적 이벤트만)

## 제거 마킹 (언젠가 이 인프라를 완전히 제거할 때)
grep -rn "from app.diag_logger" backend/
grep -rn "diag(" backend/app/ | grep -v "def diag"
grep -rn "DIAG_BLOCK_START\\|DIAG_BLOCK_END" backend/ frontend/
grep -rn "X-Diag-\\|__diagAction\\|X-Request-ID" frontend/src/
grep -rn "DIAG_LEVEL\\|DIAG_LOG_DIR" .env* docker-compose*
위 5개 grep 결과 0건 + diag_logger.py 삭제 = 완전 제거
"""
import gzip
import logging
import os
import shutil
from contextvars import ContextVar
from logging.handlers import TimedRotatingFileHandler
from typing import Optional

# ── 레벨 정의 ──────────────────────────────────────────────────────────
_LEVELS = {"off": 0, "critical": 1, "verbose": 2}
_LEVEL_NAME = os.environ.get("DIAG_LEVEL", "off").lower()
_LEVEL = _LEVELS.get(_LEVEL_NAME, 0)  # 알 수 없는 값은 off

# ── Request correlation context ──────────────────────────────────────
_request_id_ctx: ContextVar[str] = ContextVar("diag_request_id", default="-")
_action_ctx: ContextVar[str] = ContextVar("diag_user_action", default="-")

# ── Logger 싱글톤 ────────────────────────────────────────────────────
_logger: Optional[logging.Logger] = None


def _gzip_namer(default_name: str) -> str:
    # default_name = ".../refactor-diag.log.YYYY-MM-DD"
    # backupCount cleanup 이 .gz 까지 식별하도록 namer 와 rotator 모두 .gz suffix 사용.
    return default_name + ".gz"


def _gzip_rotator(source: str, dest: str) -> None:
    # dest 는 _gzip_namer 가 이미 .gz 로 끝낸 경로.
    try:
        with open(source, "rb") as f_in, gzip.open(dest, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        os.remove(source)
    except Exception:
        # gzip 실패해도 rotation 자체는 성공해야 하므로 원본 이름(.gz 제거) 유지
        fallback = dest[:-3] if dest.endswith(".gz") else dest
        try:
            os.rename(source, fallback)
        except Exception:
            pass


def get_diag_logger() -> logging.Logger:
    global _logger, _LEVEL
    if _logger is not None:
        return _logger

    _logger = logging.getLogger("refactor_diag")

    # off 모드: NullHandler 붙여 완전 무음
    if _LEVEL == 0:
        _logger.addHandler(logging.NullHandler())
        _logger.setLevel(logging.CRITICAL + 1)
        _logger.propagate = False
        return _logger

    # ★ 파일 핸들러 설치 실패 시 stderr fallback (로그는 docker logs 에서 계속 볼 수 있음)
    log_dir = os.environ.get("DIAG_LOG_DIR", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        # 쓰기 가능 여부 실제 확인
        _probe = os.path.join(log_dir, ".diag_probe")
        with open(_probe, "a", encoding="utf-8") as _:
            pass
        os.remove(_probe)

        handler = TimedRotatingFileHandler(
            os.path.join(log_dir, "refactor-diag.log"),
            when="midnight",
            backupCount=7,
            encoding="utf-8",
        )
        handler.rotator = _gzip_rotator
        handler.namer = _gzip_namer
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        _logger.addHandler(handler)
        _logger.setLevel(logging.INFO)
        _logger.propagate = False
        return _logger
    except (PermissionError, OSError) as e:
        # 파일 핸들러 설치 실패 → stderr StreamHandler로 fallback
        # (레벨은 그대로 유지, 로그는 `docker logs <container>` 에 [DIAG] 태그로 나옴)
        import sys
        print(
            f"[diag_logger] WARNING: cannot open {log_dir}/refactor-diag.log ({e}) "
            f"— falling back to stderr. Logs will appear in `docker logs` with [DIAG] tag. "
            f"For file output, fix dir permission: mkdir -p {log_dir} && chmod 777 {log_dir}",
            file=sys.stderr,
        )
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(
            logging.Formatter("[DIAG] %(asctime)s | %(levelname)s | %(message)s")
        )
        _logger.addHandler(stream_handler)
        _logger.setLevel(logging.INFO)
        _logger.propagate = False
        return _logger


# ── 민감정보 마스킹 ────────────────────────────────────────────────
def mask_phone(phone: Optional[str]) -> str:
    if not phone:
        return "-"
    if len(phone) < 8:
        return "***"
    return f"{phone[:3]}****{phone[-4:]}"


def mask_name(name: Optional[str]) -> str:
    if not name:
        return "-"
    if len(name) == 1:
        return "*"
    return name[0] + "*" * (len(name) - 1)


# ── 핵심 diag 함수 ──────────────────────────────────────────────────
def diag(event: str, level: str = "critical", **kwargs) -> None:
    """이벤트 로그 기록.

    level: 'critical' (이례적 이벤트) | 'verbose' (상세 트레이스)

    DIAG_LEVEL=off       → 아무것도 기록 안 함 (early exit, zero cost)
    DIAG_LEVEL=critical  → level='critical'만 기록
    DIAG_LEVEL=verbose   → 모두 기록
    """
    required_level = _LEVELS.get(level, 1)
    if required_level > _LEVEL:
        return  # early exit — format string 비용도 없음

    # 자동 주입: request_id, user_action
    # 옵션 C (Phase 6): tenant_id 자동 주입 제거. 호출자가 명시 인자로 'tid' 전달.
    kwargs.setdefault("req", _request_id_ctx.get())
    action = _action_ctx.get()
    if action and action != "-":
        kwargs.setdefault("action", action)

    logger = get_diag_logger()
    kv = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
    logger.info(f"[{event}] {kv}")


# ── Context 관리자 (middleware 등에서 사용) ─────────────────────────
def set_request_context(request_id: str, user_action: str = "-"):
    """Returns tokens for context reset."""
    t1 = _request_id_ctx.set(request_id)
    t2 = _action_ctx.set(user_action)
    return t1, t2


def reset_request_context(tokens) -> None:
    _request_id_ctx.reset(tokens[0])
    _action_ctx.reset(tokens[1])


# ── 현재 레벨 노출 (테스트/디버깅용) ─────────────────────────────────
def is_enabled(level: str = "critical") -> bool:
    """Check if a given level would produce output."""
    return _LEVELS.get(level, 1) <= _LEVEL


def current_level_name() -> str:
    return _LEVEL_NAME
