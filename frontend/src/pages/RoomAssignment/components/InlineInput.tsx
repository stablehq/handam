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
}: InlineInputProps) => {
  const [localValue, setLocalValue] = useState(value);
  useEffect(() => setLocalValue(value), [value]);
  if (disabled) {
    return (
      <span className={`w-full text-body truncate ${className || ''}`}>
        {value || <span className="text-[#B0B8C1] dark:text-[#4E5968]">{placeholder}</span>}
      </span>
    );
  }
  return (
    <input
      className={`bg-transparent border-none outline-none w-full text-body
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
