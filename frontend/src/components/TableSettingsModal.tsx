import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Modal, ModalHeader, ModalBody, ModalFooter } from '@/components/ui/modal';
import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import { Plus, X, RotateCcw, Palette, Pipette } from 'lucide-react';
import {
  DEFAULT_ROW_COLORS,
  DEFAULT_DIVIDER_COLOR,
  GOOGLE_SHEETS_PALETTE,
  isLightColor,
  type RowColorSettings,
} from '@/lib/highlight-colors';

interface RoomEntry {
  room_id: number;
  room_number: string;
  building_name: string | null;
}

interface RoomGroup {
  id: number;
  name: string;
  sort_order: number;
  color?: string;
  room_ids: number[];
}

interface TableSettingsModalProps {
  show: boolean;
  onClose: () => void;
  // Tab 1: Highlight colors
  customColors: string[];
  onSaveCustomColors: (colors: string[]) => Promise<void>;
  // Tab 2: Dividers
  activeRoomEntries: RoomEntry[];
  roomGroups: RoomGroup[];
  roomInfoMap: Record<string, string>;
  onSaveDividers: (dividers: Set<number>, dividerColors: Map<number, string>) => Promise<void>;
  // Tab 3: Row styles
  rowColors: RowColorSettings;
  onSaveRowColors: (colors: RowColorSettings) => void;
}

type TabId = 'highlight' | 'dividers' | 'rowstyle';

const TABS: { id: TabId; label: string }[] = [
  { id: 'highlight', label: '하이라이트 색상' },
  { id: 'dividers', label: '구분선' },
  { id: 'rowstyle', label: '행 스타일' },
];

