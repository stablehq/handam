"""
일회성 백필: onsite_sales / onsite_auctions (레거시) → daily_hosts 의
경매/포차/언스 × 현금/이체/카드 9컬럼.

규칙 (2026-05 결정):
- 분류: item_name == '경매' → 경매 / {'언스매출','3차 언스테이블'} → 언스 / 그 외 전부 → 포차
- 경매 합산 = onsite_auctions + onsite_sales 중 '경매' 분류
- 결제버킷: 현금→cash, 이체→transfer, 카드→card, None→transfer
- 진행자 행 없는 날짜 → host_username='(미지정)' 으로 생성
- 안전장치: 이미 9컬럼 중 하나라도 값이 있는 daily_hosts 행은 건드리지 않음 (--force 로 해제)
- 멱등: 레거시 테이블에서 매번 전체 재계산해 SET (증분 아님)
- 레거시 테이블(onsite_sales/onsite_auctions)은 삭제하지 않음

사용:
  python -m scripts.migrate_sales_to_daily_hosts            # dry-run (기록 안 함)
  python -m scripts.migrate_sales_to_daily_hosts --commit   # 실제 기록
  python -m scripts.migrate_sales_to_daily_hosts --commit --force  # 기존 값 덮어쓰기
"""
import argparse
from collections import defaultdict

from sqlalchemy import create_engine, text

from app.config import settings

UNS_NAMES = {"언스매출", "3차 언스테이블"}
SALES_COLS = [
    "auction_cash", "auction_transfer", "auction_card",
    "pocha_cash", "pocha_transfer", "pocha_card",
    "uns_cash", "uns_transfer", "uns_card",
]


def classify(item_name: str) -> str:
    if item_name == "경매":
        return "auction"
    if item_name in UNS_NAMES:
        return "uns"
    return "pocha"


def bucket(payment_method) -> str:
    return {"현금": "cash", "이체": "transfer", "카드": "card"}.get(payment_method, "transfer")


def compute_targets(conn):
    """returns: {(tenant_id, date): {col: amount}}"""
    targets: dict[tuple[int, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))

    # 경매 테이블
    for tid, date, final_amount, pm in conn.execute(text(
        "SELECT tenant_id, date, final_amount, payment_method FROM onsite_auctions"
    )):
        if final_amount and final_amount > 0:
            targets[(tid, date)][f"auction_{bucket(pm)}"] += final_amount

    # 판매 테이블 (분류 적용)
    for tid, date, item_name, amount, pm in conn.execute(text(
        "SELECT tenant_id, date, item_name, amount, payment_method FROM onsite_sales"
    )):
        if not amount or amount <= 0:
            continue
        cat = classify(item_name)
        targets[(tid, date)][f"{cat}_{bucket(pm)}"] += amount

    return targets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="실제 DB 기록 (기본: dry-run)")
    ap.add_argument("--force", action="store_true", help="기존 값이 있어도 덮어쓰기")
    args = ap.parse_args()

    engine = create_engine(settings.DATABASE_URL)
    created = updated = skipped = 0
    grand = defaultdict(int)

    with engine.begin() as conn:
        targets = compute_targets(conn)

        for (tid, date) in sorted(targets):
            sums = targets[(tid, date)]
            vals = {col: sums.get(col, 0) for col in SALES_COLS}
            for col, v in vals.items():
                grand[col] += v

            row = conn.execute(text(
                "SELECT id, " + ", ".join(SALES_COLS) +
                " FROM daily_hosts WHERE tenant_id=:t AND date=:d"
            ), {"t": tid, "d": date}).fetchone()

            # NULL 컬럼은 0 으로, 양수만 저장 (0 버킷은 NULL 유지)
            set_vals = {col: (vals[col] if vals[col] > 0 else None) for col in SALES_COLS}
            summary = ", ".join(f"{c}={vals[c]}" for c in SALES_COLS if vals[c] > 0) or "(전부 0)"

            if row is None:
                action = "CREATE '(미지정)'"
                created += 1
                if args.commit:
                    cols = ["tenant_id", "date", "host_username"] + SALES_COLS
                    conn.execute(text(
                        "INSERT INTO daily_hosts (" + ", ".join(cols) + ") VALUES (" +
                        ":tenant_id, :date, :host, " + ", ".join(f":{c}" for c in SALES_COLS) + ")"
                    ), {"tenant_id": tid, "date": date, "host": "(미지정)", **set_vals})
            else:
                existing_nonnull = any(row[i + 1] is not None for i in range(len(SALES_COLS)))
                if existing_nonnull and not args.force:
                    action = "SKIP (이미 값 있음)"
                    skipped += 1
                    print(f"  t{tid} {date} | {action}")
                    continue
                action = "UPDATE"
                updated += 1
                if args.commit:
                    conn.execute(text(
                        "UPDATE daily_hosts SET " + ", ".join(f"{c}=:{c}" for c in SALES_COLS) +
                        " WHERE tenant_id=:t AND date=:d"
                    ), {"t": tid, "d": date, **set_vals})

            print(f"  t{tid} {date} | {action} | {summary}")

        if not args.commit:
            conn.rollback()

    print()
    print(f"{'[COMMIT]' if args.commit else '[DRY-RUN]'} created={created} updated={updated} skipped={skipped}")
    print("합계(버킷별):", {c: grand[c] for c in SALES_COLS if grand[c]})
    print("경매 총:", grand["auction_cash"] + grand["auction_transfer"] + grand["auction_card"])
    print("포차 총:", grand["pocha_cash"] + grand["pocha_transfer"] + grand["pocha_card"])
    print("언스 총:", grand["uns_cash"] + grand["uns_transfer"] + grand["uns_card"])


if __name__ == "__main__":
    main()
