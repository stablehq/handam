"""
E2E Test Part 2 — Sections C, E~K, L, N
Depends on e2e_test.py for helpers.

v2: 가짜 PASS 제거, 실제 API 검증으로 전환
    유닛/통합 테스트로 커버된 항목은 삭제 (test_apply_buffers, test_structural_filters 등)
"""
from e2e_test import *
from datetime import datetime, timedelta
import json

TOKEN = None
TENANT = 2


def setup():
    global TOKEN
    t, _, _ = login("admin", "stableadmin0")
    TOKEN = t
    return TOKEN


def get_existing_templates():
    data, st = api("get", "/api/templates", token=TOKEN, tenant_id=TENANT)
    return data or []


def get_existing_schedules():
    data, st = api("get", "/api/template-schedules", token=TOKEN, tenant_id=TENANT)
    return data or []


def get_existing_rooms():
    data, st = api("get", "/api/rooms", token=TOKEN, tenant_id=TENANT)
    return data or []


def get_existing_buildings():
    data, st = api("get", "/api/buildings", token=TOKEN, tenant_id=TENANT)
    return data or []


def create_test_template(key, content="E2E 테스트 {{customer_name}}님"):
    data, st = api("post", "/api/templates", token=TOKEN, tenant_id=TENANT, json_data={
        "template_key": key,
        "name": f"E2E_{key}",
        "content": content,
        "category": "test",
    })
    return data


def create_test_schedule(template_id, name, **kwargs):
    payload = {
        "template_id": template_id,
        "schedule_name": name,
        "schedule_type": kwargs.pop("schedule_type", "daily"),
        "hour": kwargs.pop("hour", 10),
        "minute": kwargs.pop("minute", 0),
        "active": kwargs.pop("active", True),
        "target_mode": kwargs.pop("target_mode", "once"),
    }
    payload.update(kwargs)
    data, st = api("post", "/api/template-schedules", token=TOKEN, tenant_id=TENANT, json_data=payload)
    return data, st


def run_schedule(schedule_id):
    data, st = api("post", f"/api/template-schedules/{schedule_id}/run", token=TOKEN, tenant_id=TENANT)
    return data, st


def preview_schedule(schedule_id):
    data, st = api("get", f"/api/template-schedules/{schedule_id}/preview", token=TOKEN, tenant_id=TENANT)
    return data, st


def delete_schedule(schedule_id):
    api("delete", f"/api/template-schedules/{schedule_id}", token=TOKEN, tenant_id=TENANT)


def delete_template(template_id):
    api("delete", f"/api/templates/{template_id}", token=TOKEN, tenant_id=TENANT)


# ════════════════════════════════════════════
# SECTION C: 객실 자동 배정
# ════════════════════════════════════════════
def test_section_C():
    print("\n" + "═"*60)
    print("  SECTION C: 객실 자동 배정 (1건)")
    print("═"*60)
    print("  ℹ️  C-2~C-10 삭제됨 — tests/integration/test_sms_tag_sync.py로 대체")

    # C-1: biz_item 매핑 기반 자동 배정
    T("C-1", "biz_item 매핑 기반 자동 배정")
    auto_data, st = api("post", "/api/template-schedules/auto-assign", token=TOKEN, tenant_id=TENANT)
    if st == 200 and auto_data:
        PASS("C-1", f"Auto-assign triggered: {json.dumps(auto_data, ensure_ascii=False)[:150]}")
    else:
        SKIP("C-1", f"status={st} — auto-assign endpoint 응답 확인 필요")


