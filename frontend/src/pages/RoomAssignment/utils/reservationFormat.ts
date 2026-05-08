/**
 * 게스트 정보를 화면에 표시할 문자열로 가공하는 순수 헬퍼.
 *
 * Phase A-1: RoomAssignment.tsx 71~107 에서 분리 (동작 변경 없음).
 */

import type { Reservation } from '../types';

export function formatGenderPeople(res: Reservation): string {
  const m = res.male_count || 0;
  const f = res.female_count || 0;
  if (m > 0 && f > 0) return `남${m}여${f}`;
  if (m > 0) return `남${m}`;
  if (f > 0) return `여${f}`;
  // Fallback: gender 문자열에서 숫자 파싱
  if (res.gender) {
    const maleMatch = res.gender.match(/남(\d+)/);
    const femaleMatch = res.gender.match(/여(\d+)/);
    if (maleMatch || femaleMatch) {
      const parts: string[] = [];
      if (maleMatch) parts.push(`남${maleMatch[1]}`);
      if (femaleMatch) parts.push(`여${femaleMatch[1]}`);
      return parts.join('');
    }
    // 단순 "남" or "여"
    if (res.gender === '남' || res.gender === '여') {
      return `${res.gender}${res.party_size || 1}`;
    }
  }
  return '';
}

export function formatGuestSuffix(res: Reservation): string {
  // 외부에서 들어온 신뢰 가능한 메타데이터만 노출 (네이버/연박추가/멀티룸 분할).
  // 수동 입력 경로(manual)는 직원이 임시로 채운 값일 수 있어 표시하지 않는다.
  const src = res.booking_source;
  if (src !== 'naver' && src !== 'naver_split' && src !== 'extend') return '';
  const parts: string[] = [];
  if (res.visit_count && res.visit_count > 0) parts.push(`${res.visit_count}회`);
  const age = res.age_group ? String(res.age_group).trim() : '';
  const g = res.gender === '남' || res.gender === '여' ? res.gender : '';
  const ageGender = `${age}${g}`;
  if (ageGender) parts.push(ageGender);
  return parts.length ? `(${parts.join('/')})` : '';
}
