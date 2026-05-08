import type { HoverZoneState } from './useHoverZone';

/**
 * zoneId 문자열에서 HoverZoneState 로 변환.
 * 'room-5' → { type: 'room', roomId: 5 }
 * 'next-room-3' → { type: 'next-room', roomId: 3 }
 * 'pool' / 'party' / 'next-pool' / 'next-party' → { type: '...' }
 */
function zoneIdToHoverState(zoneId: string): HoverZoneState {
  if (zoneId.startsWith('room-')) {
    return { type: 'room', roomId: Number(zoneId.replace('room-', '')) };
  }
  if (zoneId.startsWith('next-room-')) {
    return { type: 'next-room', roomId: Number(zoneId.replace('next-room-', '')) };
  }
  return { type: zoneId as Exclude<HoverZoneState['type'], 'room' | 'next-room' | 'none'> };
}

function isHoverMatch(hover: HoverZoneState, zoneId: string): boolean {
  if (zoneId.startsWith('room-')) {
    const id = Number(zoneId.replace('room-', ''));
    return hover.type === 'room' && hover.roomId === id;
  }
  if (zoneId.startsWith('next-room-')) {
    const id = Number(zoneId.replace('next-room-', ''));
    return hover.type === 'next-room' && hover.roomId === id;
  }
  return hover.type === zoneId;
}

interface UseGuestDropTargetProps {
  zoneId: string;
  hover: HoverZoneState;
  setHover: (state: HoverZoneState) => void;
  clearHover: () => void;
  /** false 면 드롭존 비활성화 — data-drop-zone / 핸들러 모두 비어있는 props 반환. */
  enabled?: boolean;
}

/**
 * 드롭 영역 한 곳을 등록하는 훅.
 *
 * Phase F-1: zoneId 만 알려주면 data-drop-zone + 호버 핸들러 + isDragOver 자동 처리.
 * dnd-kit / react-dnd 와 같은 표준 훅 인터페이스 패턴.
 *
 * 사용 예:
 * ```tsx
 * const { isDragOver, dropZoneProps } = useGuestDropTarget({
 *   zoneId: 'pool', hover, setHover, clearHover,
 * });
 * <div {...dropZoneProps} className={isDragOver ? 'bg-blue' : ''}>...</div>
 * ```
 */
export function useGuestDropTarget({
  zoneId,
  hover,
  setHover,
  clearHover,
  enabled = true,
}: UseGuestDropTargetProps) {
  const isDragOver = enabled && isHoverMatch(hover, zoneId);

  const dropZoneProps = enabled
    ? {
        'data-drop-zone': zoneId,
        onMouseEnter: () => setHover(zoneIdToHoverState(zoneId)),
        onMouseLeave: clearHover,
      }
    : ({} as { 'data-drop-zone'?: string; onMouseEnter?: () => void; onMouseLeave?: () => void });

  return { isDragOver, dropZoneProps };
}
