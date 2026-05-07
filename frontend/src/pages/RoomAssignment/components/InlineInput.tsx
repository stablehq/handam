import { useState, useEffect, useRef } from 'react';

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
}: InlineInputProps) => {
  const [editing, setEditing] = useState(false);
  const [localValue, setLocalValue] = useState(value);
  const lastTapRef = useRef(0);

  // 외부 value 변경 동기화 (편집 중이 아닐 때만)
  useEffect(() => {
    if (!editing) setLocalValue(value);
  }, [value, editing]);

  // autoFocus=true 면 마운트 시 즉시 편집 모드 진입 (quickAdd 케이스).
  // 마운트 1회만 동작; 이후 prop 변경 무시.
  useEffect(() => {
    if (autoFocus && !disabled) {
      setEditing(true);
      onActivate?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activate = () => {
    if (disabled) return;
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
    if (localValue !== value) onSave(resId, field, localValue);
    setEditing(false);
  };

  const cancel = () => {
    setLocalValue(value);
    setEditing(false);
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
      onDoubleClick={activate}
      onTouchEnd={handleTouchEnd}
      title={disabled ? undefined : '더블클릭하여 수정'}
      // touchAction: 'manipulation' 제거 — iOS에서 long-press → contextmenu 도 같이
      // 차단해 컨텍스트 메뉴가 안 뜸. 더블탭 줌은 handleTouchEnd 의 preventDefault 로
      // 충분히 막힘 (RoomMemoEditor 도 동일 방식).
      // non-compact 모드: block + 세로 padding 으로 셀 전체를 더블클릭 영역으로 확장
      // (값 비어있을 때 클릭 범위가 좁아 수정 활성화 어렵던 문제 해결)
      // compact 모드 (이름): 컨텐츠 너비 유지로 inline span 그대로
      className={`${compact ? '' : 'w-full block py-1.5'} text-body truncate select-none ${disabled ? '' : 'cursor-text'} ${className || ''}`}
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