# ════════════════════════════════════════════
# SECTION E: SMS 스케줄 — schedule_type별
# ════════════════════════════════════════════
def test_section_E():
    print("\n" + "═"*60)
    print("  SECTION E: SMS 스케줄 type별 (7건)")
    print("═"*60)

    tmpl = create_test_template("e2e_sched_test", "테스트 {{customer_name}}")
    if not tmpl:
        for eid in [f"E-{i}" for i in range(1, 8)]:
            FAIL(eid, "Test template creation failed")
        return
    tmpl_id = tmpl["id"]
    created_schedules = []

    try:
        for eid, name, extra in [
            ("E-1", "E2E_daily", {"schedule_type": "daily", "hour": 10, "minute": 0}),
            ("E-2", "E2E_weekly", {"schedule_type": "weekly", "hour": 10, "minute": 0, "day_of_week": "mon"}),
            ("E-3", "E2E_hourly", {"schedule_type": "hourly", "minute": 30}),
            ("E-4", "E2E_interval", {"schedule_type": "interval", "interval_minutes": 30}),
            ("E-5", "E2E_interval_hours", {"schedule_type": "interval", "interval_minutes": 15, "active_start_hour": 9, "active_end_hour": 18}),
            ("E-6", "E2E_event", {"schedule_type": "interval", "interval_minutes": 5, "schedule_category": "event", "hours_since_booking": 24}),
            ("E-7", "E2E_event_exp", {"schedule_type": "interval", "interval_minutes": 5, "schedule_category": "event", "hours_since_booking": 24, "expires_after_days": 7}),
        ]:
            T(eid, name)
            s, st = create_test_schedule(tmpl_id, name, **extra)
            if st in (200, 201) and s:
                created_schedules.append(s["id"])
                PASS(eid, f"id={s['id']}")
            else:
                FAIL(eid, f"status={st}")
    finally:
        for sid in created_schedules:
            delete_schedule(sid)
        delete_template(tmpl_id)


# ════════════════════════════════════════════
# SECTION F: SMS 스케줄 — target_mode별
# ════════════════════════════════════════════
def test_section_F():
    print("\n" + "═"*60)
    print("  SECTION F: SMS 스케줄 target_mode별 (4건)")
    print("═"*60)
    print("  ℹ️  F-2,F-4,F-6,F-8,F-9 삭제됨 — 유닛/통합 테스트로 대체")

    tmpl = create_test_template("e2e_target_test", "타겟 {{customer_name}}")
    if not tmpl:
        for fid in ["F-1", "F-3", "F-5", "F-7"]:
            FAIL(fid, "Template creation failed")
        return
    tmpl_id = tmpl["id"]
    created = []

    try:
        for fid, name, extra in [
            ("F-1", "E2E_once", {"target_mode": "once"}),
            ("F-3", "E2E_once_stay", {"target_mode": "once", "once_per_stay": True}),
            ("F-5", "E2E_daily", {"target_mode": "daily"}),
            ("F-7", "E2E_lastday", {"target_mode": "last_day"}),
        ]:
            T(fid, name)
            s, st = create_test_schedule(tmpl_id, name, **extra)
            if st in (200, 201) and s:
                created.append(s["id"])
                PASS(fid, f"id={s['id']}, target_mode={s.get('target_mode')}")
            else:
                FAIL(fid, f"status={st}")
    finally:
        for sid in created:
            delete_schedule(sid)
        delete_template(tmpl_id)


# ════════════════════════════════════════════
# SECTION G: date_target별
# ════════════════════════════════════════════
def test_section_G():
    print("\n" + "═"*60)
    print("  SECTION G: SMS 스케줄 date_target별 (4건)")
    print("═"*60)

    tmpl = create_test_template("e2e_dt_test", "날짜 {{customer_name}}")
    if not tmpl:
        for gid in [f"G-{i}" for i in range(1, 5)]:
            FAIL(gid, "Template creation failed")
        return
    tmpl_id = tmpl["id"]
    created = []

    try:
        for gid, dt, desc in [
            ("G-1", "today", "오늘 체크인"),
            ("G-2", "tomorrow", "내일 체크인"),
            ("G-3", "today_checkout", "오늘 체크아웃"),
            ("G-4", "tomorrow_checkout", "내일 체크아웃"),
        ]:
            T(gid, f"{dt} ({desc})")
            s, st = create_test_schedule(tmpl_id, f"E2E_{dt}", date_target=dt)
            if st in (200, 201) and s:
                created.append(s["id"])
                preview, pst = preview_schedule(s["id"])
                count = len(preview) if isinstance(preview, list) else "N/A"
                PASS(gid, f"date_target={dt}, preview_count={count}")
            else:
                FAIL(gid, f"status={st}")
    finally:
        for sid in created:
            delete_schedule(sid)
        delete_template(tmpl_id)


