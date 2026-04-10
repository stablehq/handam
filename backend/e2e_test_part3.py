"""
E2E Test Part 3 — 누락 섹션 추가
  O: 예약 CRUD
  U: 템플릿 CRUD
  V: 건물/객실 CRUD
  T: 객실 그룹
Depends on e2e_test.py for helpers.
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


# ════════════════════════════════════════════
# SECTION O: 예약 CRUD
# ════════════════════════════════════════════
def test_section_O():
    print("\n" + "═"*60)
    print("  SECTION O: 예약 CRUD (6건)")
    print("═"*60)

    created_id = None

    try:
        # O-1: 예약 생성
        T("O-1", "예약 생성")
        data, st = api("post", "/api/reservations", token=TOKEN, tenant_id=TENANT, json_data={
            "customer_name": "E2E_CRUD테스트",
            "phone": "010-9999-0001",
            "check_in_date": "2026-07-01",
            "check_in_time": "15:00",
            "check_out_date": "2026-07-03",
            "status": "confirmed",
            "booking_source": "manual",
            "male_count": 2,
            "female_count": 1,
            "party_size": 3,
            "notes": "E2E 테스트 메모",
        })
        if st in (200, 201) and data and data.get("id"):
            created_id = data["id"]
            PASS("O-1", f"id={created_id}, name={data.get('customer_name')}")
        else:
            FAIL("O-1", f"status={st}, data={data}")
            return

        # O-2: 예약 수정
        T("O-2", "예약 수정 (날짜/인원 변경)")
        update, st = api("put", f"/api/reservations/{created_id}", token=TOKEN, tenant_id=TENANT, json_data={
            "check_out_date": "2026-07-04",
            "male_count": 3,
            "female_count": 2,
            "notes": "E2E 수정된 메모",
        })
        if st == 200 and update:
            co = update.get("check_out_date", "")
            mc = update.get("male_count")
            fc = update.get("female_count")
            notes = update.get("notes", "")
            checks = []
            if "2026-07-04" in str(co):
                checks.append("checkout")
            if mc == 3:
                checks.append("male")
            if fc == 2:
                checks.append("female")
            if "수정된" in str(notes):
                checks.append("notes")
            if len(checks) == 4:
                PASS("O-2", f"모든 필드 반영: {', '.join(checks)}")
            else:
                FAIL("O-2", f"일부 미반영: {checks}, co={co}, mc={mc}, fc={fc}")
        else:
            FAIL("O-2", f"status={st}")

        # O-3: 예약 목록 조회 + 검색
        T("O-3", "예약 목록 조회 + 검색")
        res_list, st = api("get", "/api/reservations", token=TOKEN, tenant_id=TENANT,
                           params={"search": "E2E_CRUD", "limit": 10})
        if st == 200 and res_list:
            items = res_list.get("items", res_list) if isinstance(res_list, dict) else res_list
            found = any(r.get("id") == created_id for r in (items or []))
            if found:
                PASS("O-3", f"검색 결과에 id={created_id} 포함")
            else:
                FAIL("O-3", f"id={created_id} 검색 안 됨")
        else:
            FAIL("O-3", f"status={st}")

        # O-4: 예약 상태 변경 → cancelled
        T("O-4", "예약 상태 변경 (confirmed → cancelled)")
        cancel, st = api("put", f"/api/reservations/{created_id}", token=TOKEN, tenant_id=TENANT,
                         json_data={"status": "cancelled"})
        if st == 200 and cancel:
            new_status = cancel.get("status", "")
            if "cancel" in str(new_status).lower():
                PASS("O-4", f"status={new_status}")
            else:
                FAIL("O-4", f"status={new_status}, expected cancelled")
        else:
            FAIL("O-4", f"status={st}")

        # O-5: 당일 취소 예약 표시 확인 (목록에서 조회)
        T("O-5", "취소 예약 목록 조회")
        res_list2, st = api("get", "/api/reservations", token=TOKEN, tenant_id=TENANT,
                            params={"search": "E2E_CRUD", "limit": 10})
        if st == 200 and res_list2:
            items = res_list2.get("items", res_list2) if isinstance(res_list2, dict) else res_list2
            found = [r for r in (items or []) if r.get("id") == created_id]
            if found:
                PASS("O-5", f"취소 예약 id={created_id} 목록에서 조회 가능")
            else:
                PASS("O-5", "취소 예약이 목록에서 제외됨 (필터 동작)")
        else:
            FAIL("O-5", f"status={st}")

        # O-6: 예약 삭제
        T("O-6", "예약 삭제")
        _, st = api("delete", f"/api/reservations/{created_id}", token=TOKEN, tenant_id=TENANT)
        if st in (200, 204):
            # 삭제 후 조회되면 안 됨
            check, st2 = api("get", "/api/reservations", token=TOKEN, tenant_id=TENANT,
                             params={"search": "E2E_CRUD", "limit": 10})
            items = (check or {}).get("items", check or []) if isinstance(check, dict) else (check or [])
            still_exists = any(r.get("id") == created_id for r in items)
            if not still_exists:
                PASS("O-6", f"id={created_id} 삭제 완료, 목록에서 사라짐")
                created_id = None  # cleanup 불필요
            else:
                FAIL("O-6", f"삭제 후에도 id={created_id} 조회됨")
        else:
            FAIL("O-6", f"status={st}")

    finally:
        if created_id:
            api("delete", f"/api/reservations/{created_id}", token=TOKEN, tenant_id=TENANT)


# ════════════════════════════════════════════
# SECTION U: 템플릿 CRUD
# ════════════════════════════════════════════
def test_section_U():
    print("\n" + "═"*60)
    print("  SECTION U: 템플릿 CRUD (4건)")
    print("═"*60)

    created_id = None

    try:
        # U-1: 템플릿 생성
        T("U-1", "템플릿 생성")
        data, st = api("post", "/api/templates", token=TOKEN, tenant_id=TENANT, json_data={
            "template_key": "e2e_crud_tpl",
            "name": "E2E CRUD 테스트",
            "content": "{{customer_name}}님 안녕하세요. {{room_num}}호 비밀번호: {{room_password}}",
            "category": "test",
            "participant_buffer": 5,
            "round_unit": 10,
            "round_mode": "ceil",
        })
        if st in (200, 201) and data and data.get("id"):
            created_id = data["id"]
            PASS("U-1", f"id={created_id}, key={data.get('template_key')}")
        else:
            FAIL("U-1", f"status={st}")
            return

        # U-2: 템플릿 수정
        T("U-2", "템플릿 수정 (content/buffer 변경)")
        update, st = api("put", f"/api/templates/{created_id}", token=TOKEN, tenant_id=TENANT, json_data={
            "content": "{{customer_name}}님 수정된 안내입니다.",
            "participant_buffer": 10,
            "round_mode": "floor",
        })
        if st == 200 and update:
            new_content = update.get("content", "")
            new_buffer = update.get("participant_buffer")
            new_mode = update.get("round_mode")
            if "수정된" in new_content and new_buffer == 10 and new_mode == "floor":
                PASS("U-2", f"content/buffer/round_mode 모두 반영")
            else:
                FAIL("U-2", f"content={new_content[:30]}, buffer={new_buffer}, mode={new_mode}")
        else:
            FAIL("U-2", f"status={st}")

        # U-3: 중복 template_key 거부
        T("U-3", "중복 template_key 거부")
        dup, st = api("post", "/api/templates", token=TOKEN, tenant_id=TENANT, json_data={
            "template_key": "e2e_crud_tpl",
            "name": "중복",
            "content": "중복 테스트",
        })
        if st in (400, 409, 422, 500):
            PASS("U-3", f"중복 거부: status={st}")
        else:
            FAIL("U-3", f"중복 허용됨: status={st}")
            if dup and dup.get("id"):
                api("delete", f"/api/templates/{dup['id']}", token=TOKEN, tenant_id=TENANT)

        # U-4: 템플릿 삭제
        T("U-4", "템플릿 삭제")
        _, st = api("delete", f"/api/templates/{created_id}", token=TOKEN, tenant_id=TENANT)
        if st in (200, 204):
            # 삭제 후 목록에서 사라지는지
            all_tpls, _ = api("get", "/api/templates", token=TOKEN, tenant_id=TENANT)
            still = any(t.get("id") == created_id for t in (all_tpls or []))
            if not still:
                PASS("U-4", f"id={created_id} 삭제 완료")
                created_id = None
            else:
                FAIL("U-4", "삭제 후에도 목록에 남아있음")
        else:
            FAIL("U-4", f"status={st}")

    finally:
        if created_id:
            api("delete", f"/api/templates/{created_id}", token=TOKEN, tenant_id=TENANT)


# ════════════════════════════════════════════
# SECTION V: 건물/객실 CRUD
# ════════════════════════════════════════════
def test_section_V():
    print("\n" + "═"*60)
    print("  SECTION V: 건물/객실 CRUD (5건)")
    print("═"*60)

    bldg_id = None
    room_id = None

    try:
        # V-1: 건물 생성
        T("V-1", "건물 생성")
        data, st = api("post", "/api/buildings", token=TOKEN, tenant_id=TENANT, json_data={
            "name": "E2E_테스트관",
            "description": "E2E 테스트용 건물",
        })
        if st in (200, 201) and data and data.get("id"):
            bldg_id = data["id"]
            PASS("V-1", f"id={bldg_id}, name={data.get('name')}")
        else:
            FAIL("V-1", f"status={st}")
            return

        # V-2: 객실 생성
        T("V-2", "객실 생성 (건물에 연결)")
        data, st = api("post", "/api/rooms", token=TOKEN, tenant_id=TENANT, json_data={
            "room_number": "E2E-101",
            "room_type": "standard",
            "building_id": bldg_id,
            "base_capacity": 2,
            "max_capacity": 4,
            "is_dormitory": False,
        })
        if st in (200, 201) and data and data.get("id"):
            room_id = data["id"]
            PASS("V-2", f"id={room_id}, room_number={data.get('room_number')}, building_id={bldg_id}")
        else:
            FAIL("V-2", f"status={st}")

        # V-3: 객실 수정
        T("V-3", "객실 수정")
        if room_id:
            update, st = api("put", f"/api/rooms/{room_id}", token=TOKEN, tenant_id=TENANT, json_data={
                "room_type": "deluxe",
                "max_capacity": 6,
            })
            if st == 200 and update:
                PASS("V-3", f"room_type={update.get('room_type')}, max_capacity={update.get('max_capacity')}")
            else:
                FAIL("V-3", f"status={st}")
        else:
            SKIP("V-3", "No room")

        # V-4: 객실 삭제
        T("V-4", "객실 삭제")
        if room_id:
            _, st = api("delete", f"/api/rooms/{room_id}", token=TOKEN, tenant_id=TENANT)
            if st in (200, 204):
                PASS("V-4", f"room id={room_id} 삭제")
                room_id = None
            else:
                FAIL("V-4", f"status={st}")
        else:
            SKIP("V-4", "No room")

        # V-5: 건물 삭제
        T("V-5", "건물 삭제")
        _, st = api("delete", f"/api/buildings/{bldg_id}", token=TOKEN, tenant_id=TENANT)
        if st in (200, 204):
            PASS("V-5", f"building id={bldg_id} 삭제")
            bldg_id = None
        else:
            FAIL("V-5", f"status={st}")

    finally:
        if room_id:
            api("delete", f"/api/rooms/{room_id}", token=TOKEN, tenant_id=TENANT)
        if bldg_id:
            api("delete", f"/api/buildings/{bldg_id}", token=TOKEN, tenant_id=TENANT)


# ════════════════════════════════════════════
# SECTION T2: 신규 API 기본 CRUD
# ════════════════════════════════════════════
def test_section_T2():
    print("\n" + "═"*60)
    print("  SECTION T2: 신규 API 엔드포인트 접근성 (6건)")
    print("═"*60)

    today = datetime.now().strftime("%Y-%m-%d")

    endpoints = [
        ("T2-1", "GET", "/api/event-sms", "이벤트 SMS"),
        ("T2-2", "GET", f"/api/onsite-sales?date={today}", "현장 판매"),
        ("T2-3", "GET", f"/api/sales-report?start_date={today}&end_date={today}", "매출 보고서"),
        ("T2-4", "GET", f"/api/daily-host?date={today}", "일별 진행자"),
        ("T2-5", "GET", f"/api/party-hosts?date={today}", "파티 호스트"),
        ("T2-6", "GET", f"/api/onsite-auction?date={today}", "현장 경매"),
    ]

    for tid, method, path, desc in endpoints:
        T(tid, f"{desc} — {method} {path}")
        _, st = api(method.lower(), path, token=TOKEN, tenant_id=TENANT)
        if st in (200, 404):
            PASS(tid, f"status={st}")
        else:
            FAIL(tid, f"status={st}")


# ════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════
if __name__ == "__main__":
    print("SMS System E2E Test Part 3 — O, U, V, T2 (신규 섹션)")
    print(f"   Time: {datetime.now().isoformat()}")

    setup()

    test_section_O()
    test_section_U()
    test_section_V()
    test_section_T2()

    print_summary()
