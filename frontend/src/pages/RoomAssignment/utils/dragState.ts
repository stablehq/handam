/**
 * dnd-kit drag 종료 직후 발생하는 native click 이벤트를 무시하기 위한 timestamp tracker.
 *
 * 드래그 끝 시점의 마우스 release 위치가 InlineInput display span 위면
 * native click → onClick → activate → 의도치 않은 편집 모드 진입. 이를 차단.
 */
let _dragEndedAt = 0;

export function markDragEnded(): void {
  _dragEndedAt = Date.now();
}

export function recentlyDragEnded(thresholdMs = 200): boolean {
  return Date.now() - _dragEndedAt < thresholdMs;
}
