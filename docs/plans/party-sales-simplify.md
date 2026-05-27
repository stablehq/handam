# 파티매출 탭 단순화 — 사전조사 / 설계 문서

## 1. 목표 (요구사항)

파티 입장 체크 페이지의 **파티매출 탭**을 단순화한다.

- 저장할 값: **진행자 / 경매액 / 리뷰수 / 언스매출 / 포차매출 / 여자초대수**
- 리뷰·경매·포차매출·언스매출 → **그날의 단일 진행자(DailyHost)에 귀속**되는 데이터
- 여자초대수 → 행마다 **선택하는 진행자**에게 귀속 (기존 그대로)
- 기존 **판매기록(OnsiteSale, 자유 품명 N건)** 카드를 제거하고, 그 자리를
  **언스매출 / 포차매출** 2개 고정 항목으로 나눠 **진행자 카드 안으로 이동**.

## 2. 결정 사항 (확정)

| 항목 | 결정 |
|------|------|
| 언스/포차 저장 위치 | **DailyHost 테이블에 컬럼 추가** |
| 결제방식(카드/이체/현금) | **유지** → 언스/포차 각각 `금액 + 결제방식` (경매액과 동일 형태) |
| 기존 OnsiteSale 기능/데이터 | **완전 제거** (마이그레이션 없음, 기존 테이블은 방치) |

> 경매(OnsiteAuction)·리뷰(DailyReviewCount)는 이미 날짜별 자체 테이블이 있고 정상 동작하므로
> 저장 위치를 옮기지 않는다. "진행자에 귀속"은 개념적 의미일 뿐, 저장 구조는 현행 유지.

## 3. 데이터 모델 변경

### `DailyHost` (backend/app/db/models.py)

**Before**
```python
class DailyHost(TenantMixin, Base):
    id, date, host_username, created_at
    UniqueConstraint(tenant_id, date)
```

**After** — 컬럼 4개 추가
```python
    uns_amount          = Column(Integer, nullable=True)   # 언스매출 금액
    uns_payment_method  = Column(String(20), nullable=True)  # 카드/이체/현금
    pocha_amount        = Column(Integer, nullable=True)   # 포차매출 금액
    pocha_payment_method= Column(String(20), nullable=True)
```

### Auto-migrate (backend/app/db/database.py)
`onsite_auctions.payment_method` 블록(454~459줄) 패턴 그대로 daily_hosts 4컬럼 추가:
```python
if "daily_hosts" in inspector.get_table_names():
    cols = [c["name"] for c in inspector.get_columns("daily_hosts")]
    for col, ddl in [
        ("uns_amount", "INTEGER"), ("uns_payment_method", "VARCHAR(20)"),
        ("pocha_amount", "INTEGER"), ("pocha_payment_method", "VARCHAR(20)"),
    ]:
        if col not in cols:
            conn.execute(text(f"ALTER TABLE daily_hosts ADD COLUMN {col} {ddl}"))
```
+ 기존 `onsite_sales.payment_method` 마이그 블록(447~452줄) 제거.

## 4. 백엔드 API 변경

### 4-1. `daily_host.py` — uns/pocha 입출력 추가
- `DailyHostUpsert`: `uns_amount, uns_payment_method, pocha_amount, pocha_payment_method` (모두 Optional) 추가
- `DailyHostResponse`: 동일 4필드 추가
- `upsert_daily_host`: existing/new 양쪽에서 4필드 대입
- `get_daily_host`: 응답 dict 에 4필드 포함

### 4-2. `sales_report.py` — OnsiteSale → DailyHost 소스 교체 (★ 응답 형태 불변)
- import 에서 `OnsiteSale` 제거
- `hosts` 쿼리 결과로 `host_obj_by_date: dict[date, DailyHost]` 구축 (host_username 외 uns/pocha 접근용)
- `sales = db.query(OnsiteSale)...` (82~87줄) **삭제**, `sales_by_date` 삭제
- `build_date_detail(d, ...)` 재작성:
  - `host = host_obj_by_date.get(d)`
  - 합성 items: `[("언스매출", uns_amount, uns_pm), ("포차매출", pocha_amount, pocha_pm)]` 중 금액>0 인 것만
  - `sales_total = (uns_amount or 0) + (pocha_amount or 0)`
  - `sales_by_payment`: 두 항목을 결제방식별 합산
  - `items`: 위 합성 항목 리스트
- `all_dates_with_data` (200줄): `sales_by_date.keys()` → 제거. 언스/포차는 DailyHost 안에 있어 "host 없는 매출"이 원천적으로 불가능. auction 단독 날짜만 unassigned 후보로 남김:
  `all_dates_with_data = set(auction_map.keys())`