export default function TableSettingsModal({
  show,
  onClose,
  customColors,
  onSaveCustomColors,
  activeRoomEntries,
  roomGroups,
  roomInfoMap,
  onSaveDividers,
  rowColors,
  onSaveRowColors,
}: TableSettingsModalProps) {
  const [activeTab, setActiveTab] = useState<TabId>('highlight');

  // --- Tab 1: Highlight colors state ---
  const [localCustomColors, setLocalCustomColors] = useState<string[]>([]);
  const [savingColors, setSavingColors] = useState(false);
  const colorInputRef = useRef<HTMLInputElement>(null);

  // --- Tab 2: Dividers state ---
  const [dividers, setDividers] = useState<Set<number>>(new Set());
  const [dividerColors, setDividerColors] = useState<Map<number, string>>(new Map());
  const [savingDividers, setSavingDividers] = useState(false);
  const [colorPopupDivIdx, setColorPopupDivIdx] = useState<number | null>(null);
  const [colorPopupPos, setColorPopupPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const colorPopupRef = useRef<HTMLDivElement>(null);

  // --- Tab 3: Row style state ---
  const [localRowColors, setLocalRowColors] = useState<RowColorSettings>({ ...DEFAULT_ROW_COLORS });
  const evenColorRef = useRef<HTMLInputElement>(null);
  const oddColorRef = useRef<HTMLInputElement>(null);
  const overbookingColorRef = useRef<HTMLInputElement>(null);

  // Initialize state when modal opens
  useEffect(() => {
    if (!show) return;

    // Tab 1: sync custom colors from props
    setLocalCustomColors([...customColors]);

    // Tab 2: initialize dividers from roomGroups
    const roomIds = activeRoomEntries.map(e => e.room_id);
    const groupMap = new Map<number, number>();
    roomGroups.forEach(g => g.room_ids.forEach(rid => groupMap.set(rid, g.id)));
    const initDividers = new Set<number>();
    if (roomGroups.length > 0) {
      initDividers.add(-1);
      initDividers.add(roomIds.length - 1);
    }
    roomIds.forEach((id, idx) => {
      if (idx < roomIds.length - 1) {
        const curGroup = groupMap.get(id);
        const nextGroup = groupMap.get(roomIds[idx + 1]);
        if (curGroup !== undefined && nextGroup !== undefined && curGroup !== nextGroup) {
          initDividers.add(idx);
        }
        if ((curGroup !== undefined) !== (nextGroup !== undefined)) {
          initDividers.add(idx);
        }
      }
    });
    setDividers(initDividers);

    // Tab 2: initialize divider colors from roomGroups
    const initColors = new Map<number, string>();
    // Build a map from group boundary index → group color
    for (let gIdx = 0; gIdx < roomGroups.length; gIdx++) {
      const g = roomGroups[gIdx];
      if (g.color) {
        // Find the last room_id of this group in activeRoomEntries
        const lastId = g.room_ids[g.room_ids.length - 1];
        const lastIdx = roomIds.indexOf(lastId);
        if (lastIdx >= 0) {
          initColors.set(lastIdx, g.color);
        }
        // Also handle the leading -1 divider for first group
        if (gIdx === 0) {
          initColors.set(-1, g.color);
        }
      }
    }
    setDividerColors(initColors);

    // Tab 3: sync row colors from props
    setLocalRowColors({ ...rowColors });
  }, [show]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- Tab 1 handlers ---
  function handleAddCustomColor(hex: string) {
    if (!localCustomColors.includes(hex)) {
      setLocalCustomColors(prev => [...prev, hex]);
    }
  }

  function handleRemoveCustomColor(hex: string) {
    setLocalCustomColors(prev => prev.filter(c => c !== hex));
  }

  async function handleSaveColors() {
    setSavingColors(true);
    try {
      await onSaveCustomColors(localCustomColors);
      onClose();
    } finally {
      setSavingColors(false);
    }
  }

  // Close color popup on outside click
  useEffect(() => {
    if (colorPopupDivIdx === null) return;
    function handleClick(e: MouseEvent) {
      if (colorPopupRef.current && !colorPopupRef.current.contains(e.target as Node)) {
        setColorPopupDivIdx(null);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [colorPopupDivIdx]);

  // --- Tab 2 handlers ---
  function toggleDivider(divIdx: number) {
    setDividers(prev => {
      const next = new Set(prev);
      if (next.has(divIdx)) {
        next.delete(divIdx);
        setDividerColors(cm => {
          const next2 = new Map(cm);
          next2.delete(divIdx);
          return next2;
        });
      } else {
        next.add(divIdx);
      }
      return next;
    });
  }

  function setDividerColor(divIdx: number, color: string) {
    setDividerColors(prev => {
      const next = new Map(prev);
      next.set(divIdx, color);
      return next;
    });
  }

  async function handleSaveDividers() {
    setSavingDividers(true);
    try {
      await onSaveDividers(dividers, dividerColors);
      onClose();
    } finally {
      setSavingDividers(false);
    }
  }

  // --- Tab 3 handlers ---
  function handleRowColorChange(field: keyof RowColorSettings, value: string) {
    setLocalRowColors(prev => ({ ...prev, [field]: value }));
  }

  function handleResetRowColors() {
    setLocalRowColors({ ...DEFAULT_ROW_COLORS });
  }

  function handleSaveRowColors() {
    onSaveRowColors(localRowColors);
    onClose();
  }

  // --- Render helpers ---
  function renderDividerSlot(divIdx: number) {
    const isActive = dividers.has(divIdx);
    const currentColor = dividerColors.get(divIdx) ?? DEFAULT_DIVIDER_COLOR;
    const isPopupOpen = colorPopupDivIdx === divIdx;

    return (
      <div key={`divider-slot-${divIdx}`}>
        {/* Clickable divider line */}
        <div
          className="relative py-1.5 flex items-center cursor-pointer group/divider"
          onClick={() => toggleDivider(divIdx)}
        >
          {isActive ? (
            <>
              <div
                className="absolute inset-x-4 border-t-2"
                style={{ borderColor: currentColor }}
              />
              <div
                className="absolute left-1/2 -translate-x-1/2 z-10 text-white rounded-full h-5 w-5 flex items-center justify-center opacity-0 group-hover/divider:opacity-100 transition-opacity"
                style={{ backgroundColor: currentColor }}
              >
                <X className="h-3 w-3" />
              </div>
              {/* Color picker icon at right end */}
              <button
                className="absolute right-1 z-10 w-5 h-5 rounded-full border border-gray-300 dark:border-gray-600 flex items-center justify-center hover:scale-110 transition-transform"
                style={{ backgroundColor: currentColor }}
                title="구분선 색상 변경"
                onClick={(e) => {
                  e.stopPropagation();
                  if (isPopupOpen) {
                    setColorPopupDivIdx(null);
                  } else {
                    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                    setColorPopupPos({ x: rect.right + 8, y: rect.top + rect.height / 2 });
                    setColorPopupDivIdx(divIdx);
                  }
                }}
              >
                <Pipette className={`h-2.5 w-2.5 ${isLightColor(currentColor) ? 'text-[#4E5968]' : 'text-white'}`} />
              </button>
            </>
          ) : (
            <>
              <div className="absolute inset-x-4 border-t border-dashed border-transparent group-hover/divider:border-[#D1D5DB] dark:group-hover/divider:border-[#4E5968] transition-colors" />
              <div className="absolute left-1/2 -translate-x-1/2 z-10 bg-[#E5E8EB] dark:bg-[#2C2C34] text-[#8B95A1] rounded-full h-5 w-5 flex items-center justify-center opacity-0 group-hover/divider:opacity-100 transition-opacity">
                <Plus className="h-3 w-3" />
              </div>
            </>
          )}
        </div>
      </div>
    );
  }

  // --- Tab content ---
  function renderHighlightTab() {
    return (
      <div className="space-y-4">
        {/* Quick colors — selected from palette */}
        <div>
          <p className="text-label font-medium text-[#4E5968] dark:text-gray-300 mb-2">퀵 컬러</p>
          <div className="flex flex-wrap items-center gap-2">
            {localCustomColors.map(hex => (
              <div key={hex} className="relative group/swatch flex-shrink-0">
                <div
                  className="w-6 h-6 rounded-full border border-[#E5E8EB] dark:border-gray-700 cursor-default"
                  style={{ backgroundColor: hex }}
                  title={hex}
                />
                <button
                  onClick={() => handleRemoveCustomColor(hex)}
                  className="absolute -top-1 -right-1 w-3.5 h-3.5 rounded-full bg-[#F04452] text-white items-center justify-center hidden group-hover/swatch:flex"
                  title="삭제"
                >
                  <X className="h-2 w-2" />
                </button>
              </div>
            ))}
            {/* Native color picker for truly custom colors */}
            <button
              onClick={() => colorInputRef.current?.click()}
              className="w-6 h-6 rounded-full border-2 border-dashed border-[#D1D5DB] dark:border-gray-600 flex items-center justify-center hover:border-[#3182F6] transition-colors flex-shrink-0"
              title="직접 색상 추가"
            >
              <Plus className="h-3.5 w-3.5 text-[#8B95A1]" />
            </button>
            <input
              ref={colorInputRef}
              type="color"
              className="sr-only"
              defaultValue="#3182F6"
              onChange={e => handleAddCustomColor(e.target.value)}
            />
          </div>
          {localCustomColors.length === 0 && (
            <p className="text-caption text-[#B0B8C1] dark:text-gray-600 mt-2">
              아래 팔레트에서 클릭하여 퀵 컬러를 추가하세요
            </p>
          )}
        </div>

        <div className="border-t border-[#E5E8EB] dark:border-gray-800" />

        {/* Google Sheets color palette */}
        <div>
          <p className="text-label font-medium text-[#4E5968] dark:text-gray-300 mb-2">색상 팔레트</p>
          <div className="flex flex-col gap-0.5">
            {GOOGLE_SHEETS_PALETTE.map((row, rowIdx) => (
              <React.Fragment key={rowIdx}>
                {rowIdx === 2 && <div className="h-1" />}
                <div className="flex gap-0.5">
                  {row.map(hex => {
                    const isSelected = localCustomColors.includes(hex);
                    return (
                      <button
                        key={hex}
                        title={isSelected ? `${hex} (추가됨)` : `${hex} — 클릭하여 퀵 컬러 추가`}
                        onClick={() => {
                          if (isSelected) {
                            handleRemoveCustomColor(hex);
                          } else {
                            handleAddCustomColor(hex);
                          }
                        }}
                        className={`w-[28px] h-[28px] flex-shrink-0 cursor-pointer hover:scale-110 transition-transform relative ${
                          rowIdx < 2 ? 'rounded-sm' : 'rounded-sm'
                        } ${
                          isSelected
                            ? 'ring-2 ring-[#3182F6] ring-offset-1 dark:ring-offset-[#1E1E24] z-10'
                            : 'border border-black/10 dark:border-white/10'
                        }`}
                        style={{ backgroundColor: hex }}
                      >
                        {isSelected && (
                          <span className={`absolute inset-0 flex items-center justify-center text-[11px] font-bold ${isLightColor(hex) ? 'text-[#191F28]' : 'text-white'}`}>
                            ✓
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </React.Fragment>
            ))}
          </div>
        </div>
      </div>
    );
  }

  function renderDividersTab() {
    if (activeRoomEntries.length === 0) {
      return (
        <div className="flex flex-col items-center py-10 text-[#8B95A1]">
          <Palette className="h-10 w-10 mb-2 opacity-30" />
          <p className="text-label">표시할 객실이 없습니다</p>
        </div>
      );
    }

    return (
      <div className="space-y-0">
        {activeRoomEntries.map((entry, idx) => (
          <React.Fragment key={entry.room_id}>
            {idx === 0 && renderDividerSlot(-1)}

            <div className="flex items-center px-4 py-1.5 text-caption">
              {entry.building_name && (
                <span className="text-caption text-[#B0B8C1] dark:text-[#4E5968] w-16">
                  {entry.building_name}
                </span>
              )}
              <span className="font-medium text-[#191F28] dark:text-white w-28 truncate">{entry.room_number}</span>
              <span className="text-[#8B95A1] dark:text-[#8B95A1] text-caption">
                {roomInfoMap[entry.room_number] || ''}
              </span>
            </div>

            {renderDividerSlot(idx)}
          </React.Fragment>
        ))}
      </div>
    );
  }

  function renderRowStyleTab() {
    const colorFields: { field: keyof RowColorSettings; label: string; ref: React.RefObject<HTMLInputElement> }[] = [
      { field: 'even', label: '짝수 그룹', ref: evenColorRef },
      { field: 'odd', label: '홀수 그룹', ref: oddColorRef },
      { field: 'overbooking', label: '초과배정', ref: overbookingColorRef },
    ];

    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <p className="text-label font-medium text-[#4E5968] dark:text-gray-300">객실 행 색상</p>
          <button
            onClick={handleResetRowColors}
            className="flex items-center gap-1 text-caption text-[#8B95A1] hover:text-[#3182F6] transition-colors"
            title="기본값으로 초기화"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            초기화
          </button>
        </div>

        <div className="space-y-3">
          {colorFields.map(({ field, label, ref }) => (
            <div key={field} className="flex items-center justify-between">
              <div>
                <p className="text-body text-[#191F28] dark:text-white">{label}</p>
                {field === 'overbooking' && (
                  <p className="text-caption text-[#8B95A1]">도미토리 외 2명 이상 배정 시</p>
                )}
              </div>
              <div className="flex items-center gap-2">
                {/* Hex display */}
                <span className="text-caption text-[#8B95A1] font-mono tabular-nums">
                  {localRowColors[field].toUpperCase()}
                </span>
                {/* Color swatch trigger */}
                <button
                  onClick={() => ref.current?.click()}
                  className="w-8 h-8 rounded-lg border-2 border-[#E5E8EB] dark:border-gray-700 cursor-pointer hover:scale-105 transition-transform shadow-sm"
                  style={{ backgroundColor: localRowColors[field] }}
                  title={`${label} 색상 변경`}
                />
                <input
                  ref={ref}
                  type="color"
                  className="sr-only"
                  value={localRowColors[field]}
                  onChange={e => handleRowColorChange(field, e.target.value)}
                />
              </div>
            </div>
          ))}
        </div>

        <div className="rounded-xl bg-[#F8F9FA] dark:bg-[#17171C] p-3 border border-[#E5E8EB] dark:border-gray-800">
          <p className="text-caption text-[#8B95A1]">
            다크 모드 색상은 밝기 모드 색상에서 자동으로 조정됩니다.
          </p>
        </div>
      </div>
    );
  }

  // --- Footer per tab ---
  function renderFooter() {
    if (activeTab === 'highlight') {
      return (
        <>
          <Button color="light" onClick={onClose}>취소</Button>
          <Button color="blue" disabled={savingColors} onClick={handleSaveColors}>
            {savingColors ? <><Spinner size="sm" className="mr-2" />저장 중...</> : '저장'}
          </Button>
        </>
      );
    }
    if (activeTab === 'dividers') {
      return (
        <>
          <Button color="light" onClick={onClose}>취소</Button>
          <Button color="blue" disabled={savingDividers} onClick={handleSaveDividers}>
            {savingDividers ? <><Spinner size="sm" className="mr-2" />저장 중...</> : '저장'}
          </Button>
        </>
      );
    }
    // rowstyle
    return (
      <>
        <Button color="light" onClick={onClose}>취소</Button>
        <Button color="blue" onClick={handleSaveRowColors}>저장</Button>
      </>
    );
  }

  return (
    <>
    <Modal show={show} onClose={onClose} size="md">
      <ModalHeader>테이블 설정</ModalHeader>
      <ModalBody className="p-0">
        {/* Tab bar */}
        <div className="flex items-center gap-1 px-4 pt-4 pb-0">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-1.5 rounded-lg text-label font-medium transition-colors ${
                activeTab === tab.id
                  ? 'bg-[#3182F6] text-white'
                  : 'text-[#8B95A1] hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34]'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="p-4">
          {activeTab === 'highlight' && renderHighlightTab()}
          {activeTab === 'dividers' && renderDividersTab()}
          {activeTab === 'rowstyle' && renderRowStyleTab()}
        </div>
      </ModalBody>
      <ModalFooter>
        {renderFooter()}
      </ModalFooter>
    </Modal>

      {/* Divider color popup — portal to escape modal overflow */}
      {colorPopupDivIdx !== null && (() => {
        const popupCurrentColor = dividerColors.get(colorPopupDivIdx) ?? DEFAULT_DIVIDER_COLOR;
        return createPortal(
          <div
            ref={colorPopupRef}
            style={{ position: 'fixed', left: colorPopupPos.x, top: colorPopupPos.y, transform: 'translateY(-50%)', zIndex: 10100 }}
            className="bg-white dark:bg-[#1E1E24] border border-[#E5E8EB] dark:border-gray-800 rounded-xl shadow-lg p-2.5 animate-in fade-in zoom-in-95 duration-100"
          >
            <div className="grid grid-cols-5 gap-2">
              {popupCurrentColor !== DEFAULT_DIVIDER_COLOR && !localCustomColors.includes(popupCurrentColor) && (
                <button
                  title={`${popupCurrentColor} (현재)`}
                  onClick={() => setColorPopupDivIdx(null)}
                  className="w-5 h-5 rounded-full border cursor-pointer flex-shrink-0 ring-2 ring-offset-1 ring-[#3182F6] dark:ring-offset-[#1E1E24]"
                  style={{ backgroundColor: popupCurrentColor }}
                />
              )}
              {localCustomColors.map(hex => (
                <button
                  key={hex}
                  title={hex}
                  onClick={() => {
                    setDividerColor(colorPopupDivIdx, hex);
                    setColorPopupDivIdx(null);
                  }}
                  className={`w-5 h-5 rounded-full border cursor-pointer hover:scale-110 transition-transform flex-shrink-0 ${
                    popupCurrentColor === hex
                      ? 'ring-2 ring-offset-1 ring-[#3182F6] dark:ring-offset-[#1E1E24]'
                      : 'border-gray-300 dark:border-gray-600'
                  }`}
                  style={{ backgroundColor: hex }}
                />
              ))}
            </div>
            {localCustomColors.length === 0 && popupCurrentColor === DEFAULT_DIVIDER_COLOR && (
              <p className="text-caption text-[#B0B8C1] whitespace-nowrap">하이라이트 탭에서 퀵 컬러를 추가하세요</p>
            )}
          </div>,
          document.body,
        );
      })()}
    </>
  );
}