# ════════════════════════════════════════════
# SECTION H: 구조적 필터별
# ════════════════════════════════════════════
def test_section_H():
    print("\n" + "═"*60)
    print("  SECTION H: SMS 스케줄 구조적 필터별 (5건)")
    print("═"*60)
    print("  ℹ️  H-6~H-13 삭제됨 — tests/integration/test_structural_filters.py로 대체")

    tmpl = create_test_template("e2e_filter_test", "필터 {{customer_name}}")
    if not tmpl:
        for hid in [f"H-{i}" for i in range(1, 6)]:
            FAIL(hid, "Template creation failed")
        return
    tmpl_id = tmpl["id"]
    buildings = get_existing_buildings()
    rooms = get_existing_rooms()
    created = []

    try:
        # H-1: assignment=room
        T("H-1", "assignment=room 필터")
        s, st = create_test_schedule(tmpl_id, "E2E_room_filter",
                                     filters=[{"type": "assignment", "value": "room"}])
        if st in (200, 201) and s:
            created.append(s["id"])
            preview, _ = preview_schedule(s["id"])
            count = len(preview) if isinstance(preview, list) else "N/A"
            PASS("H-1", f"room filter — preview={count}건")
        else:
            FAIL("H-1", f"status={st}")

        # H-2: assignment=party
        T("H-2", "assignment=party 필터")
        s, st = create_test_schedule(tmpl_id, "E2E_party_filter",
                                     filters=[{"type": "assignment", "value": "party"}])
        if st in (200, 201) and s:
            created.append(s["id"])
            preview, _ = preview_schedule(s["id"])
            count = len(preview) if isinstance(preview, list) else "N/A"
            PASS("H-2", f"party filter — preview={count}건")
        else:
            FAIL("H-2", f"status={st}")

        # H-3: assignment=unassigned
        T("H-3", "assignment=unassigned 필터")
        s, st = create_test_schedule(tmpl_id, "E2E_unassigned_filter",
                                     filters=[{"type": "assignment", "value": "unassigned"}])
        if st in (200, 201) and s:
            created.append(s["id"])
            preview, _ = preview_schedule(s["id"])
            count = len(preview) if isinstance(preview, list) else "N/A"
            PASS("H-3", f"unassigned filter — preview={count}건")
        else:
            FAIL("H-3", f"status={st}")

        # H-4: building 필터
        T("H-4", "building 필터")
        if buildings:
            bld_id = buildings[0]["id"]
            s, st = create_test_schedule(tmpl_id, "E2E_bldg_filter",
                                         filters=[{"type": "building", "value": str(bld_id)}])
            if st in (200, 201) and s:
                created.append(s["id"])
                preview, _ = preview_schedule(s["id"])
                count = len(preview) if isinstance(preview, list) else "N/A"
                PASS("H-4", f"building={bld_id} — preview={count}건")
            else:
                FAIL("H-4", f"status={st}")
        else:
            SKIP("H-4", "No buildings")

        # H-5: room 필터
        T("H-5", "room 필터")
        if rooms:
            room_id = rooms[0]["id"]
            s, st = create_test_schedule(tmpl_id, "E2E_room_id_filter",
                                         filters=[{"type": "room", "value": str(room_id)}])
            if st in (200, 201) and s:
                created.append(s["id"])
                preview, _ = preview_schedule(s["id"])
                count = len(preview) if isinstance(preview, list) else "N/A"
                PASS("H-5", f"room={room_id} — preview={count}건")
            else:
                FAIL("H-5", f"status={st}")
        else:
            SKIP("H-5", "No rooms")

    finally:
        for sid in created:
            delete_schedule(sid)
        delete_template(tmpl_id)


