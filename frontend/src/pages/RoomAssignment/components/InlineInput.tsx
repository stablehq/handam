import { useState, useEffect } from 'react';

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
}: InlineInputProps) => {
  const [localValue, setLocalValue] = useState(value);
  useEffect(() => setLocalValue(value), [value]);
  if (disabled) {
    return (
      <span className={`${compact ? '' : 'w-full'} text-body truncate ${className || ''}`}>
        {value || <span className="text-[#B0B8C1] dark:text-[#4E5968]">{placeholder}</span>}
      </span>
    );
  }
  return (
    <input
      className={`bg-transparent border-none outline-none ${compact ? 'field-sizing-content min-w-[40px]' : 'w-full'} text-body
        focus:bg-[#F2F4F6] focus:rounded focus:px-1 dark:focus:bg-[#2C2C34]
        transition-colors ${className || ''}`}
      value={localValue}
      onChange={(e) => setLocalValue(e.target.value)}
      onBlur={() => { if (localValue !== value) onSave(resId, field, localValue); }}
      placeholder={placeholder}
      autoFocus={autoFocus}
    />
  );
};
