import { useState } from 'react';

/**
 * 선택 모드에서 마우스가 어느 영역 위에 있는지 추적하는 호버 상태.
 *
 * Phase A-3: RoomAssignment.tsx 의 dragOverRoom/dragOverPool 등 6개 useState 통합.
 * - "drag" 라는 옛 명칭의 잔재를 "hover" 로 정정 (HTML5 drag&drop 미사용).
 * - Discriminated union 으로 6개 케이스 중 하나만 가능함을 타입으로 보장.
 */
export type HoverZoneState =
  | { type: 'none' }
  | { type: 'room'; roomId: number }
  | { type: 'next-room'; roomId: number }
  | { type: 'pool' }
  | { type: 'next-pool' }
  | { type: 'party' }
  | { type: 'next-party' };

export function useHoverZone() {
  const [hover, setHover] = useState<HoverZoneState>({ type: 'none' });

  const clearHover = () => setHover({ type: 'none' });

  return { hover, setHover, clearHover };
}