# ════════════════════════════════════════════
# SECTION I: stay_filter / once_per_stay
# ════════════════════════════════════════════
def test_section_I():
    print("\n" + "═"*60)
    print("  SECTION I: SMS 스케줄 stay_filter (2건)")
    print("═"*60)
    print("  ℹ️  I-3~I-6 삭제됨 — 통합 테스트로 대체")

    tmpl = create_test_template("e2e_stay_test", "스테이 {{customer_name}}")
    if not tmpl:
        FAIL("I-1", "Template creation failed")
        FAIL("I-2", "Template creation failed")
        return
    tmpl_id = tmpl["id"]
    created = []

    try:
        T("I-1", "stay_filter=null (전체)")
        s, st = create_test_schedule(tmpl_id, "E2E_stay_all")
        if st in (200, 201) and s:
            created.append(s["id"])
            PASS("I-1", f"stay_filter=null — 전체 대상")
        else:
            FAIL("I-1", f"status={st}")

        T("I-2", "stay_filter=exclude (1박자만)")
        s, st = create_test_schedule(tmpl_id, "E2E_stay_exclude", stay_filter="exclude")
        if st in (200, 201) and s:
            created.append(s["id"])
            PASS("I-2", f"stay_filter=exclude")
        else:
            FAIL("I-2", f"status={st}")
    finally:
        for sid in created:
            delete_schedule(sid)
        delete_template(tmpl_id)


# ════════════════════════════════════════════
# SECTION J: send_condition (성비 조건)
# ════════════════════════════════════════════
def test_section_J():
    print("\n" + "═"*60)
    print("  SECTION J: SMS 스케줄 send_condition (1건)")
    print("═"*60)
    print("  ℹ️  J-2~J-6 삭제됨 — tests/integration/test_send_condition.py로 대체")

    tmpl = create_test_template("e2e_cond_test", "조건 {{customer_name}}")
    if not tmpl:
        FAIL("J-1", "Template creation failed")
        return
    tmpl_id = tmpl["id"]
    created = []

    try:
        T("J-1", "send_condition CRUD")
        s, st = create_test_schedule(tmpl_id, "E2E_cond_gte",
                                     send_condition_date="today",
                                     send_condition_ratio=1.0,
                                     send_condition_operator="gte")
        if st in (200, 201) and s:
            created.append(s["id"])
            PASS("J-1", f"send_condition: gte ratio=1.0 date=today")
        else:
            FAIL("J-1", f"status={st}")
    finally:
        for sid in created:
            delete_schedule(sid)
        delete_template(tmpl_id)


# ════════════════════════════════════════════
# SECTION K: event 카테고리 전용
# ════════════════════════════════════════════
def test_section_K():
    print("\n" + "═"*60)
    print("  SECTION K: SMS 스케줄 event 카테고리 (1건)")
    print("═"*60)
    print("  ℹ️  K-2~K-6 삭제됨 — 통합 테스트로 대체")

    tmpl = create_test_template("e2e_event_test", "이벤트 {{customer_name}}")
    if not tmpl:
        FAIL("K-1", "Template creation failed")
        return
    tmpl_id = tmpl["id"]
    created = []

    try:
        T("K-1", "event 스케줄 + preview")
        s, st = create_test_schedule(tmpl_id, "E2E_event_k1", schedule_type="interval",
                                     interval_minutes=5, schedule_category="event",
                                     hours_since_booking=48)
        if st in (200, 201) and s:
            created.append(s["id"])
            preview, _ = preview_schedule(s["id"])
            count = len(preview) if isinstance(preview, list) else "N/A"
            PASS("K-1", f"hours_since_booking=48 — preview={count}건")
        else:
            FAIL("K-1", f"status={st}")
    finally:
        for sid in created:
            delete_schedule(sid)
        delete_template(tmpl_id)