> **동작 동등성**: `SalesItemDetail / DateDetail / HostSummary` 스키마와 필드명 전부 불변 →
> 프론트 `SalesReport.tsx` 변경 **0건**. 진행자별 total_sales/total_revenue 계산 로직도 그대로.

### 4-3. `onsite_sales.py` 제거
- 파일 삭제
- `main.py` 17줄 import + 216줄 `include_router(onsite_sales_router)` 삭제
- `models.py` `OnsiteSale` 클래스 삭제 (참조처: main/onsite_sales/sales_report/database 만 — 모두 본 변경에서 정리됨)
- 기존 prod `onsite_sales` 테이블은 방치 (무해)

## 5. 프론트엔드 변경

### 5-1. `api.ts`
- `onsiteSalesAPI` 전체 삭제 (408~413줄)
- `dailyHostAPI.upsert` payload + `.get` 응답 타입에 uns/pocha 4필드 추가

### 5-2. `queryKeys.ts`
- `partyCheckin.sales` 키(87줄) 삭제 (사용처 사라짐)

### 5-3. `PartyCheckin.tsx`
**삭제**
- `salesQuery` / `sales` / `salesLoading` (246~253줄)
- 판매기록 상태: `newItemName/newAmount/newPaymentMethod` (189~191줄)
- `handleAddSale` (424줄), `confirmDeleteSale` (443줄), `salesTotalAmount` (448줄)
- `deleteModal` 상태 + 판매 삭제 확인 모달 (1044~1062줄)
- 판매 기록 카드 전체 (973~1039줄)

**추가**
- 상태: `unsAmount, unsPaymentMethod, pochaAmount, pochaPaymentMethod`
- 진행자 카드(경매액 아래)에 **언스매출 / 포차매출** 행 2개 — 경매액과 동일한 `결제방식 Select + 금액 TextInput` 패턴, `cardEditing` 토글 공유
- 동기화 useEffect(296~317줄 구간)에 `host?.uns_amount` 등으로 4필드 set 추가
- `cardSaveMutation`(451줄)의 `dailyHostAPI.upsert` 호출에 uns/pocha 4필드 포함

### 5-4. 권한/탭 노출 (열린 결정 — §7)
판매기록 제거 후 파티매출 탭의 모든 콘텐츠가 `canManageHost`(admin/superadmin) 전용이 됨.
STAFF 는 빈 탭만 보게 되므로 **`!canManageHost` 시 파티매출 탭 자체를 숨김** 권장.

## 6. 영향 범위 요약

| 파일 | 변경 |
|------|------|
| backend/app/db/models.py | DailyHost +4컬럼, OnsiteSale 삭제 |
| backend/app/db/database.py | daily_hosts 마이그 추가, onsite_sales 마이그 제거 |
| backend/app/api/daily_host.py | uns/pocha 입출력 |
| backend/app/api/sales_report.py | 소스 OnsiteSale→DailyHost (응답 불변) |
| backend/app/api/onsite_sales.py | **파일 삭제** |
| backend/app/main.py | onsite_sales 라우터 등록 제거 |
| frontend/src/services/api.ts | onsiteSalesAPI 삭제, dailyHostAPI 확장 |
| frontend/src/lib/queryKeys.ts | partyCheckin.sales 삭제 |
| frontend/src/pages/PartyCheckin.tsx | 판매기록 카드 제거 + 언스/포차 진행자 카드 편입 |
| frontend/src/pages/SalesReport.tsx | **변경 없음** (응답 스키마 불변) |

## 7. 열린 결정 (사용자 확인 필요)
1. STAFF 에게 파티매출 탭을 숨길지 (권장: 숨김)
2. SalesReport 의 "판매" 컬럼 라벨을 그대로 둘지 ("판매" = 언스+포차 합) — 라벨 변경 불요 시 백엔드/프론트 추가 작업 0.

## 8. 시나리오 검증
- **신규 저장**: 진행자 카드에서 진행자+경매+리뷰+언스+포차 입력 → 저장 → daily_hosts 1행(uns/pocha 포함) + onsite_auctions + daily_review_counts upsert. ✔
- **리포트 집계**: sales_report 가 daily_hosts.uns/pocha 를 items 2건으로 합성 → SalesReport 가 기존과 동일하게 "판매=언스+포차", 결제방식별 분해 표시. ✔
- **경매만 있고 진행자 미지정 날짜**: auction_map 기반 unassigned 그룹 유지 → 기존 동작 보존. ✔
- **기존 OnsiteSale 데이터**: 리포트에서 더 이상 집계 안 됨 (의도된 제거). 과거 수치 보존 불필요 확인됨. ✔
