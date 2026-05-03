"""
Diag #1 — reservations API 분리 회귀 가드.

api/reservations.py (1436줄) 를 4개 도메인 라우터 + shared 로 분리한 후
누군가 실수로 라우트를 추가/이동/삭제하면 즉시 잡기 위한 invariant 테스트.

분리 작업: refactor/split-reservations-api 브랜치.
검증 대상: 17개 엔드포인트가 정확한 파일에, 정확한 method+path 로 등록되어 있어야 함.
"""
from app.api import (
    reservations,
    reservations_room,
    reservations_sms,
    reservations_stay,
    reservations_shared,
)


# ---- 라우터별 expected 매핑 (path, method 정렬키) ----
EXPECTED_CRUD = {
    ("GET", "/api/reservations"),
    ("POST", "/api/reservations"),
    ("PUT", "/api/reservations/{reservation_id}"),
    ("DELETE", "/api/reservations/{reservation_id}"),
    ("POST", "/api/reservations/sync/naver"),
}

EXPECTED_ROOM = {
    ("PUT", "/api/reservations/{reservation_id}/room"),
    ("PUT", "/api/reservations/{reservation_id}/daily-info"),
}

EXPECTED_SMS = {
    ("POST", "/api/reservations/{reservation_id}/sms-assign"),
    ("DELETE", "/api/reservations/{reservation_id}/sms-assign/{template_key}"),
    ("PATCH", "/api/reservations/{reservation_id}/sms-toggle/{template_key}"),
    ("POST", "/api/reservations/sms-send-by-tag"),
}

EXPECTED_STAY = {
    ("POST", "/api/reservations/detect-consecutive"),
    ("POST", "/api/reservations/{reservation_id}/stay-group/link"),
    ("DELETE", "/api/reservations/{reservation_id}/stay-group/unlink"),
    ("POST", "/api/reservations/{reservation_id}/extend-stay"),
    ("POST", "/api/reservations/{reservation_id}/extend-stay/assign-room"),
    ("DELETE", "/api/reservations/{reservation_id}/extend-stay"),
}

TOTAL_EXPECTED = (
    len(EXPECTED_CRUD) + len(EXPECTED_ROOM) + len(EXPECTED_SMS) + len(EXPECTED_STAY)
)  # 5 + 2 + 4 + 6 = 17


def _routes_of(router):
    """APIRouter 의 (METHOD, path) 셋 반환."""
    out = set()
    for r in router.routes:
        if not hasattr(r, "path") or not hasattr(r, "methods"):
            continue
        for m in r.methods:
            if m == "HEAD":
                continue
            out.add((m, r.path))
    return out


def test_router_route_counts():
    """각 라우터에 정확히 expected 개수의 라우트만 등록되어 있어야 함."""
    assert len(_routes_of(reservations.router)) == len(EXPECTED_CRUD), \
        "CRUD 라우터 라우트 수 변경됨"
    assert len(_routes_of(reservations_room.router)) == len(EXPECTED_ROOM), \
        "Room 라우터 라우트 수 변경됨"
    assert len(_routes_of(reservations_sms.router)) == len(EXPECTED_SMS), \
        "SMS 라우터 라우트 수 변경됨"
    assert len(_routes_of(reservations_stay.router)) == len(EXPECTED_STAY), \
        "Stay 라우터 라우트 수 변경됨"


def test_router_route_paths_exact():
    """라우트의 method+path 셋이 정확히 일치해야 함 (오타/이동 잡기)."""
    assert _routes_of(reservations.router) == EXPECTED_CRUD
    assert _routes_of(reservations_room.router) == EXPECTED_ROOM
    assert _routes_of(reservations_sms.router) == EXPECTED_SMS
    assert _routes_of(reservations_stay.router) == EXPECTED_STAY


def test_no_cross_domain_leak():
    """한 라우터에 다른 도메인 라우트가 섞이면 안 됨 (분리 무결성)."""
    crud = _routes_of(reservations.router)
    # CRUD 에 sms-/stay-group/extend-stay/room/daily-info 가 있으면 안 됨
    for m, p in crud:
        assert "/sms-" not in p and "sms-send-by-tag" not in p, \
            f"CRUD 라우터에 SMS 라우트 누수: {m} {p}"
        assert "/stay-group" not in p and "/extend-stay" not in p, \
            f"CRUD 라우터에 Stay 라우트 누수: {m} {p}"
        assert "/room" not in p and "/daily-info" not in p, \
            f"CRUD 라우터에 Room 라우트 누수: {m} {p}"


def test_shared_helper_exposed():
    """_to_response 와 핵심 스키마가 reservations_shared 에서 정상 export 되어야 함.
    분리 후 헬퍼가 사라지면 4개 라우터 모두 import 실패 → 서버 기동 불가."""
    assert hasattr(reservations_shared, "_to_response")
    assert callable(reservations_shared._to_response)
    assert hasattr(reservations_shared, "ReservationResponse")
    assert hasattr(reservations_shared, "ReservationCreate")
    assert hasattr(reservations_shared, "ReservationUpdate")
    assert hasattr(reservations_shared, "SmsAssignmentResponse")


def test_total_endpoint_count_in_app():
    """FastAPI app 에 등록된 /api/reservations 경로 합이 17 개여야 함.
    main.py 에서 include_router 누락하면 여기서 잡힘."""
    from app.main import app
    paths = set()
    for r in app.routes:
        if not hasattr(r, "path") or not hasattr(r, "methods"):
            continue
        if not r.path.startswith("/api/reservations"):
            continue
        for m in r.methods:
            if m == "HEAD":
                continue
            paths.add((m, r.path))
    assert len(paths) == TOTAL_EXPECTED, (
        f"app.routes 의 /api/reservations 합계 불일치: "
        f"{len(paths)} != {TOTAL_EXPECTED}\n"
        f"실제: {sorted(paths)}"
    )
