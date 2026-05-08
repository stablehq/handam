import type { Reservation } from '../types';

/**
 * 도미토리 게스트 배열을 침대 번호 기반 Map 으로 매핑.
 *
 * - bed_order >= 1 인 게스트 → 그 번호 슬롯에 배치 (중복은 leftover)
 * - bed_order = 0 (레거시) 또는 중복 → 빈 슬롯에 순서대로 fallback
 *
 * @example
 * // 김철수(bed_order=1), 이영희(bed_order=3), 박민수(bed_order=0)
 * mapBedSlots([김철수, 이영희, 박민수], 4)
 * // → Map { 1: 김철수, 3: 이영희, 2: 박민수 }
 *
 * 4번 슬롯은 비어 있어 Map 에 키 없음.
 */
export function mapBedSlots(
  guests: Reservation[],
  bedCapacity: number,
): Map<number, Reservation> {
  const byBed = new Map<number, Reservation>();
  const leftover: Reservation[] = [];

  for (const g of guests) {
    const bo = g.bed_order || 0;
    if (bo >= 1 && !byBed.has(bo)) {
      byBed.set(bo, g);
    } else {
      leftover.push(g);
    }
  }

  // bed_order=0 (레거시) 또는 중복 → 빈 슬롯에 순서대로
  let leftIdx = 0;
  for (let b = 1; b <= bedCapacity && leftIdx < leftover.length; b++) {
    if (!byBed.has(b)) {
      byBed.set(b, leftover[leftIdx++]);
    }
  }

  return byBed;
}
