import React, { useState, useEffect, useRef } from 'react';

interface RoomMemoEditorProps {
  roomId: number;
  memo: string;
  onSave: (roomId: number, memo: string) => Promise<void>;
}

export function RoomMemoEditor({ roomId, memo, onSave }: RoomMemoEditorProps) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(memo);
  const [saving, setSaving] = useState(false);
  const lastTapRef = useRef(0);

  useEffect(() => {
    if (!editing) setValue(memo);
  }, [memo, editing]);

  const activate = (e?: React.SyntheticEvent) => {
    if (e) e.stopPropagation();
    setEditing(true);
  };

  const handleTouchEnd = (e: React.TouchEvent) => {
    const now = Date.now();
    if (now - lastTapRef.current < 300) {
      e.preventDefault();
      activate(e);
    }
    lastTapRef.current = now;
  };

  const commit = async () => {
    const next = value.trim();
    if (next === memo) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(roomId, next);
      setEditing(false);
    } catch {
      setValue(memo);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  if (editing) {
    return (
      <input
        type="text"
        value={value}
        autoFocus
        disabled={saving}
        onChange={(e) => setValue(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            (e.target as HTMLInputElement).blur();
          } else if (e.key === 'Escape') {
            setValue(memo);
            setEditing(false);
          }
        }}
        onClick={(e) => e.stopPropagation()}
        onMouseDown={(e) => e.stopPropagation()}
        onTouchStart={(e) => e.stopPropagation()}
        placeholder="메모"
        className="text-caption flex-1 min-w-0 bg-transparent border-b border-[#3182F6] outline-none px-1 py-0 text-[#191F28] dark:text-white placeholder-[#D1D5DB] dark:placeholder-[#4E5968]"
      />
    );
  }

  return (
    <span
      onDoubleClick={activate}
      onTouchEnd={handleTouchEnd}
      title="더블클릭하여 메모 수정"
      className={`text-caption truncate cursor-text select-none flex-1 min-w-0 ${
        memo
          ? 'text-[#8B95A1] dark:text-gray-400'
          : 'text-[#D1D5DB] dark:text-[#4E5968]'
      }`}
    >
      {memo || '메모'}
    </span>
  );
}
