"""One-shot: reconcile chips for all reservations migrated by the extend-stay refactor.

Run once after the data migration to ensure chips for the extended days are present.

Usage:
    cd backend && python -m scripts.reconcile_post_migration
"""
from app.db.database import session_bypass, session_for_tenant
from app.db.models import Reservation
from app.services.reconcile import reconcile_all_chips


def main():
    # Phase 1: fetch all affected reservations via bypass session (cross-tenant)
    with session_bypass() as db_bypass:
        targets = (
            db_bypass.query(Reservation)
            .filter(Reservation.manually_extended_until.isnot(None))
            .all()
        )
        # Snapshot the data we need before the session closes
        target_info = [
            (r.id, r.tenant_id, r.customer_name, r.check_in_date, r.check_out_date)
            for r in targets
        ]

    print(f"Found {len(target_info)} reservations to reconcile")

    ok = 0
    errors = 0
    for res_id, tenant_id, customer_name, check_in, check_out in target_info:
        # Phase 2: per-tenant scoped session for reconcile
        with session_for_tenant(tenant_id) as db:
            try:
                reconcile_all_chips(db, res_id)
                db.commit()
                print(f"  OK  {res_id} {customer_name} {check_in}~{check_out}")
                ok += 1
            except Exception as e:
                db.rollback()
                print(f"  ERR {res_id} {customer_name} ERROR: {e}")
                errors += 1

    print(f"\nDone. {ok} succeeded, {errors} failed.")


if __name__ == "__main__":
    main()
