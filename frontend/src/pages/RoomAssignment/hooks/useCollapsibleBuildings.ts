import { useCallback, useState } from 'react';

/**
 * 빌딩별 접기/펼치기 상태를 관리한다.
 *
 * Phase A-4: RoomAssignment.tsx 의 collapsedBuildings + toggleBuildingCollapse 분리.
 * - building_id 가 null 인 케이스(미지정 그룹)도 키로 사용 가능해야 하므로 Set 사용.
 */
export function useCollapsibleBuildings() {
  const [collapsedBuildings, setCollapsedBuildings] = useState<Set<number | null>>(new Set());

  const toggleBuildingCollapse = useCallback((buildingId: number | null) => {
    setCollapsedBuildings((prev) => {
      const next = new Set(prev);
      if (next.has(buildingId)) next.delete(buildingId);
      else next.add(buildingId);
      return next;
    });
  }, []);

  return { collapsedBuildings, toggleBuildingCollapse };
}
