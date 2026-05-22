import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Dayjs } from 'dayjs';
import type { Reservation } from '../types';
import { formatGuestSuffix } from '../utils/reservationFormat';

const DEFAULT_COL_WIDTHS = { name: 60, phone: 120, party: 60, gender: 60, roomType: 100, notes: 100, sms: 140, nextDay: 96 };

const COL_WIDTHS_STORAGE_KEY = 'roomAssignment_colWidths_by_date';
const LEGACY_COL_WIDTHS_KEY = 'roomAssignment_colWidths';

export type ColWidths = typeof DEFAULT_COL_WIDTHS;

const loadColWidthsFor = (dateStr: string): ColWidths => {
  try {
    const raw = localStorage.getItem(COL_WIDTHS_STORAGE_KEY);
    if (raw) {
      const all = JSON.parse(raw) as Record<string, Partial<ColWidths>>;
      const existing = all[dateStr];
      if (existing) return { ...DEFAULT_COL_WIDTHS, ...existing };
    }
  } catch { /* ignore */ }
  return DEFAULT_COL_WIDTHS;
};

const saveColWidthsFor = (dateStr: string, widths: ColWidths): void => {
  try {
    const raw = localStorage.getItem(COL_WIDTHS_STORAGE_KEY);
    const all = raw ? JSON.parse(raw) : {};
    all[dateStr] = widths;
    localStorage.setItem(COL_WIDTHS_STORAGE_KEY, JSON.stringify(all));
  } catch { /* ignore */ }
};

// 캔버스로 텍스트 폭 측정 — DOM 안 건드리고 폰트 적용해 그렸다고 가정한 폭만 반환.
// MAX_NAME_WIDTH 로 캡 — 긴 이름(예: "FORTINA GUILLAUME") 이 컬럼 전체를 확장해
// 다른 컬럼(전화/파티/성별)이 좁아지는 문제 방지. 넘는 부분은 truncate 로 ... 표시.
const MAX_NAME_WIDTH = 120;
const measureMaxNameWidth = (rows: Reservation[]): number => {
  if (rows.length === 0) return 60;
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  if (!ctx) return 60;
  ctx.font = '500 14px ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
  let max = 60;
  for (const r of rows) {
    const text = `${r.customer_name || ''}${formatGuestSuffix(r)}`;
    if (!text) continue;
    const w = ctx.measureText(text).width;
    if (w > max) max = w;
  }
  return Math.min(Math.ceil(max) + 16, MAX_NAME_WIDTH);
};

const MIN_WIDTHS: Record<string, number> = { ...DEFAULT_COL_WIDTHS };

interface UseColumnResizeProps {
  selectedDate: Dayjs;
  reservations: Reservation[];
  nextDayReservations: Reservation[];
}

/**
 * 테이블 컬럼 폭 + 드래그 리사이즈 + 날짜별 localStorage 저장 + 이름 컬럼 캔버스 자동 측정.
 *
 * Phase D-1: RoomAssignment.tsx 의 colWidths 관련 로직 통합 (~150줄).
 */