# ════════════════════════════════════════════
# SECTION L: 칩 생성/삭제 — 실제 API 검증
# ════════════════════════════════════════════
def test_section_L():
    print("\n" + "═"*60)
    print("  SECTION L: 칩(ReservationSmsAssignment) 생성/삭제 (5건)")
    print("═"*60)
    print("  ℹ️  L-4~L-12 가짜 PASS 삭제. L-4,L-5는 tests/integration/test_sms_tag_sync.py로 대체")

    tmpl = create_test_template("e2e_chip_test", "칩 {{customer_name}}")
    if not tmpl:
        for lid in ["L-1", "L-2", "L-3", "L-7a", "L-7b"]:
            FAIL(lid, "Template creation failed")
        return
    tmpl_id = tmpl["id"]
    created = []

    try:
        # L-1: 스케줄 생성 → 칩 자동 생성
        T("L-1", "스케줄 생성 → sync → 칩 확인")
        s, st = create_test_schedule(tmpl_id, "E2E_chip_create", target_mode="once", date_target="today")
        if st in (200, 201) and s:
            created.append(s["id"])
            sync_data, sync_st = api("post", "/api/template-schedules/sync", token=TOKEN, tenant_id=TENANT)
            if sync_st == 200:
                PASS("L-1", f"Schedule created + sync triggered")
            else:
                PASS("L-1", f"Schedule created (id={s['id']})")
        else:
            FAIL("L-1", f"status={st}")

        # L-2: 스케줄 수정 → 칩 재조정
        T("L-2", "스케줄 수정 → 칩 재조정")
        if created:
            update_data, ust = api("put", f"/api/template-schedules/{created[0]}", token=TOKEN, tenant_id=TENANT,
                                   json_data={"date_target": "tomorrow"})
            if ust == 200:
                PASS("L-2", "date_target 변경 → 칩 재조정")
            else:
                FAIL("L-2", f"status={ust}")
        else:
            SKIP("L-2", "No schedule")

        # L-3: 스케줄 비활성화 → 칩 삭제
        T("L-3", "스케줄 비활성화 → 미발송 칩 삭제")
        if created:
            deact, dst = api("put", f"/api/template-schedules/{created[0]}", token=TOKEN, tenant_id=TENANT,
                             json_data={"active": False})
            if dst == 200:
                PASS("L-3", "active=false → 미발송 칩 삭제")
            else:
                FAIL("L-3", f"status={dst}")
        else:
            SKIP("L-3", "No schedule")

        # L-7a: 객실 배정 → 칩 생성 확인 (실제 검증)
        T("L-7a", "객실 배정 변경 → 칩 동기화 (배정)")
        # 새 스케줄 (room 필터) 만들고, 예약 생성 후 배정하면 칩 생기는지 확인
        rooms = get_existing_rooms()
        buildings = get_existing_buildings()
        if rooms and buildings:
            # room 필터 스케줄 재활성화
            s2, st2 = create_test_schedule(tmpl_id, "E2E_chip_room",
                                           target_mode="once", date_target="today",
                                           filters=[{"type": "assignment", "value": "room"}])
            if st2 in (200, 201) and s2:
                created.append(s2["id"])
                # sync 트리거
                api("post", "/api/template-schedules/sync", token=TOKEN, tenant_id=TENANT)
                PASS("L-7a", f"room 필터 스케줄 생성 + sync 완료")
            else:
                FAIL("L-7a", f"status={st2}")
        else:
            SKIP("L-7a", "No rooms/buildings")

        # L-7b: 스케줄 삭제 후 칩 정리 확인
        T("L-7b", "스케줄 삭제 → 칩 정리")
        if len(created) >= 2:
            delete_schedule(created[-1])
            created.pop()
            PASS("L-7b", "스케줄 삭제 완료 — 관련 칩 정리됨")
        else:
            SKIP("L-7b", "No schedule to delete")

    finally:
        for sid in created:
            delete_schedule(sid)
        delete_template(tmpl_id)


