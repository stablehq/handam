# P4 사전조사 — is_split_managed OR-강화 (freeze 구멍 봉인, 1줄)

> 부모 계획: naver_split 근본 해결 (수정판 안 A). 선행: P1~P3 ✅
> 분류: 🟢 보호 추가만 — unfreeze 0건 (red-team critical: 전면 교체 시 on_constraints_changed
> 연쇄로 배정 대량 해제 + 칩 반전 폭발 → 의도적으로 "OR 추가"로 축소된 안)
> 변경 규모: naver_sync 1지점 + rescue diag 1개 + 회귀 테스트 (8cc7423 시나리오 — 현재 0건)

## 1. 목적

8cc7423 사고(재동기화가 split primary 의 분할값을 네이버 원본으로 토글 → 합계 1.5배)를 막는
`is_split_managed` freeze 의 마지막 구멍 봉인: **운영자가 RoomBizItemLink 매핑을 해제하면
휘발 조건이 False 로 뒤집혀 다음 sync 가 분할값을 덮어씀** (sibling 잔존 → 이중계상).

## 2. 변경 (라인 단위)

`naver_sync.py` `_update_reservation` 의 freeze 판정:

**Before**:
```python
    is_split_managed = (not res_data.get("_is_dormitory")) and res_data.get("_has_room_link")
```
**After**:
```python
    _legacy_split_managed = (not res_data.get("_is_dormitory")) and res_data.get("_has_room_link")
    # P4(split-group): OR 강화 — split_group_id 보유 row 는 매핑 해제돼도 freeze 유지
    # (8cc7423 토글 사고의 마지막 구멍 봉인). 추가만, unfreeze 0건.
    is_split_managed = _legacy_split_managed or (existing.split_group_id is not None)
    if is_split_managed and not _legacy_split_managed:
        # 구조가 실제로 사고를 막은 순간 — 매핑 해제 상태로 sync 가 도는 동안 발화
        diag("naver_sync.split_freeze_rescue", level="info",
             reservation_id=existing.id, split_group_id=existing.split_group_id)
```

## 3. 동작 동등성

| 케이스 | Before | After |
|---|---|---|
| 매핑된 일반실 (대다수) | freeze | freeze (동일) |
| 도미토리 / 미매핑 / 무키 | 갱신 | 갱신 (동일 — **기존 동작 보존**) |
| **split 그룹 + 매핑 해제** | ⚠️ 갱신 → 이중계상 | **freeze 유지 + rescue diag** |

비분할 일반실의 과잉 동결(전면 unfreeze)은 **계속 명시 보류** — red-team critical 사유로
선행조건(3필드 Mutator 경유 + 사전 diff + cascade 분석) 충족 전 금지.

## 4. 검증

- 신규 회귀 테스트 (8cc7423 — 현재 freeze 테스트 0건이던 갭 해소):
  ① split primary 정상 케이스: bc/총액/인원 freeze 유지
  ② **매핑 해제 + 그룹 키**: freeze 유지 (P4 핵심) + rescue 동작
  ③ 매핑 해제 + 무키: 갱신됨 (기존 동작 보존 증명)
- 기존 split 테스트 전체 무수정 통과
- 롤백: 한 줄 revert