export function useColumnResize({ selectedDate, reservations, nextDayReservations }: UseColumnResizeProps) {
  const [colWidths, setColWidths] = useState<ColWidths>(() => loadColWidthsFor(selectedDate.format('YYYY-MM-DD')));
  const [resizeCol, setResizeCol] = useState<string | null>(null);
  const [resizeGuideX, setResizeGuideX] = useState<number | null>(null);
  const [dateHeaderH, setDateHeaderH] = useState(0);

  const resizeStartXRef = useRef(0);
  const resizeStartWidthRef = useRef(0);
  const tableContainerRef = useRef<HTMLDivElement>(null);
  const dateHeaderRef = useRef<HTMLDivElement>(null);

  // 이름 컬럼 자동 너비 (오늘/내일 분리)
  const autoFitName = useMemo(() => measureMaxNameWidth(reservations), [reservations]);
  const autoFitNameNext = useMemo(() => measureMaxNameWidth(nextDayReservations), [nextDayReservations]);

  // 오늘은 사용자 드래그 값과 자동값 중 큰 쪽. 내일은 자체 자동값만.
  const effectiveNameWidth = Math.max(colWidths.name, autoFitName);
  const effectiveNameWidthNext = autoFitNameNext;

  const NEXT_DAY_EXPANDED_WIDTH = useMemo(() => {
    return 32 + effectiveNameWidthNext + DEFAULT_COL_WIDTHS.phone + DEFAULT_COL_WIDTHS.party + DEFAULT_COL_WIDTHS.gender + 16;
  }, [effectiveNameWidthNext]);

  const GUEST_COLS = useMemo(() => {
    return `${effectiveNameWidth}px ${colWidths.phone}px ${colWidths.party}px ${colWidths.gender}px ${colWidths.roomType}px ${colWidths.notes}px minmax(${colWidths.sms}px, 1fr)`;
  }, [colWidths, effectiveNameWidth]);

  const NEXT_GUEST_COLS = useMemo(() => {
    return `${effectiveNameWidthNext}px ${DEFAULT_COL_WIDTHS.phone}px ${DEFAULT_COL_WIDTHS.party}px ${DEFAULT_COL_WIDTHS.gender}px`;
  }, [effectiveNameWidthNext]);

  // 마운트 시 옛 전역 키 정리
  useEffect(() => {
    try { localStorage.removeItem(LEGACY_COL_WIDTHS_KEY); } catch { /* ignore */ }
  }, []);

  // 날짜 전환 시 그 날짜의 저장값 재로드
  useEffect(() => {
    setColWidths(loadColWidthsFor(selectedDate.format('YYYY-MM-DD')));
  }, [selectedDate]);

  // 날짜 헤더 높이 측정 → sticky top 좌표 계산용
  useEffect(() => {
    if (!dateHeaderRef.current) return;
    const ro = new ResizeObserver(([entry]) => setDateHeaderH(entry.contentRect.height));
    ro.observe(dateHeaderRef.current);
    setDateHeaderH(dateHeaderRef.current.offsetHeight);
    return () => ro.disconnect();
  }, []);

  // 드래그 라이프사이클: mousemove + mouseup 글로벌 리스너
  useEffect(() => {
    if (!resizeCol) return;

    const handleMouseMove = (e: MouseEvent) => {
      const delta = e.clientX - resizeStartXRef.current;
      const effectiveMin = resizeCol === 'name'
        ? Math.max(MIN_WIDTHS.name, autoFitName)
        : (MIN_WIDTHS[resizeCol] || 30);
      const newWidth = Math.max(effectiveMin, resizeStartWidthRef.current + delta);
      setColWidths((prev) => ({ ...prev, [resizeCol]: newWidth }));
      if (tableContainerRef.current) {
        const clampedDelta = newWidth - resizeStartWidthRef.current;
        const clampedX = resizeStartXRef.current + clampedDelta;
        const rect = tableContainerRef.current.getBoundingClientRect();
        setResizeGuideX(clampedX - rect.left);
      }
    };

    const handleMouseUp = () => {
      setResizeCol(null);
      setResizeGuideX(null);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      // 드래그 완료 시점에 현재 날짜의 슬롯에만 저장
      setColWidths((curr) => {
        saveColWidthsFor(selectedDate.format('YYYY-MM-DD'), curr);
        return curr;
      });
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [resizeCol, selectedDate, autoFitName]);

  // 헤더 핸들이 호출 — 드래그 시작 시점의 ref 셋업 + resizeCol 설정.
  const startResize = useCallback((col: keyof ColWidths, e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    resizeStartXRef.current = e.clientX;
    resizeStartWidthRef.current = col === 'name' ? effectiveNameWidth : colWidths[col];
    setResizeCol(col);
  }, [colWidths, effectiveNameWidth]);

  return {
    colWidths,
    resizeGuideX,
    dateHeaderH,
    effectiveNameWidth,
    effectiveNameWidthNext,
    GUEST_COLS,
    NEXT_GUEST_COLS,
    NEXT_DAY_EXPANDED_WIDTH,
    tableContainerRef,
    dateHeaderRef,
    startResize,
  };
}
