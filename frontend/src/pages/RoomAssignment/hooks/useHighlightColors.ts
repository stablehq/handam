import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { settingsAPI } from '../../../services/api';
import { loadRowColors, saveRowColors, type RowColorSettings } from '@/lib/highlight-colors';

/**
 * 행 하이라이트 색상 시스템 (커스텀 hex / 기본 색상 / 다크모드 추적).
 *
 * Phase B-3: RoomAssignment.tsx 의 customHighlightColors / rowColors / isDarkMode 통합.
 * - 마운트 시 서버에서 커스텀 색상 로드.
 * - `<html>` class 변화로 다크모드 감지 (MutationObserver).
 * - applyCustomColors / applyRowColors 는 저장 동작 + 토스트까지 포함.
 */
export function useHighlightColors() {
  const [customHighlightColors, setCustomHighlightColors] = useState<string[]>([]);
  const [rowColors, setRowColors] = useState<RowColorSettings>(loadRowColors);
  const [isDarkMode, setIsDarkMode] = useState(() => document.documentElement.classList.contains('dark'));

  // 마운트 시 서버에서 커스텀 색상 로드
  useEffect(() => {
    settingsAPI.getHighlightColors().then(res => {
      setCustomHighlightColors(res.data.colors || []);
    }).catch(() => { /* ignore */ });
  }, []);

  // <html class="dark"> 토글 감지
  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDarkMode(document.documentElement.classList.contains('dark'));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  const applyCustomColors = useCallback(async (colors: string[]) => {
    await settingsAPI.updateHighlightColors(colors);
    setCustomHighlightColors(colors);
    toast.success('커스텀 색상이 저장되었습니다');
  }, []);

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
