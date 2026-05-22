import { useState, useEffect, useRef } from 'react';
import { recentlyDragEnded } from '../utils/dragState';

interface InlineInputProps {
  value: string;
  field: string;
  resId: number;
  className?: string;
  placeholder?: string;
  onSave: (resId: number, field: string, value: string) => void;
  autoFocus?: boolean;
  disabled?: boolean;
  // display 모드(disabled)에서 w-full 을 제거해 컨텐츠 너비로 축소.
  // 이름 + suffix 같이 옆에 다른 요소를 좌측정렬로 붙여야 할 때 사용.
  compact?: boolean;
  // 편집 모드 진입 직후 호출. 행의 deselect 250ms 타이머 취소 등에 사용.
  onActivate?: () => void;
  // 편집 모드 종료(blur 또는 ESC cancel) 시 호출. activeQuickGuestId 해제 등에 사용.
  onDeactivate?: () => void;
  /** PC에서 단일클릭으로 편집 진입 (true). false면 더블클릭 (모바일 기존 동작). */
  singleClick?: boolean;
}

export const InlineInput = ({
  value,
  field,
  resId,
  className,
  placeholder,
  onSave,
  autoFocus,
  disabled,
  compact,
  onActivate,
  onDeactivate,
  singleClick,
}: InlineInputProps) => {
  const [editing, setEditing] = useState(false);
  const [localValue, setLocalValue] = useState(value);
  const lastTapRef = useRef(0);
  const committedRef = useRef(false);

  // 외부 value 변경 동기화 (편집 중이 아닐 때만)
  useEffect(() => {
    if (!editing) setLocalValue(value);
  }, [value, editing]);

  // autoFocus=true 면 마운트 시 즉시 편집 모드 진입 (quickAdd 케이스).
  // 마운트 1회만 동작; 이후 prop 변경 무시.
  useEffect(() => {
    if (autoFocus && !disabled) {
      committedRef.current = false;
      setEditing(true);
      onActivate?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activate = () => {
    if (disabled) return;
    committedRef.current = false;
    setEditing(true);
    onActivate?.();
  };

  // 모바일 더블탭 감지 (300ms 윈도우)
  const handleTouchEnd = (e: React.TouchEvent) => {
    const now = Date.now();
    if (now - lastTapRef.current < 300) {
      e.preventDefault();
      activate();
    }
    lastTapRef.current = now;
  };

  const commit = () => {
    if (committedRef.current) return;
    committedRef.current = true;
    if (localValue !== value) onSave(resId, field, localValue);
    setEditing(false);
    onDeactivate?.();
  };

  const cancel = () => {
    setLocalValue(value);
    setEditing(false);
    onDeactivate?.();
  };

  if (editing) {
    return (
      <input
        className={`bg-transparent border-none outline-none ${compact ? 'field-sizing-content min-w-[40px]' : 'w-full'} text-body
          focus:bg-[#F2F4F6] focus:rounded focus:px-1 dark:focus:bg-[#2C2C34]
          transition-colors ${className || ''}`}
        value={localValue}
        autoFocus
        onChange={(e) => setLocalValue(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.stopPropagation();
            commit();
            (e.target as HTMLInputElement).blur();
          } else if (e.key === 'Escape') {
            cancel();
          }
        }}
        // 편집 중 클릭/터치/우클릭은 행 핸들러(선택 토글, 컨텍스트 메뉴)로 전파 차단.
        // 우클릭은 브라우저 native input context (paste/select-all 등) 가 뜨도록 함.
        onClick={(e) => e.stopPropagation()}
        onMouseDown={(e) => e.stopPropagation()}
        onTouchStart={(e) => e.stopPropagation()}
        onContextMenu={(e) => e.stopPropagation()}
        placeholder={placeholder}
      />
    );
  }

  return (
    <span
      onClick={singleClick ? () => {
        // dnd-kit drag 종료 직후 합성 click 무시 (드래그 후 의도치 않은 편집 진입 방지)
        if (recentlyDragEnded()) return;
        activate();
      } : undefined}
      onDoubleClick={!singleClick ? activate : undefined}
      onTouchEnd={handleTouchEnd}
      // 키보드 Tab 흐름: span 자체를 focusable 로 만들고 키보드 focus 시 자동 activate.
      // 활성 input 에서 Tab → blur(commit) → 다음 InlineInput span 으로 focus 이동
      // → onFocus → activate → input 모드 진입. (이름→전화→파티→성별→메모 자연스러운 흐름)
      // :focus-visible 매칭으로 키보드 focus 만 활성화 — 마우스 단일 클릭/터치 focus 는
      // activate 하지 않아 더블클릭 진입 규칙 유지.
      tabIndex={disabled ? -1 : 0}
      onFocus={(e) => {
        if (e.currentTarget.matches(':focus-visible')) activate();
      }}
      title={value ? String(value) : (disabled ? undefined : (singleClick ? '클릭하여 수정' : '더블클릭하여 수정'))}
      // touchAction: 'manipulation' 제거 — iOS에서 long-press → contextmenu 도 같이
      // 차단해 컨텍스트 메뉴가 안 뜸. 더블탭 줌은 handleTouchEnd 의 preventDefault 로
      // 충분히 막힘 (RoomMemoEditor 도 동일 방식).
      // non-compact 모드: block + 세로 padding 으로 셀 전체를 더블클릭 영역으로 확장
      // (값 비어있을 때 클릭 범위가 좁아 수정 활성화 어렵던 문제 해결)
      // compact 모드 (이름): 컨텐츠 너비 유지로 inline span 그대로
      className={`${compact ? '' : 'w-full block py-1.5'} text-body truncate select-none ${disabled ? '' : 'cursor-text'} outline-none focus-visible:bg-[#F2F4F6] dark:focus-visible:bg-[#2C2C34] focus-visible:rounded ${className || ''}`}
    >
      {value || (
        <span className="text-[#B0B8C1] dark:text-[#4E5968]">
          {/* placeholder 가 빈 문자열인 경우에도 nbsp 로 클릭 영역 보장 (값 비어있을 때 더블클릭 안 먹는 회귀 방지) */}
          {placeholder || ' '}
        </span>
      )}
    </span>
  );
};
