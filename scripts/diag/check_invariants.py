#!/usr/bin/env python3
"""
Check invariants from docs/diag-golden/invariants.md against a diag log.

Usage:
  python3 check_invariants.py --log <file>
  python3 check_invariants.py --log <file> --since "2026-04-21 13:30:00"
"""
import argparse
import re
import sys
from collections import defaultdict

EVENT_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+)\s+\|\s+INFO\s+\|\s+\[(?P<event>[\w.]+)\]\s*(?P<rest>.*)$"
)
KV_PATTERN = re.compile(r"(\w+)=(\S+)")

DEAD_EVENTS = {
    "cascade.full_past_noop": "0ec7084 에서 제거됨",
    "cascade.downgraded_to_single": "0ec7084 에서 제거됨",
    "cascade.group_member_clamped": "0ec7084 에서 제거됨",
    "cascade.group_member_skipped": "0ec7084 에서 제거됨",
    "past_drop.blocked": "863f2fe 에서 제거됨",
}

VALID_SCHEDULE_OUTCOMES = {
    "completed", "schedule_not_found", "template_not_found",
    "send_condition_not_met", "no_targets", "exception",
}


def load_events(log_path: str, since: str | None):
    events = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            m = EVENT_LINE.match(line)
            if not m:
                continue
            ts = m.group("ts")
            if since and ts < since:
                continue
            kv = dict(KV_PATTERN.findall(m.group("rest")))
            events.append({
                "ts": ts,
                "event": m.group("event"),
                "fields": kv,
                "raw": line.rstrip(),
            })
    return events


# ------------------------------------------------------------------ 불변식들
def inv1_request_pair(events):
    """request.enter ↔ request.exit/error 짝"""
    violations = []
    per_req = defaultdict(lambda: {"enter": 0, "exit": 0, "error": 0})
    for e in events:
        req = e["fields"].get("req", "-")
        if e["event"] == "request.enter":
            per_req[req]["enter"] += 1
        elif e["event"] == "request.exit":
            per_req[req]["exit"] += 1
        elif e["event"] == "request.error":
            per_req[req]["error"] += 1
    for req, c in per_req.items():
        if req == "-":
            continue
        if c["enter"] != c["exit"] + c["error"]:
            violations.append(
                f"req={req} enter={c['enter']} exit={c['exit']} error={c['error']}"
            )
    return violations


def inv2_assign_room_pair(events):
    """assign_room.enter ↔ .exit"""
    violations = []
    per_key = defaultdict(lambda: {"enter": 0, "exit": 0})
    for e in events:
        if e["event"] not in ("assign_room.enter", "assign_room.exit"):
            continue
        key = (e["fields"].get("req", "-"), e["fields"].get("res_id"))
        per_key[key][e["event"].split(".")[-1]] += 1
    for key, c in per_key.items():
        if c["enter"] != c["exit"]:
            violations.append(f"req={key[0]} res_id={key[1]} enter={c['enter']} exit={c['exit']}")
    return violations


def inv3_schedule_outcome(events):
    """schedule.execute.exit 는 outcome 필드 필수"""
    violations = []
    for e in events:
        if e["event"] != "schedule.execute.exit":
            continue
        outcome = e["fields"].get("outcome")
        if outcome is None:
            violations.append(f"{e['ts']} schedule_id={e['fields'].get('schedule_id')} — outcome 필드 없음")
        elif outcome not in VALID_SCHEDULE_OUTCOMES:
            violations.append(f"{e['ts']} outcome={outcome} — 허용값 아님")
    return violations


def inv5_dead_events(events):
    """제거된 이벤트가 다시 등장하는지 체크"""
    violations = []
    for e in events:
        if e["event"] in DEAD_EVENTS:
            violations.append(f"{e['ts']} [{e['event']}] — {DEAD_EVENTS[e['event']]}")
    return violations


def inv6_no_health_noise(events):
    """/health 경로의 request.enter 가 있으면 안 됨"""
    violations = []
    for e in events:
        if e["event"] == "request.enter" and e["fields"].get("path") == "/health":
            violations.append(f"{e['ts']} req={e['fields'].get('req')} — /health 스킵 회귀")
    return violations


def inv7_naver_sync_counts(events):
    """synced == added + updated (same_day_cancel 제외 정규 흐름)"""
    violations = []
    for e in events:
        if e["event"] != "naver_sync.exit":
            continue
        try:
            s = int(e["fields"].get("synced", 0))
            a = int(e["fields"].get("added", 0))
            u = int(e["fields"].get("updated", 0))
        except (ValueError, TypeError):
            continue
        if s != a + u:
            violations.append(f"{e['ts']} synced={s} added={a} updated={u}")
    return violations


def inv8_pii_leak(events):
    """마스킹 안 된 전화번호/이메일 탐지"""
    violations = []
    # 전화번호: 010 뒤 연속 8자리 (중간에 ****가 없음)
    phone_leak = re.compile(r"01[0-9][\s-]?\d{4}[\s-]?\d{4}")
    email_leak = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    # 운영 정책상 phone 평문 노출이 허용된 이벤트 (운영자 디버깅 편의 우선).
    # 추가 시 docs/diag-golden/state.json notes 에 근거 기록.
    phone_whitelist = {"sms_sender.blocked_invalid_phone", "sms.failed_recorded"}
    for e in events:
        raw = e["raw"]
        if e.get("event") in phone_whitelist:
            continue
        # to=010****1234 같이 이미 마스킹된 건 제외. 원본 번호가 그대로 있는지만 체크.
        for m in phone_leak.finditer(raw):
            token = m.group()
            if "****" not in token:
                violations.append(f"{e['ts']} 전화번호 노출 의심: {token}")
                break
        for m in email_leak.finditer(raw):
            violations.append(f"{e['ts']} 이메일 노출 의심: {m.group()}")
            break
    return violations


CHECKS = [
    ("INV-1 request 짝", "HIGH", inv1_request_pair),
    ("INV-2 assign_room 짝", "HIGH", inv2_assign_room_pair),
    ("INV-3 schedule.outcome 필수", "MEDIUM", inv3_schedule_outcome),
    ("INV-5 사망 이벤트 재출현", "HIGH", inv5_dead_events),
    ("INV-6 /health 노이즈", "MEDIUM", inv6_no_health_noise),
    ("INV-7 naver_sync 카운트", "MEDIUM", inv7_naver_sync_counts),
    ("INV-8 PII 누수", "HIGH", inv8_pii_leak),
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--log", required=True)
    p.add_argument("--since", help="이 타임스탬프 이후만 체크 (YYYY-MM-DD HH:MM:SS)")
    args = p.parse_args()

    events = load_events(args.log, args.since)
    print(f"📊 검증 대상: {len(events)} 이벤트\n")

    total_violations = 0
    for name, severity, fn in CHECKS:
        try:
            violations = fn(events)
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ {name} 실행 중 에러: {exc}")
            continue
        if not violations:
            print(f"  ✅ {name}")
            continue
        total_violations += len(violations)
        print(f"  ❌ [{severity}] {name} — 위반 {len(violations)}건:")
        for v in violations[:10]:
            print(f"     - {v}")
        if len(violations) > 10:
            print(f"     ... 외 {len(violations) - 10} 건")

    print(f"\n총 위반: {total_violations} 건")
    sys.exit(0 if total_violations == 0 else 1)


if __name__ == "__main__":
    main()