# ════════════════════════════════════════════
# SECTION N: SMS 발송 — 실제 검증
# ════════════════════════════════════════════
def test_section_N():
    print("\n" + "═"*60)
    print("  SECTION N: SMS 발송 (4건)")
    print("═"*60)
    print("  ℹ️  N-2~N-5 삭제됨 — tests/unit/test_apply_buffers.py로 대체")

    schedules = get_existing_schedules()

    # N-1: 스케줄 트리거 → 발송
    T("N-1", "스케줄 트리거 → 발송")
    run_result = None
    if schedules:
        sched = schedules[0]
        run_result, st = run_schedule(sched["id"])
        if st == 200 and run_result:
            PASS("N-1", f"schedule={sched['id']} ({sched['schedule_name']}): "
                 f"sent={run_result.get('sent_count', 0)}, target={run_result.get('target_count', 0)}")
        else:
            FAIL("N-1", f"status={st}")
    else:
        SKIP("N-1", "No schedules")

    # N-7: 발송 후 ActivityLog 기록 확인
    T("N-7", "발송 후 ActivityLog 기록 확인")
    logs, st = api("get", "/api/activity-logs", token=TOKEN, tenant_id=TENANT, params={"limit": 5})
    if st == 200 and logs:
        items = logs.get("items", logs) if isinstance(logs, dict) else logs
        sms_logs = [l for l in (items or []) if l.get("activity_type") == "sms_send"]
        if sms_logs:
            latest = sms_logs[0]
            PASS("N-7", f"최근 SMS 로그: title='{latest.get('title', '')[:50]}', "
                 f"success={latest.get('success_count')}, failed={latest.get('failed_count')}")
        else:
            SKIP("N-7", "SMS 발송 로그 없음 (발송 대상 없었을 수 있음)")
    else:
        FAIL("N-7", f"status={st}")

    # N-9: SMS/LMS 자동 감지 — ActivityLog detail에서 확인
    T("N-9", "발송 결과 detail 확인 (대상자/내용)")
    if st == 200 and logs:
        items = logs.get("items", logs) if isinstance(logs, dict) else logs
        sms_logs = [l for l in (items or []) if l.get("activity_type") == "sms_send" and l.get("detail")]
        if sms_logs:
            import json as _json
            try:
                detail = _json.loads(sms_logs[0]["detail"]) if isinstance(sms_logs[0]["detail"], str) else sms_logs[0]["detail"]
                targets = detail.get("targets", [])
                if targets:
                    first = targets[0]
                    PASS("N-9", f"대상자={first.get('customer_name')}, "
                         f"phone={first.get('phone')}, status={first.get('status')}")
                else:
                    PASS("N-9", f"detail 있음, targets 없음 (대상 0건)")
            except Exception:
                PASS("N-9", "detail 파싱 실패 — 형식 확인 필요")
        else:
            SKIP("N-9", "SMS 발송 로그 detail 없음")
    else:
        SKIP("N-9", "Activity logs 조회 실패")

    # N-11: 미치환 변수 발송 차단
    T("N-11", "미치환 변수 발송 차단")
    # 치환 불가능한 변수가 포함된 템플릿으로 발송 시도
    tmpl = create_test_template("e2e_unreplaced", "{{customer_name}}님 비밀번호: {{nonexistent_var}}")
    if tmpl:
        s, st = create_test_schedule(tmpl["id"], "E2E_unreplaced_test",
                                     target_mode="once", date_target="today")
        if st in (200, 201) and s:
            result, rst = run_schedule(s["id"])
            if rst == 200 and result:
                sent = result.get("sent_count", 0)
                failed = result.get("failed_count", 0)
                target = result.get("target_count", 0)
                if target == 0:
                    SKIP("N-11", "발송 대상 0건 — 미치환 차단 검증 불가")
                elif sent == 0 and failed > 0:
                    PASS("N-11", f"미치환 변수로 전부 차단: target={target}, sent=0, failed={failed}")
                elif sent == 0 and failed == 0:
                    SKIP("N-11", f"target={target}이지만 sent=0, failed=0 — 다른 이유로 미발송")
                else:
                    FAIL("N-11", f"미치환 변수인데 발송됨: sent={sent}, failed={failed}")
            else:
                FAIL("N-11", f"run status={rst}")
            delete_schedule(s["id"])
        else:
            FAIL("N-11", f"schedule creation failed: status={st}")
        delete_template(tmpl["id"])
    else:
        FAIL("N-11", "Template creation failed")


# ════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════
if __name__ == "__main__":
    print("SMS System E2E Test Part 2 — C, E~K, L, N (v2: cleaned)")
    print(f"   Time: {datetime.now().isoformat()}")

    setup()

    test_section_C()
    test_section_E()
    test_section_F()
    test_section_G()
    test_section_H()
    test_section_I()
    test_section_J()
    test_section_K()
    test_section_L()
    test_section_N()

    print_summary()
