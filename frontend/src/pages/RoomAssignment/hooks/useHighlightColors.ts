import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { settingsAPI } from '../../../services/api';
import { queryKeys } from '@/lib/queryKeys';
import { loadRowColors, saveRowColors, type RowColorSettings } from '@/lib/highlight-colors';

/**
 * 행 하이라이트 색상 시스템 (커스텀 hex / 기본 색상 / 다크모드 추적).
 *
 * Phase B-3: RoomAssignment.tsx 의 customHighlightColors / rowColors / isDarkMode 통합.
 * Phase 3b: getHighlightColors → useQuery (staleTime 5min).
 *           updateHighlightColors → useMutation (optimistic via setQueryData).
 * - `<html>` class 변화로 다크모드 감지 (MutationObserver).
 * - rowColors 는 순수 로컬 UI 상태 — 변경 없음.
 */
export function useHighlightColors() {
  const qc = useQueryClient();
  const [rowColors, setRowColors] = useState<RowColorSettings>(loadRowColors);
  const [isDarkMode, setIsDarkMode] = useState(() => document.documentElement.classList.contains('dark'));

  // ===== useQuery: 커스텀 색상 =====
  const { data: colorsData } = useQuery({
    queryKey: queryKeys.settings.highlightColors(),
    queryFn: () => settingsAPI.getHighlightColors().then(res => res.data.colors as string[] || []),
    staleTime: 5 * 60 * 1000,
  });

  const customHighlightColors: string[] = colorsData ?? [];

  // ===== useMutation: 커스텀 색상 저장 (optimistic) =====
  const updateColorsMutation = useMutation({
    mutationFn: (colors: string[]) => settingsAPI.updateHighlightColors(colors),
    onMutate: async (colors) => {
      await qc.cancelQueries({ queryKey: queryKeys.settings.highlightColors() });
      const previous = qc.getQueryData<string[]>(queryKeys.settings.highlightColors());
      qc.setQueryData(queryKeys.settings.highlightColors(), colors);
      return { previous };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous !== undefined) {
        qc.setQueryData(queryKeys.settings.highlightColors(), ctx.previous);
      }
      toast.error('색상 저장 실패');
    },
    onSuccess: () => {
      toast.success('커스텀 색상이 저장되었습니다');
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKeys.settings.highlightColors() });
    },
  });

  // <html class="dark"> 토글 감지
  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDarkMode(document.documentElement.classList.contains('dark'));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  const applyCustomColors = useCallback(
    (colors: string[]): Promise<void> =>
      updateColorsMutation.mutateAsync(colors).then(() => undefined),
    [updateColorsMutation],
  );

  const applyRowColors = useCallback((colors: RowColorSettings) => {
    setRowColors(colors);
    saveRowColors(colors);
    toast.success('행 스타일이 저장되었습니다');
  }, []);

  return {
    customHighlightColors,
    rowColors,
    isDarkMode,
    applyCustomColors,
    applyRowColors,
  };
}
