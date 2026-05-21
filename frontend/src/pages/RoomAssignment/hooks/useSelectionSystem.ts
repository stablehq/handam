import type { Dayjs } from 'dayjs';
import { useHoverZone, type HoverZoneState } from './useHoverZone';
import type { Reservation } from '../types';

interface UseSelectionSystemProps {
  selectedDate: Dayjs;
  reservations: Reservation[];
  nextDayReservations: Reservation[];
}

const EMPTY_SET = new Set<number>();
const NOOP_SET_STATE: React.Dispatch<React.SetStateAction<Set<number>>> = () => {};
const NOOP_GRIP: (e: React.MouseEvent | React.PointerEvent, resId: number) => void = () => {};
const NOOP_VOID: () => void = () => {};

/**
 * 호버 zone 상태 + selection fixture 반환.
 *
 * Step #06b (2026-05-20): 모바일 selection 시스템 제거. PC/모바일 모두 selection 은 noop fixture.
 * 이전엔 PC=fixture, 모바일=real selection 분기였지만, 이제 모바일도 drag/drop 이 주된 인터랙션.
 *
 * useHoverZone 만 실제 훅 결과 반환 (drop zone hover 시각 효과용).
 * selection 관련 필드들은 noop fixture 로 호환 유지 (호출처는 점진 정리).
 */
export function useSelectionSystem(_props: UseSelectionSystemProps) {
  const hover = useHoverZone();

  return {
    selectedGuestIds: EMPTY_SET,
    setSelectedGuestIds: NOOP_SET_STATE,
    selectionActive: false as const,
    cancelDeselect: NOOP_VOID,
    onGripClick: NOOP_GRIP,
    hover: hover.hover,
    setHover: hover.setHover,
    clearHover: hover.clearHover,
  };
}
