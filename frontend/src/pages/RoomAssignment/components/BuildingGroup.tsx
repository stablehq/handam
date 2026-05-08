import React from 'react';
import { Plus, Minus } from 'lucide-react';
import type { RoomEntry } from './RoomRow';

export interface BuildingGroupData {
  building_id: number | null;
  building_name: string | null;
  entries: RoomEntry[];
  assignedCount: number;
  totalCount: number;
}

interface BuildingGroupProps {
  group: BuildingGroupData;
  isCollapsed: boolean;
  onToggle: (buildingId: number | null) => void;
  /** 줄무늬 색상 계산용 누적 인덱스 — 이 그룹 첫 객실의 시작 rowIndex. */
  startRowIndex: number;
  renderRoomRow: (entry: RoomEntry, rowIndex: number) => React.ReactNode;
}

/**
 * 빌딩별 객실 묶음 — 좌측 북마크 탭으로 접기/펼치기.
 *
 * Phase G-3: RoomAssignment.tsx 의 buildingGroups.map 인라인 JSX 분리.
 */
export function BuildingGroup({
  group, isCollapsed, onToggle, startRowIndex, renderRoomRow,
}: BuildingGroupProps) {
  const buildingLabel = group.building_name || '기타';
  const summary = `${group.assignedCount}/${group.totalCount}`;

  return (
    <div className="relative">
      {/* Bookmark tab */}
      <div
        className="absolute -left-[2px] top-0 z-10 flex items-center justify-center cursor-pointer select-none rounded-l-md w-4 h-6 border border-r-0 border-[#E5E8EB] dark:border-[#2C2C34] bg-white dark:bg-[#1E1E24] hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34] transition-colors shadow-sm"
        style={{ transform: 'translateX(-100%)' }}
        onClick={() => onToggle(group.building_id)}
        title={`${buildingLabel} ${summary}`}
      >
        {isCollapsed
          ? <Plus className="h-2.5 w-2.5 text-[#8B95A1]" />
          : <Minus className="h-2.5 w-2.5 text-[#8B95A1]" />}
      </div>
      {isCollapsed ? (
        <div
          className="flex items-center h-8 px-3 border-b border-[#E5E8EB] dark:border-[#2C2C34] bg-[#F8F9FA]/50 dark:bg-[#17171C]/30 cursor-pointer"
          onClick={() => onToggle(group.building_id)}
        >
          <span className="text-caption text-[#B0B8C1] dark:text-gray-600">{buildingLabel} ({summary})</span>
        </div>
      ) : (
        group.entries.map((entry, i) => renderRoomRow(entry, startRowIndex + i))
      )}
    </div>
  );
}
