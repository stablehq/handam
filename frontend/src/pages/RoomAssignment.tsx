import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import api, { reservationsAPI, roomsAPI, templatesAPI, smsAssignmentsAPI, stayGroupAPI, settingsAPI } from '../services/api';
import { useTenantStore } from '@/stores/tenant-store';
import dayjs, { Dayjs } from 'dayjs';
import { toast } from 'sonner';
import { Tooltip } from '@/components/ui/tooltip';
import { Modal, ModalHeader, ModalBody, ModalFooter } from '@/components/ui/modal';
import { TextInput } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import { Spinner } from '@/components/ui/spinner';
import { Button } from '@/components/ui/button';
import {
  Send,
  RefreshCw,
  X,
  BedDouble,
  Trash2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Plus,
  UserRoundPlus,
  UserPlus,
  Link2,
  Layers,
  Circle,
  Minus,
  PanelRightOpen,
  PanelRightClose,
  ChevronsLeft,
  ChevronsRight,
} from 'lucide-react';
import GuestContextMenu from '../components/GuestContextMenu';
import TableSettingsModal from '../components/TableSettingsModal';

import {
  PRESET_HIGHLIGHT_STYLES,
  isCustomHexColor,
  getCustomBgStyle,
  getCustomTextClass,
  loadRowColors,
  saveRowColors,
  type RowColorSettings,
} from '@/lib/highlight-colors';

interface SmsAssignment {
  id: number;
  reservation_id: number;
  template_key: string;
  assigned_at: string;
  sent_at: string | null;
  assigned_by: string;
  date: string;
}

interface Reservation {
  id: number;
  customer_name: string;
  phone: string;
  check_in_date: string;
  check_in_time: string;
  status: string;
  room_id: number | null;
  room_number: string | null;
  room_password: string | null;
  room_assigned_by: string | null;
  naver_room_type: string | null;
  section: string;  // 'room', 'unassigned', 'party', 'unstable'
  unstable_party?: boolean;
  gender: string | null;
  male_count: number | null;
  female_count: number | null;
  party_size: number | null;
  party_type: string | null;  // '1'=1차만, '2'=1+2차, '2차만'
  notes: string | null;
  check_out_date: string | null;
  booking_source?: string;
  sms_assignments: SmsAssignment[];
  stay_group_id?: string | null;
  stay_group_order?: number | null;
  is_long_stay?: boolean;
  bed_order?: number;
  highlight_color?: string | null;
  has_unstable_booking?: boolean;
}



function formatGenderPeople(res: Reservation): string {
  const m = res.male_count || 0;
  const f = res.female_count || 0;
  if (m > 0 && f > 0) return `남${m}여${f}`;
  if (m > 0) return `남${m}`;
  if (f > 0) return `여${f}`;
  // Fallback: gender 문자열에서 숫자 파싱
  if (res.gender) {
    const maleMatch = res.gender.match(/남(\d+)/);
    const femaleMatch = res.gender.match(/여(\d+)/);
    if (maleMatch || femaleMatch) {
      const parts: string[] = [];
      if (maleMatch) parts.push(`남${maleMatch[1]}`);
      if (femaleMatch) parts.push(`여${femaleMatch[1]}`);
      return parts.join('');
    }
    // 단순 "남" or "여"
    if (res.gender === '남' || res.gender === '여') {
      return `${res.gender}${res.party_size || 1}`;
    }
  }
  return '';
}

interface SmsCellProps {
  reservation: Reservation;
  templateLabels: {template_key: string; name: string; short_label: string | null}[];
  selectedDate: string;
  onToggle: (resId: number, templateKey: string) => void;
  onAssign: (resId: number, templateKey: string) => void;
  onRemove: (resId: number, templateKey: string) => void;
}

const SmsCell: React.FC<SmsCellProps> = ({ reservation, templateLabels, selectedDate, onToggle, onAssign, onRemove }) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [showArrows, setShowArrows] = useState(false);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [dropdownPos, setDropdownPos] = useState<{ top?: number; bottom?: number; right: number }>({ right: 0 });
  const dropdownRef = useRef<HTMLDivElement>(null);
  const dropdownMenuRef = useRef<HTMLDivElement>(null);
  const buttonRectRef = useRef<DOMRect | null>(null);

  // Deduplicate by template_key: prefer today's chip, fallback to most recent sent chip
  const assignments = (() => {
    const raw = reservation.sms_assignments || [];
    const byKey = new Map<string, typeof raw[0]>();
    for (const a of raw) {
      const existing = byKey.get(a.template_key);
      if (!existing) {
        byKey.set(a.template_key, a);
      } else {
        // Prefer unsent (today's) over sent (past), or newer date
        if (!a.sent_at && existing.sent_at) {
          byKey.set(a.template_key, a);
        } else if (a.date > (existing.date || '')) {
          byKey.set(a.template_key, a);
        }
      }
    }
    return [...byKey.values()].sort((a, b) => {
      const ai = templateLabels.findIndex(t => t.template_key === a.template_key);
      const bi = templateLabels.findIndex(t => t.template_key === b.template_key);
      return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
    });
  })();

  const checkScroll = useCallback(() => {
    if (scrollRef.current) {
      const { scrollLeft, scrollWidth, clientWidth } = scrollRef.current;
      setShowArrows(scrollWidth > clientWidth);
      setCanScrollLeft(scrollLeft > 0);
      setCanScrollRight(scrollLeft < scrollWidth - clientWidth - 1);
    }
  }, []);

  useEffect(() => {
    checkScroll();
    const handleResize = () => checkScroll();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [checkScroll, assignments]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    if (dropdownOpen) {
      document.addEventListener('mousedown', handler);
      return () => document.removeEventListener('mousedown', handler);
    }
  }, [dropdownOpen]);

  // 드롭다운 실제 높이 측정 후 뷰포트 밖이면 위로 재배치
  useEffect(() => {
    if (dropdownOpen && dropdownMenuRef.current && buttonRectRef.current) {
      const menuRect = dropdownMenuRef.current.getBoundingClientRect();
      const rect = buttonRectRef.current;
      if (menuRect.bottom > window.innerHeight) {
        setDropdownPos({ bottom: window.innerHeight - rect.top + 4, right: window.innerWidth - rect.right });
      }
    }
  }, [dropdownOpen]);

  const scroll = (direction: 'left' | 'right') => {
    if (scrollRef.current) {
      scrollRef.current.scrollBy({ left: direction === 'left' ? -100 : 100, behavior: 'smooth' });
      setTimeout(checkScroll, 300);
    }
  };

  const getLabel = (key: string) => {
    const tpl = templateLabels.find(t => t.template_key === key);
    return tpl?.short_label || tpl?.name || key;
  };

  const getFullName = (key: string) => {
    const tpl = templateLabels.find(t => t.template_key === key);
    return tpl?.name || key;
  };

  const isAssigned = (key: string) => assignments.some(a => a.template_key === key);

  const isSentTemplate = (key: string) => !!assignments.find(a => a.template_key === key)?.sent_at;

  const handleDropdownToggle = (key: string) => {
    if (isSentTemplate(key)) return; // 발송완료된 항목은 해제 불가
    if (isAssigned(key)) {
      onRemove(reservation.id, key);
    } else {
      onAssign(reservation.id, key);
    }
  };

  return (
    <div className="relative flex items-center h-8">
      <div
        ref={scrollRef}
        onScroll={checkScroll}
        className="overflow-x-auto overflow-y-hidden flex items-center min-w-0 scrollbar-none"
      >
        <div className="flex items-center gap-1 flex-nowrap">
          {assignments.map((a) => {
            const isSent = !!a.sent_at;
            const isPastChip = isSent && a.date < selectedDate;
            return (
              <span
                key={a.template_key}
                title={isPastChip ? `${getFullName(a.template_key)} (${a.date} 발송완료)` : getFullName(a.template_key)}
                className={`inline-flex items-center px-1.5 py-1 rounded text-[11px] leading-tight font-medium whitespace-nowrap cursor-pointer transition-all
                  ${isSent
                    ? 'bg-[#E8F3FF] text-[#3182F6] border border-[#3182F6]/30 dark:bg-[#3182F6]/20 dark:text-[#3182F6] dark:border-[#3182F6]/30'
                    : 'bg-[#F2F4F6] text-[#8B95A1] border border-[#E5E8EB] dark:bg-[#2C2C34] dark:text-[#8B95A1] dark:border-[#2C2C34]'
                  }`}
                onClick={(e) => { e.stopPropagation(); onToggle(reservation.id, a.template_key); }}
              >
                {getLabel(a.template_key)}
              </span>
            );
          })}
          {assignments.length === 0 && (
            <span className="text-[#B0B8C1] dark:text-[#8B95A1] text-caption">-</span>
          )}
        </div>
      </div>
      {/* + button with checklist dropdown */}
      <div className="relative flex-shrink-0 ml-1" ref={dropdownRef}>
        <button
          onClick={(e) => {
            e.stopPropagation();
            if (!dropdownOpen) {
              const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
              buttonRectRef.current = rect;
              // 일단 아래로 열고, useEffect에서 실제 높이 측정 후 재배치
              setDropdownPos({ top: rect.bottom + 4, right: window.innerWidth - rect.right });
            }
            setDropdownOpen(!dropdownOpen);
          }}
          className="inline-flex items-center justify-center w-[18px] h-[18px] rounded border border-dashed border-[#E5E8EB] dark:border-[#2C2C34] text-[#B0B8C1] dark:text-[#8B95A1] hover:border-[#3182F6] hover:text-[#3182F6] dark:hover:border-[#3182F6] dark:hover:text-[#3182F6] transition-colors cursor-pointer"
          title="문자 템플릿 관리"
        >
          <Plus size={10} />
        </button>
        {dropdownOpen && templateLabels.length > 0 && (
          <div
            ref={dropdownMenuRef}
            className="fixed z-[60] w-max rounded-lg border border-[#E5E8EB] dark:border-[#2C2C34] bg-white dark:bg-[#1E1E24] shadow-lg py-1"
            style={{ top: dropdownPos.top, bottom: dropdownPos.bottom, right: dropdownPos.right }}
          >
            {templateLabels.map(t => {
              const assigned = isAssigned(t.template_key);
              const sent = assignments.find(a => a.template_key === t.template_key)?.sent_at;
              return (
                <button
                  key={t.template_key}
                  className={`w-full flex items-center gap-2 px-3 py-1.5 text-caption transition-colors ${
                    sent ? 'opacity-60 cursor-not-allowed' : 'hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34] cursor-pointer'
                  }`}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDropdownToggle(t.template_key);
                  }}
                >
                  <span className={`flex items-center justify-center w-3.5 h-3.5 rounded border transition-colors ${
                    assigned
                      ? 'bg-[#3182F6] border-[#3182F6] text-white'
                      : 'border-[#E5E8EB] dark:border-[#4E5968]'
                  }`}>
                    {assigned && <span className="text-[9px] font-bold">✓</span>}
                  </span>
                  <span className={`flex items-center gap-1.5 ${assigned ? 'text-[#191F28] dark:text-white' : 'text-[#8B95A1] dark:text-[#4E5968]'}`}>
                    <span className={`font-medium ${sent ? 'line-through text-[#8B95A1] dark:text-[#4E5968]' : ''}`}>
                      {t.short_label ? (
                        <>{t.short_label} <span className="text-[#8B95A1] dark:text-[#4E5968] font-normal">({t.name})</span></>
                      ) : t.name}
                    </span>
                    {sent && <span className="text-[9px] text-[#3182F6] font-medium">발송완료</span>}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

const InlineInput = ({ value, field, resId, className, placeholder, onSave, autoFocus, disabled }: {
  value: string;
  field: string;
  resId: number;
  className?: string;
  placeholder?: string;
  onSave: (resId: number, field: string, value: string) => void;
  autoFocus?: boolean;
  disabled?: boolean;
}) => {
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

interface ConfirmState {
  open: boolean;
  title: string;
  content: string;
  onOk: () => void;
}

const RoomAssignment = () => {
  const { tenants, currentTenantId } = useTenantStore();
  const currentTenant = tenants.find(t => String(t.id) === currentTenantId);
  const hasUnstable = currentTenant?.has_unstable ?? false;

  const [selectedDate, setSelectedDate] = useState<Dayjs>(dayjs());
  const [reservations, setReservations] = useState<Reservation[]>([]);
  // Track which section unassigned reservations belong to: 'party' or 'unassigned'
  const [sectionOverrides, setSectionOverrides] = useState<Record<number, 'party' | 'unassigned'>>({});
  const [nextDayReservations, setNextDayReservations] = useState<Reservation[]>([]);
  const [nextDayExpanded, setNextDayExpanded] = useState(() => {
    const saved = localStorage.getItem('roomAssignment_nextDayExpanded');
    return saved !== null ? saved === 'true' : true;
  });
  const [rooms, setRooms] = useState<any[]>([]);
  const [animDirection, setAnimDirection] = useState<'none' | 'left' | 'right'>('none');
  const [loading, setLoading] = useState(false);
  const [dragOverRoom, setDragOverRoom] = useState<number | null>(null);
  const [dragOverNextRoom, setDragOverNextRoom] = useState<number | null>(null);
  const [dragOverPool, setDragOverPool] = useState(false);
  const [dragOverPartyZone, setDragOverPartyZone] = useState(false);
  const [dragOverNextPool, setDragOverNextPool] = useState(false);
  const [dragOverNextParty, setDragOverNextParty] = useState(false);

  // ===== Select mode state =====
  const [selectedGuestIds, setSelectedGuestIds] = useState<Set<number>>(new Set());
  const selectionActive = selectedGuestIds.size > 0;

  // Selection mode toast
  useEffect(() => {
    localStorage.setItem('roomAssignment_nextDayExpanded', String(nextDayExpanded));
  }, [nextDayExpanded]);

  useEffect(() => {
    const TOAST_ID = 'selection-mode';
    if (selectionActive) {
      const name = selectedGuestIds.size === 1
        ? reservations.find(r => r.id === [...selectedGuestIds][0])?.customer_name
        : undefined;
      const msg = name
        ? `${name} — 이동할 방을 클릭하세요`
        : `${selectedGuestIds.size}명 선택됨 — 이동할 방을 클릭하세요`;
      toast.info(msg, {
        id: TOAST_ID,
        duration: Infinity,
        position: 'top-center',
        action: {
          label: '✕ 취소',
          onClick: () => setSelectedGuestIds(new Set()),
        },
      });
    } else {
      toast.dismiss(TOAST_ID);
    }
  }, [selectionActive, selectedGuestIds, reservations]);

  // Undo stack for room assignments
  const [undoStack, setUndoStack] = useState<Array<{ resId: number; prevRoomId: number | null; prevRoomNumber: string | null; prevSection: string | null; date: string; customerName: string }>>([]);
  const undoInProgress = useRef(false);

  const [recentlyMovedId, setRecentlyMovedId] = useState<number | null>(null);
  const [processing, setProcessing] = useState(false);
  const [quickAddedId, setQuickAddedId] = useState<number | null>(null);
  const [collapsedBuildings, setCollapsedBuildings] = useState<Set<number | null>>(new Set());

  // ===== Context menu state =====
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; targetIds: number[]; zone?: string } | null>(null);

  const [modalVisible, setModalVisible] = useState(false);
  const [savingReservation, setSavingReservation] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formValues, setFormValues] = useState<any>({
    guest_type: 'party_only',
    customer_name: '',
    phone: '',
    date: '',
    time: '18:00',
    gender: '',
    party_size: 1,
    naver_room_type: '',
    notes: '',
    status: 'confirmed',
    booking_source: 'manual',
  });

  const [confirmState, setConfirmState] = useState<ConfirmState>({
    open: false,
    title: '',
    content: '',
    onOk: () => {},
  });

  const showConfirm = (title: string, content: string, onOk: () => void) => {
    setConfirmState({ open: true, title, content, onOk });
  };

  const [multiNightConfirm, setMultiNightConfirm] = useState<{
    open: boolean;
    resId: number;
    resName: string;
    roomId: number;
    roomNumber: string;
    onConfirm: (applySubsequent: boolean) => void;
  } | null>(null);

  const [extendStayConflict, setExtendStayConflict] = useState<{
    open: boolean;
    newResId: number;
    roomId: number;
    roomNumber: string;
    existingGuests: string[];
  } | null>(null);

  const [dateChangeModal, setDateChangeModal] = useState<{
    open: boolean;
    resId: number;
    customerName: string;
    checkIn: string;
    checkOut: string;
  } | null>(null);

  const [templateLabels, setTemplateLabels] = useState<{template_key: string; name: string; short_label: string | null}[]>([]);

  const [roomGroups, setRoomGroups] = useState<Array<{id: number; name: string; sort_order: number; color?: string; room_ids: number[]}>>([]);
  const [tableSettingsOpen, setTableSettingsOpen] = useState(false);
  const [customHighlightColors, setCustomHighlightColors] = useState<string[]>([]);
  const [rowColors, setRowColors] = useState<RowColorSettings>(loadRowColors);
  const [isDarkMode, setIsDarkMode] = useState(() => document.documentElement.classList.contains('dark'));

  const [showStayGroupModal, setShowStayGroupModal] = useState(false);


  const [stayGroupChain, setStayGroupChain] = useState<Array<{id: number; customer_name: string; phone: string; check_in_date: string; check_out_date: string; stay_group_id?: string | null}>>([]);
  const [stayGroupDateReservations, setStayGroupDateReservations] = useState<any[]>([]);
  const [stayGroupSelectedId, setStayGroupSelectedId] = useState<number | null>(null);
  const [stayGroupLoading, setStayGroupLoading] = useState(false);
  const [stayGroupLinking, setStayGroupLinking] = useState(false);
  const [stayGroupDirection, setStayGroupDirection] = useState<'left' | 'right'>('right');

  const handleFieldSave = async (resId: number, field: string, value: string, targetDate?: Dayjs) => {
    const effectiveDate = targetDate || selectedDate;
    if (field === 'party_type') {
      try {
        await reservationsAPI.updateDailyInfo(resId, { date: effectiveDate.format('YYYY-MM-DD'), party_type: value || null });
        fetchReservations(selectedDate);
      } catch {
        toast.error('저장 실패');
      }
      return;
    }
    if (field === 'notes') {
      try {
        await reservationsAPI.updateDailyInfo(resId, { date: effectiveDate.format('YYYY-MM-DD'), notes: value });
        fetchReservations(selectedDate);
      } catch {
        toast.error('저장 실패');
      }
      return;
    }
    try {
      if (field === 'genderPeople') {
        // Parse mixed gender format: "남1여1", "남2", "여3", "남1", etc.
        const maleMatch = (value || '').match(/남(\d+)/);
        const femaleMatch = (value || '').match(/여(\d+)/);
        const male_count = maleMatch ? Number(maleMatch[1]) : 0;
        const female_count = femaleMatch ? Number(femaleMatch[1]) : 0;
        // Also update party_size as total
        const total = male_count + female_count;
        const gender = male_count > 0 && female_count > 0 ? '혼성' : male_count > 0 ? '남' : female_count > 0 ? '여' : null;
        await reservationsAPI.update(resId, { male_count, female_count, gender, party_size: total || null });
      } else {
        await reservationsAPI.update(resId, { [field]: value });
      }
      fetchReservations(selectedDate);
    } catch {
      toast.error('저장 실패');
    }
  };


  const defaultColWidths = { name: 60, phone: 120, party: 60, gender: 60, roomType: 100, notes: 100, sms: 140, nextDay: 96 };
  const [colWidths, setColWidths] = useState(() => {
    try {
      const saved = localStorage.getItem('roomAssignment_colWidths');
      if (saved) return { ...defaultColWidths, ...JSON.parse(saved) };
    } catch { /* ignore */ }
    return defaultColWidths;
  });
  const NEXT_DAY_EXPANDED_WIDTH = useMemo(() => {
    return 32 + colWidths.name + colWidths.phone + colWidths.party + colWidths.gender + 16;
  }, [colWidths]);
  const [resizeCol, setResizeCol] = useState<string | null>(null);
  const [resizeGuideX, setResizeGuideX] = useState<number | null>(null);
  const resizeStartXRef = useRef(0);
  const resizeStartWidthRef = useRef(0);
  const tableContainerRef = useRef<HTMLDivElement>(null);
  const dateHeaderRef = useRef<HTMLDivElement>(null);
  const [dateHeaderH, setDateHeaderH] = useState(0);

  useEffect(() => {
    localStorage.setItem('roomAssignment_colWidths', JSON.stringify(colWidths));
  }, [colWidths]);

  // Load custom highlight colors from tenant settings
  useEffect(() => {
    settingsAPI.getHighlightColors().then(res => {
      setCustomHighlightColors(res.data.colors || []);
    }).catch(() => { /* ignore */ });
  }, []);

  // Dark mode detection for custom highlight inline styles
  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDarkMode(document.documentElement.classList.contains('dark'));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  // 날짜 헤더 높이 측정 → 테이블 헤더 sticky top 계산
  useEffect(() => {
    if (!dateHeaderRef.current) return;
    const ro = new ResizeObserver(([entry]) => setDateHeaderH(entry.contentRect.height));
    ro.observe(dateHeaderRef.current);
    setDateHeaderH(dateHeaderRef.current.offsetHeight);
    return () => ro.disconnect();
  }, []);

  const GUEST_COLS = useMemo(() => {
    return `${colWidths.name}px ${colWidths.phone}px ${colWidths.party}px ${colWidths.gender}px ${colWidths.roomType}px ${colWidths.notes}px minmax(${colWidths.sms}px, 1fr)`;
  }, [colWidths]);

  const NEXT_GUEST_COLS = useMemo(() => {
    return `${colWidths.name}px ${colWidths.phone}px ${colWidths.party}px ${colWidths.gender}px`;
  }, [colWidths]);

  const roomInfoMap = useMemo(() => {
    const map: Record<string, string> = {};
    rooms.forEach((room) => {
      map[room.room_number] = room.room_type;
    });
    return map;
  }, [rooms]);

  const activeRoomEntries = useMemo(() => {
    return rooms.filter((room) => room.active).map((room) => ({
      room_id: room.id as number,
      room_number: room.room_number as string,
      isDormitory: room.dormitory || false,
      bed_capacity: room.bed_capacity || 1,
      building_id: room.building_id as number | null,
      building_name: room.building_name as string | null,
    }));
  }, [rooms]);

  const nextDayRoomMap = useMemo(() => {
    const map = new Map<number, Reservation[]>();
    nextDayReservations.forEach((r) => {
      if (r.room_id) {
        const existing = map.get(r.room_id) || [];
        existing.push(r);
        map.set(r.room_id, existing);
      }
    });
    return map;
  }, [nextDayReservations]);


  const roomGroupMap = useMemo(() => {
    const map = new Map<number, { group_id: number; groupIndex: number; isFirst: boolean; isLast: boolean }>();
    for (let gi = 0; gi < roomGroups.length; gi++) {
      const group = roomGroups[gi];
      // Find positions of group rooms within activeRoomEntries order
      const orderedIds = activeRoomEntries
        .map((e) => e.room_id)
        .filter((id) => group.room_ids.includes(id));
      orderedIds.forEach((roomId, idx) => {
        map.set(roomId, {
          group_id: group.id,
          groupIndex: gi,
          isFirst: idx === 0,
          isLast: idx === orderedIds.length - 1,
        });
      });
    }
    return map;
  }, [roomGroups, activeRoomEntries]);

  const [selectedTemplateKey, setSelectedTemplateKey] = useState<string | null>(null);
  const [campaignDropdownOpen, setCampaignDropdownOpen] = useState(false);
  const campaignDropdownRef = useRef<HTMLDivElement>(null);
  const [targets, setTargets] = useState<Reservation[]>([]);
  const [sending, setSending] = useState(false);
  const [sendConfirm, setSendConfirm] = useState<{ type: 'campaign' | 'toggle'; resId?: number; templateKey?: string; customerName?: string; templateName?: string } | null>(null);
  const [autoAssignConfirm, setAutoAssignConfirm] = useState(false);
  const [autoAssigning, setAutoAssigning] = useState(false);

  const handleAutoAssign = useCallback(async () => {
    setAutoAssigning(true);
    try {
      const dateStr = selectedDate.format('YYYY-MM-DD');
      const res = await roomsAPI.autoAssign(dateStr);
      const today = res.data.today;
      toast.success(`객실 자동 배정 완료: ${today.assigned}건 배정`);
      fetchReservations(selectedDate);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || '객실 자동 배정에 실패했습니다.');
    } finally {
      setAutoAssigning(false);
      setAutoAssignConfirm(false);
    }
  }, [selectedDate]);

  const fetchRoomGroups = useCallback(async () => {
    try {
      const res = await roomsAPI.getGroups();
      setRoomGroups(res.data);
    } catch {
      // silently ignore group fetch failures
    }
  }, []);

  const fetchRooms = useCallback(async () => {
    try {
      const res = await roomsAPI.getAll();
      setRooms(res.data);
    } catch {
      toast.error('객실 목록을 불러오지 못했습니다.');
    }
  }, []);

  // 날짜 이동 방향 추적 (프리페치용)
  const prevDateRef = useRef<Dayjs>(selectedDate);
  const reservationsRef = useRef<Reservation[]>([]);
  const nextDayRef = useRef<Reservation[]>([]);

  const filterActive = useCallback((data: any[]) =>
    data.filter((r: Reservation) => r.status !== 'cancelled'), []);

  const fetchReservations = useCallback(async (date: Dayjs) => {
    setLoading(true);
    try {
      const dateStr = date.format('YYYY-MM-DD');

      // 당일 먼저 로딩
      const current = await reservationsAPI.getAll({ date: dateStr, limit: 200 });
      const curr = filterActive(current.data.items ?? current.data);
      setReservations(curr);
      reservationsRef.current = curr;
      prevDateRef.current = date;
      setLoading(false);

      // 다음날 백그라운드 fetch
      reservationsAPI.getAll({ date: date.add(1, 'day').format('YYYY-MM-DD'), limit: 200 })
        .then(res => { const d = filterActive(res.data.items ?? res.data); setNextDayReservations(d); nextDayRef.current = d; })
        .catch(() => { setNextDayReservations([]); nextDayRef.current = []; });
    } catch {
      toast.error('예약 목록을 불러오지 못했습니다.');
      setLoading(false);
    }
  }, [filterActive]);

  useEffect(() => {
    fetchRooms();
    fetchRoomGroups();
  }, [fetchRooms, fetchRoomGroups]);

  useEffect(() => {
    templatesAPI.getLabels().then(res => setTemplateLabels(res.data)).catch(() => {});
  }, []);

  useEffect(() => {
    fetchReservations(selectedDate);
    setTargets([]);
  }, [selectedDate, fetchReservations]);

  // SSE: 스케줄 발송 완료 시 예약 목록 자동 새로고침
  useEffect(() => {
    const token = localStorage.getItem('sms-token') || '';
    const tenantId = localStorage.getItem('sms-tenant-id') || '';
    const es = new EventSource(`/api/events/stream?token=${encodeURIComponent(token)}&tenant_id=${tenantId}`);
    es.onmessage = (e) => {
      try {
        const { event } = JSON.parse(e.data);
        if (event === 'schedule_complete') {
          fetchReservations(selectedDate);
        }
      } catch {
        // malformed payload, ignore
      }
    };
    return () => es.close();
  }, [selectedDate, fetchReservations]);

  useEffect(() => {
    if (!resizeCol) return;

    const handleMouseMove = (e: MouseEvent) => {
      const delta = e.clientX - resizeStartXRef.current;
      const minWidths: Record<string, number> = { name: 60, phone: 120, party: 60, gender: 60, roomType: 100, notes: 100, sms: 140, nextDay: 96 };
      const newWidth = Math.max(minWidths[resizeCol] || 30, resizeStartWidthRef.current + delta);
      setColWidths((prev: typeof defaultColWidths) => ({ ...prev, [resizeCol!]: newWidth }));
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
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [resizeCol]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (campaignDropdownRef.current && !campaignDropdownRef.current.contains(e.target as Node)) {
        setCampaignDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    if (quickAddedId) {
      const timer = setTimeout(() => setQuickAddedId(null), 500);
      return () => clearTimeout(timer);
    }
  }, [quickAddedId]);

  // Select mode: reset on date change
  useEffect(() => {
    setSelectedGuestIds(new Set());
  }, [selectedDate]);

  // Select mode: prune invalid IDs on reservations change
  useEffect(() => {
    setSelectedGuestIds(prev => {
      const validIds = new Set([
        ...reservations.map(r => r.id),
        ...nextDayReservations.map(r => r.id),
      ]);
      const next = new Set([...prev].filter(id => validIds.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [reservations, nextDayReservations]);

  // Keyboard shortcuts: ESC to clear selection, Ctrl+Z to undo room assignment
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedGuestIds(new Set());
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
        e.preventDefault();
        if (undoInProgress.current) return;
        undoInProgress.current = true;
        setUndoStack(prev => {
          if (prev.length === 0) { undoInProgress.current = false; return prev; }
          const last = prev[prev.length - 1];
          // Restore previous room assignment
          reservationsAPI.assignRoom(last.resId, {
            room_id: last.prevRoomId,
            date: last.date,
            apply_subsequent: false,
          }).then(async () => {
            if (last.prevRoomId === null && last.prevSection) {
              await reservationsAPI.update(last.resId, { section: last.prevSection });
            }
            toast.success(`되돌리기: ${last.customerName} → ${last.prevRoomId ? last.prevRoomNumber : '미배정'}`);
            fetchReservations(selectedDate);
          }).catch(() => {
            toast.error('되돌리기 실패');
          }).finally(() => {
            undoInProgress.current = false;
          });
          return prev.slice(0, -1);
        });
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [selectedDate, fetchReservations]);


  const loadTargets = () => {
    if (!selectedTemplateKey) {
      toast.warning('템플릿을 선택하세요');
      return;
    }
    const unsent = reservations.filter(r =>
      r.sms_assignments?.some(a => a.template_key === selectedTemplateKey && !a.sent_at)
    );
    setTargets(unsent);
    if (unsent.length === 0) {
      toast.info('미발송 대상이 없습니다');
    }
  };

  const requestSendCampaign = () => {
    if (!selectedTemplateKey || targets.length === 0) {
      toast.warning('발송 대상이 없습니다');
      return;
    }
    setSendConfirm({ type: 'campaign' });
  };

  const handleSendCampaign = async () => {
    if (!selectedTemplateKey || targets.length === 0) return;
    const tpl = templateLabels.find(t => t.template_key === selectedTemplateKey);
    setSendConfirm(null);
    setSending(true);
    try {
      const response = await api.post('/api/reservations/sms-send-by-tag', {
        template_key: selectedTemplateKey,
        date: selectedDate.format('YYYY-MM-DD'),
      });
      const data = response.data;
      if (data.success) {
        toast.success(`${tpl?.name || selectedTemplateKey} 발송 완료: ${data.sent_count}건`);
        setTargets([]);
        fetchReservations(selectedDate);
      } else {
        toast.error(`발송 실패: ${data.error || '알 수 없는 오류'}`);
      }
    } catch {
      toast.error('발송 실패');
    } finally {
      setSending(false);
    }
  };


  const { assignedRooms, unassigned, partyOnly, unstableGuests } = useMemo(() => {
    const assigned = new Map<number, Reservation[]>();
    const unassignedList: Reservation[] = [];
    const partyOnlyList: Reservation[] = [];
    const unstableList: Reservation[] = [];

    reservations.forEach((res) => {
      if (res.room_id) {
        // Has a room assigned → goes to that room's row
        const list = assigned.get(res.room_id) || [];
        list.push(res);
        assigned.set(res.room_id, list);
      } else if (sectionOverrides[res.id] === 'party' || (sectionOverrides[res.id] === undefined && res.section === 'party')) {
        partyOnlyList.push(res);
      } else if (res.section === 'unstable') {
        // 순수 언스테이블 네이버 예약자
        unstableList.push(res);
      } else {
        unassignedList.push(res);
      }
    });

    // 스테이블 예약자 중 unstable_party=true인 경우 → 언스테이블 행에 복사본 추가
    reservations.forEach((res) => {
      if (res.section !== 'unstable' && res.unstable_party) {
        unstableList.push({ ...res, _isCopied: true } as Reservation & { _isCopied?: boolean });
      }
    });

    // 최근 이동한 게스트를 맨 위로
    if (recentlyMovedId !== null) {
      const bumpToTop = (list: Reservation[]) => {
        const idx = list.findIndex(r => r.id === recentlyMovedId);
        if (idx > 0) {
          const [item] = list.splice(idx, 1);
          list.unshift(item);
        }
      };
      bumpToTop(unassignedList);
      bumpToTop(partyOnlyList);
    }

    return {
      assignedRooms: assigned,
      unassigned: unassignedList,
      partyOnly: partyOnlyList,
      unstableGuests: unstableList,
    };
  }, [reservations, sectionOverrides]);

  const nextDayUnassigned = useMemo(() =>
    nextDayReservations.filter(r => !r.room_id && (r.section === 'unassigned' || !r.section)),
    [nextDayReservations]
  );

  const nextDayPartyOnly = useMemo(() =>
    nextDayReservations.filter(r => !r.room_id && r.section === 'party'),
    [nextDayReservations]
  );

  const findReservation = useCallback(
    (resId: number): { res: Reservation; isNextDay: boolean } | null => {
      const today = reservations.find((r) => r.id === resId);
      if (today) return { res: today, isNextDay: false };
      const tomorrow = nextDayReservations.find((r) => r.id === resId);
      if (tomorrow) return { res: tomorrow, isNextDay: true };
      return null;
    },
    [reservations, nextDayReservations]
  );

  // Group rooms by building for fold/unfold
  const buildingGroups = useMemo(() => {
    const groups: { building_id: number | null; building_name: string | null; entries: typeof activeRoomEntries; assignedCount: number; totalCount: number }[] = [];
    let currentBuildingId: number | null | undefined = undefined;
    let currentGroup: typeof groups[0] | null = null;

    activeRoomEntries.forEach((entry) => {
      if (entry.building_id !== currentBuildingId) {
        currentBuildingId = entry.building_id;
        currentGroup = {
          building_id: entry.building_id,
          building_name: entry.building_name,
          entries: [],
          assignedCount: 0,
          totalCount: 0,
        };
        groups.push(currentGroup);
      }
      currentGroup!.entries.push(entry);
      currentGroup!.totalCount++;
      if ((assignedRooms.get(entry.room_id) || []).length > 0) {
        currentGroup!.assignedCount++;
      }
    });

    return groups;
  }, [activeRoomEntries, assignedRooms]);

  const toggleBuildingCollapse = useCallback((buildingId: number | null) => {
    setCollapsedBuildings((prev) => {
      const next = new Set(prev);
      if (next.has(buildingId)) next.delete(buildingId);
      else next.add(buildingId);
      return next;
    });
  }, []);

  // --- 드롭 액션 (기존 onXxxDrop 비즈니스 로직 보존) ---
  const handleDropOnRoom = (resId: number, roomId: number, dropTargetDate?: Dayjs) => {
    const found = findReservation(resId);
    if (!found) return;
    const { res, isNextDay: sourceIsNextDay } = found;
    const targetDate = dropTargetDate || selectedDate;
    const dropIsNextDay = !targetDate.isSame(selectedDate, 'day');

    // Duplicate check on correct list
    const currentList = dropIsNextDay
      ? (nextDayRoomMap.get(roomId) || [])
      : (assignedRooms.get(roomId) || []);
    if (currentList.some((r) => r.id === resId)) return;

    const entry = activeRoomEntries.find((e) => e.room_id === roomId);

    // Cross-day move: change reservation date + room
    if (sourceIsNextDay !== dropIsNextDay) {
      // Block cross-day move for stay group guests
      if (res.stay_group_id) {
        toast.warning('연박 그룹에 속한 게스트는 날짜 이동이 불가합니다. 연박 해제 후 이동하세요.');
        return;
      }

      const sourceDate = sourceIsNextDay ? selectedDate.add(1, 'day') : selectedDate;
      const destDate = dropIsNextDay ? selectedDate.add(1, 'day') : selectedDate;
      const destDateStr = destDate.format('YYYY-MM-DD');
      const destCheckout = destDate.add(1, 'day').format('YYYY-MM-DD');
      const roomNumber = entry?.room_number || '';

      // Optimistic update: remove from source list, add to target list
      const sourceSetter = sourceIsNextDay ? setNextDayReservations : setReservations;
      const targetSetter = dropIsNextDay ? setNextDayReservations : setReservations;
      sourceSetter((prev) => prev.filter((r) => r.id !== resId));
      targetSetter((prev) => [...prev, { ...res, room_id: roomId, room_number: roomNumber, check_in_date: destDateStr, check_out_date: destCheckout, section: 'room' }]);

      (async () => {
        try {
          await reservationsAPI.update(resId, {
            check_in_date: destDateStr,
            check_out_date: destCheckout,
          });
          // reconcile_dates in the backend already cleans up old-date assignments
          await reservationsAPI.assignRoom(resId, {
            room_id: roomId,
            date: destDateStr,
            apply_subsequent: false,
          });
          toast.success(`${res.customer_name} → ${roomNumber} (${destDateStr})`);
          fetchReservations(selectedDate);
        } catch (err: any) {
          toast.error(err?.response?.data?.detail || '날짜 이동 실패');
          fetchReservations(selectedDate);
        }
      })();
      return;
    }
    const roomNumber = entry?.room_number || '';

    if (!!res.is_long_stay) {
      setMultiNightConfirm({
        open: true, resId, resName: res.customer_name, roomId, roomNumber,
        onConfirm: (applySubsequent) => {
          setMultiNightConfirm(null);
          doAssignRoom(resId, roomId, roomNumber, applySubsequent, !!res.stay_group_id && applySubsequent, targetDate);
        },
      });
      return;
    }
    doAssignRoom(resId, roomId, roomNumber, true, false, targetDate);
  };

  const handleDropOnPool = async (resId: number, targetDate?: Dayjs) => {
    const found = findReservation(resId);
    if (!found) return;
    const { res, isNextDay } = found;

    const effectiveDate = targetDate || (isNextDay ? selectedDate.add(1, 'day') : selectedDate);
    const setter = isNextDay ? setNextDayReservations : setReservations;
    setRecentlyMovedId(resId);
    const effectiveSection = sectionOverrides[resId] ?? res.section;
    if (!res.room_id && effectiveSection === 'unassigned') return;

    if (res.room_id) {
      setter((prev) => prev.map((r) => {
        if (r.id !== resId) return r;
        const filtered = r.sms_assignments?.filter((a) => !(a.template_key === 'room_info' && !a.sent_at)) || [];
        return { ...r, room_id: null, room_number: null, section: 'unassigned', sms_assignments: filtered };
      }));
      if (!isNextDay) setSectionOverrides((prev) => ({ ...prev, [resId]: 'unassigned' }));
      try {
        await reservationsAPI.assignRoom(resId, { room_id: null, date: effectiveDate.format('YYYY-MM-DD'), apply_subsequent: true });
        await reservationsAPI.update(resId, { section: 'unassigned' });
        toast.success('미배정으로 이동');
        fetchReservations(selectedDate);
      } catch { toast.error('배정 해제에 실패했습니다.'); await fetchReservations(selectedDate); }
    } else {
      if (isNextDay) {
        setter((prev) => prev.map((r) => r.id === resId ? { ...r, section: 'unassigned' } : r));
      } else {
        setSectionOverrides((prev) => ({ ...prev, [resId]: 'unassigned' }));
      }
      toast.success('미배정으로 이동');
      try { await reservationsAPI.update(resId, { section: 'unassigned' }); fetchReservations(selectedDate); }
      catch { if (!isNextDay) setSectionOverrides((prev) => { const next = { ...prev }; delete next[resId]; return next; }); toast.error('이동 실패'); }
    }
  };

  const handleDropOnParty = async (resId: number, targetDate?: Dayjs) => {
    const found = findReservation(resId);
    if (!found) return;
    const { res: guest, isNextDay } = found;

    const effectiveDate = targetDate || (isNextDay ? selectedDate.add(1, 'day') : selectedDate);
    const setter = isNextDay ? setNextDayReservations : setReservations;
    setRecentlyMovedId(resId);
    const effectiveSection = sectionOverrides[resId] ?? guest.section;
    if (!guest.room_id && effectiveSection === 'party') return;

    if (guest.room_id) {
      setter((prev) => prev.map((r) => {
        if (r.id !== resId) return r;
        const filtered = r.sms_assignments?.filter((a) => !(a.template_key === 'room_info' && !a.sent_at)) || [];
        return { ...r, room_id: null, room_number: null, section: 'party', sms_assignments: filtered };
      }));
      if (!isNextDay) setSectionOverrides((prev) => ({ ...prev, [resId]: 'party' }));
      try {
        await reservationsAPI.assignRoom(resId, { room_id: null, date: effectiveDate.format('YYYY-MM-DD'), apply_subsequent: true });
        await reservationsAPI.update(resId, { section: 'party' });
        toast.success('파티만으로 이동');
        fetchReservations(selectedDate);
      } catch { toast.error('이동 실패'); await fetchReservations(selectedDate); }
    } else {
      if (isNextDay) {
        setter((prev) => prev.map((r) => r.id === resId ? { ...r, section: 'party' } : r));
      } else {
        setSectionOverrides((prev) => ({ ...prev, [resId]: 'party' }));
      }
      toast.success('파티만으로 이동');
      try { await reservationsAPI.update(resId, { section: 'party' }); fetchReservations(selectedDate); }
      catch { if (!isNextDay) setSectionOverrides((prev) => { const next = { ...prev }; delete next[resId]; return next; }); toast.error('이동 실패'); }
    }
  };

  const doAssignRoom = async (resId: number, roomId: number, roomNumber: string, applySubsequent: boolean, applyGroup: boolean = false, targetDate?: Dayjs) => {
    const effectiveDate = targetDate || selectedDate;
    const isNextDay = targetDate != null && !targetDate.isSame(selectedDate, 'day');
    const setter = isNextDay ? setNextDayReservations : setReservations;
    // Save previous state for undo (captured before optimistic update)
    const source = isNextDay ? nextDayReservations : reservations;
    const prev = source.find(r => r.id === resId);
    // Optimistic update: move guest to new room + auto-assign room_info SMS tag
    setter((prev) =>
      prev.map((r) => {
        if (r.id !== resId) return r;
        const hasRoomInfo = r.sms_assignments?.some((a) => a.template_key === 'room_info');
        const updatedAssignments = hasRoomInfo
          ? r.sms_assignments
          : [...(r.sms_assignments || []), { id: 0, reservation_id: r.id, template_key: 'room_info', assigned_at: new Date().toISOString(), sent_at: null, assigned_by: 'auto', date: effectiveDate.format('YYYY-MM-DD') } as SmsAssignment];
        return { ...r, room_id: roomId, room_number: roomNumber, sms_assignments: updatedAssignments };
      })
    );
    if (!isNextDay) setSectionOverrides((prev) => { const next = { ...prev }; delete next[resId]; return next; });

    try {
      const { data: result } = await reservationsAPI.assignRoom(resId, {
        room_id: roomId,
        date: effectiveDate.format('YYYY-MM-DD'),
        apply_subsequent: applySubsequent,
        apply_group: applyGroup,
      });
      toast.success(`${roomNumber} 배정 완료`);
      // Push to undo stack only after successful assignment
      if (prev) {
        setUndoStack(stack => [...stack.slice(-19), { resId, prevRoomId: prev.room_id ?? null, prevRoomNumber: (prev as any).room_number ?? null, prevSection: prev.section ?? null, date: effectiveDate.format('YYYY-MM-DD'), customerName: prev.customer_name }]);
      }
      if (result.warnings?.length) {
        result.warnings.forEach((w: string) => toast.warning(w));
      }
      // 서버에서 갱신된 sms_assignments 반영
      fetchReservations(selectedDate);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || '객실 배정에 실패했습니다.');
      await fetchReservations(selectedDate);
    }
  };



  // Stay group modal helpers
  const loadReservationsForDate = async (date: string) => {
    setStayGroupLoading(true);
    try {
      const res = await reservationsAPI.getAll({ date });
      setStayGroupDateReservations(res.data.items || res.data || []);
    } catch {
      toast.error('예약자 목록을 불러올 수 없습니다');
    } finally {
      setStayGroupLoading(false);
    }
  };

  const openStayGroupModalForRes = (resId: number) => {
    const res = reservations.find(r => r.id === resId);
    if (!res) return;

    const initialEntry = {
      id: res.id,
      customer_name: res.customer_name,
      phone: res.phone,
      check_in_date: res.check_in_date,
      check_out_date: res.check_out_date || res.check_in_date,
      stay_group_id: res.stay_group_id,
    };

    setShowStayGroupModal(true);
    setStayGroupChain([initialEntry]);
    setStayGroupSelectedId(null);
    setStayGroupDirection('right');

    // 다음날 예약자 목록 로드 (check_out_date 기준)
    const nextDate = res.check_out_date || res.check_in_date;
    if (nextDate) {
      loadReservationsForDate(nextDate);
    }
  };


  const handleStayGroupAddMore = () => {
    const selected = stayGroupDateReservations.find((r: any) => r.id === stayGroupSelectedId);
    if (!selected) return;

    const entry = {
      id: selected.id,
      customer_name: selected.customer_name,
      phone: selected.phone,
      check_in_date: selected.check_in_date,
      check_out_date: selected.check_out_date || selected.check_in_date,
      stay_group_id: selected.stay_group_id,
    };

    if (stayGroupDirection === 'left') {
      const firstInChain = stayGroupChain[0];
      if (firstInChain && selected.check_out_date !== firstInChain.check_in_date) {
        toast.error('체크아웃 날짜가 다음 예약의 체크인과 일치하지 않습니다');
        return;
      }
      setStayGroupChain([entry, ...stayGroupChain]);
      setStayGroupSelectedId(null);
      const prevDate = dayjs(selected.check_in_date).subtract(1, 'day').format('YYYY-MM-DD');
      loadReservationsForDate(prevDate);
    } else {
      const lastInChain = stayGroupChain[stayGroupChain.length - 1];
      if (lastInChain && selected.check_in_date !== lastInChain.check_out_date) {
        toast.error('체크인 날짜가 이전 예약의 체크아웃과 일치하지 않습니다');
        return;
      }
      setStayGroupChain([...stayGroupChain, entry]);
      setStayGroupSelectedId(null);
      const nextDate = selected.check_out_date || selected.check_in_date;
      if (nextDate) {
        loadReservationsForDate(nextDate);
      }
    }
  };

  const handleStayGroupDirectionChange = (dir: 'left' | 'right') => {
    setStayGroupDirection(dir);
    setStayGroupSelectedId(null);
    if (dir === 'left') {
      const first = stayGroupChain[0];
      if (first) {
        const prevDate = dayjs(first.check_in_date).subtract(1, 'day').format('YYYY-MM-DD');
        loadReservationsForDate(prevDate);
      }
    } else {
      const last = stayGroupChain[stayGroupChain.length - 1];
      if (last) {
        loadReservationsForDate(last.check_out_date || last.check_in_date);
      }
    }
  };

  const handleStayGroupComplete = async () => {
    if (stayGroupChain.length < 2) {
      toast.error('최소 2개의 예약을 선택해야 합니다');
      return;
    }
    setStayGroupLinking(true);
    try {
      const ids = stayGroupChain.map(c => c.id);
      await stayGroupAPI.link(ids[0], ids);
      toast.success(`연박 그룹 생성 완료 (${ids.length}건)`);
      setShowStayGroupModal(false);
      // Refresh data
      window.location.reload();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || '연박 묶기에 실패했습니다');
    } finally {
      setStayGroupLinking(false);
    }
  };

  const handleStayGroupUnlink = async (reservationId: number) => {
    if (!confirm('이 예약을 연박 그룹에서 해제하시겠습니까?\nSMS 스케줄이 변경될 수 있습니다.')) return;
    try {
      await stayGroupAPI.unlink(reservationId);
      toast.success('연박 그룹에서 해제되었습니다');
      window.location.reload();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || '연박 해제에 실패했습니다');
    }
  };

  // ===== Context menu handlers =====
  const onGuestContextMenu = useCallback((e: React.MouseEvent, resId: number, zone?: string) => {
    e.preventDefault();
    e.stopPropagation();
    if (modalVisible || showStayGroupModal || multiNightConfirm?.open) return;

    const targetIds =
      selectedGuestIds.size > 0 && selectedGuestIds.has(resId)
        ? [...selectedGuestIds]
        : [resId];

    setContextMenu({ x: e.clientX, y: e.clientY, targetIds, zone });
  }, [modalVisible, showStayGroupModal, multiNightConfirm?.open, selectedGuestIds]);

  // Close context menu on outside click / scroll / Escape
  useEffect(() => {
    if (!contextMenu) return;
    const openTime = Date.now();
    const close = () => { if (Date.now() - openTime > 300) setContextMenu(null); };
    const onKeyDown = (e: KeyboardEvent) => { if (e.key === 'Escape') setContextMenu(null); };
    document.addEventListener('click', close);
    document.addEventListener('scroll', close, true);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('click', close);
      document.removeEventListener('scroll', close, true);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [contextMenu]);

  const handleAddPartyGuest = () => {
    setEditingId(null);
    setFormValues({
      guest_type: 'party_only',
      customer_name: '',
      phone: '',
      date: selectedDate.format('YYYY-MM-DD'),
      time: '18:00',
      gender: '',
      party_size: 1,
      naver_room_type: '',
      notes: '',
      status: 'confirmed',
      booking_source: 'manual',
    });
    setModalVisible(true);
  };

  const handleQuickAddParty = async () => {
    try {
      const res = await reservationsAPI.create({
        customer_name: '',
        phone: '',
        check_in_date: selectedDate.format('YYYY-MM-DD'),
        check_in_time: '18:00',
        naver_room_type: '파티만',
        section: 'party',
        status: 'confirmed',
        booking_source: 'manual',
      });
      const newId = res.data?.id;
      if (newId) setQuickAddedId(newId);
      await fetchReservations(selectedDate);
      toast.success('파티 게스트 추가됨');
    } catch {
      toast.error('추가 실패');
    }
  };

  const handleEditGuest = (id: number) => {
    const found = findReservation(id);
    if (found?.isNextDay) {
      toast.info('해당 날짜로 이동 후 편집해주세요');
      return;
    }
    const guest = reservations.find((r) => r.id === id);
    if (guest) {
      setEditingId(id);
      setFormValues({
        ...guest,
        guest_type: undefined,
      });
      setModalVisible(true);
    }
  };

  const handleDeleteGuest = (id: number) => {
    showConfirm('게스트 삭제', '정말 삭제하시겠습니까?', async () => {
      try {
        await reservationsAPI.delete(id);
        toast.success('삭제 완료');
        fetchReservations(selectedDate);
      } catch {
        toast.error('삭제 실패');
      }
    });
  };

  const contextMenuActions = useMemo(() => {
    if (!contextMenu) return null;
    const { targetIds } = contextMenu;
    const found = findReservation(targetIds[0]);
    const firstRes = found?.res ?? null;
    const contextIsNextDay = found?.isNextDay ?? false;
    if (!firstRes) return null;

    const effectiveSection = firstRes.room_id ? 'room' : (sectionOverrides[firstRes.id] ?? firstRes.section ?? 'unassigned');
    const isCopied = contextMenu.zone === 'unstable' && firstRes.section !== 'unstable';
    const setter = contextIsNextDay ? setNextDayReservations : setReservations;
    const dateStr = (contextIsNextDay ? selectedDate.add(1, 'day') : selectedDate).format('YYYY-MM-DD');

    return {
      targetCount: targetIds.length,
      currentSection: effectiveSection as 'room' | 'unassigned' | 'party' | 'unstable',
      hasStayGroup: !!firstRes.stay_group_id,
      isUnstableCopy: isCopied,
      isAlreadyCopiedToUnstable: !!firstRes.unstable_party,
      hasRealUnstableBooking: !!firstRes.has_unstable_booking,
      onMoveToPool: () => {
        targetIds.forEach((id) => handleDropOnPool(id));
        setContextMenu(null);
      },
      onMoveToParty: () => {
        targetIds.forEach((id) => handleDropOnParty(id));
        setContextMenu(null);
      },
      onDelete: () => {
        if (targetIds.length > 1) {
          showConfirm('게스트 일괄 삭제', `${targetIds.length}명을 삭제하시겠습니까?`, async () => {
            for (const id of targetIds) {
              try { await reservationsAPI.delete(id); } catch { /* skip */ }
            }
            toast.success(`${targetIds.length}명 삭제 완료`);
            fetchReservations(selectedDate);
          });
        } else {
          handleDeleteGuest(targetIds[0]);
        }
        setContextMenu(null);
      },
      onLinkStayGroup: () => {
        if (contextIsNextDay) {
          toast.info('해당 날짜로 이동 후 연박 설정해주세요');
          setContextMenu(null);
          return;
        }
        if (firstRes.stay_group_id) {
          handleStayGroupUnlink(firstRes.id);
        } else {
          openStayGroupModalForRes(firstRes.id);
        }
        setContextMenu(null);
      },
      onSetColor: async (color: string | null) => {
        for (const id of targetIds) {
          try {
            await reservationsAPI.update(id, { highlight_color: color });
          } catch { /* skip */ }
        }
        setter(prev => prev.map(r =>
          targetIds.includes(r.id) ? { ...r, highlight_color: color } : r
        ));
        setContextMenu(null);
      },
      onCopyToUnstable: async () => {
        for (const id of targetIds) {
          try {
            await reservationsAPI.updateDailyInfo(id, { date: dateStr, unstable_party: true });
          } catch { /* skip */ }
        }
        setter(prev => prev.map(r =>
          targetIds.includes(r.id) ? { ...r, unstable_party: true } : r
        ));
        toast.success(`언스테이블에 복사${targetIds.length > 1 ? ` (${targetIds.length}명)` : ''}`);
        setContextMenu(null);
      },
      onRemoveFromUnstable: async () => {
        for (const id of targetIds) {
          try {
            await reservationsAPI.updateDailyInfo(id, { date: dateStr, unstable_party: false });
          } catch { /* skip */ }
        }
        setter(prev => prev.map(r =>
          targetIds.includes(r.id) ? { ...r, unstable_party: false } : r
        ));
        toast.success('언스테이블 복사본 제거');
        setContextMenu(null);
      },
      onExtendStay: (targetIds.length === 1 && !firstRes?.stay_group_id && firstRes?.booking_source !== 'extend' && !contextIsNextDay) ? async () => {
        const resId = targetIds[0];
        const res = reservations.find((r) => r.id === resId);
        if (!res) return;
        setContextMenu(null);

        const nextDate = selectedDate.add(1, 'day');
        const nextDateStr = nextDate.format('YYYY-MM-DD');

        try {
          const { data } = await api.post(`/api/reservations/${resId}/extend-stay`, {
            room_id: res.room_id || null,
          });

          if (data.conflict_guests && data.conflict_guests.length > 0) {
            const roomEntry = activeRoomEntries.find((e: any) => e.room_id === res.room_id);
            setExtendStayConflict({
              open: true,
              newResId: data.new_reservation_id,
              roomId: res.room_id!,
              roomNumber: roomEntry?.room_number || String((res as any).room_number || ''),
              existingGuests: data.conflict_guests,
            });
          } else {
            toast.success(`연박추가 완료 — ${res.customer_name} (${nextDateStr})`);
            fetchReservations(selectedDate);
          }
        } catch (err: any) {
          toast.error(err?.response?.data?.detail || '연박추가 실패');
          console.error(err);
        }
      } : undefined,
      onCancelExtendStay: (targetIds.length === 1 && firstRes?.stay_group_id?.startsWith('manual-') && !contextIsNextDay) ? async () => {
        const resId = targetIds[0];
        setContextMenu(null);
        try {
          await api.delete(`/api/reservations/${resId}/extend-stay`);
          toast.success('수동연박 취소 완료');
          fetchReservations(selectedDate);
        } catch (err: any) {
          toast.error(err?.response?.data?.detail || '연박취소 실패');
        }
      } : undefined,
      onChangeDates: (targetIds.length === 1) ? () => {
        const res = findReservation(targetIds[0])?.res;
        if (!res) return;
        setDateChangeModal({
          open: true,
          resId: res.id,
          customerName: res.customer_name,
          checkIn: res.check_in_date,
          checkOut: res.check_out_date || res.check_in_date,
        });
        setContextMenu(null);
      } : undefined,
    };
  }, [contextMenu, reservations, nextDayReservations, findReservation, sectionOverrides, handleDropOnPool, handleDropOnParty, handleDeleteGuest, selectedDate, fetchReservations, handleStayGroupUnlink, openStayGroupModalForRes, showConfirm, activeRoomEntries]);

  const handleSubmit = async () => {
    if (savingReservation) return;
    const values = { ...formValues };

    if (!values.customer_name) { toast.error('이름을 입력하세요'); return; }
    if (!values.phone) { toast.error('전화번호를 입력하세요'); return; }
    if (!values.date) { toast.error('날짜를 입력하세요'); return; }

    // Map male_count/female_count to gender + party_size
    const maleCount = values.male_count ? Number(values.male_count) : 0;
    const femaleCount = values.female_count ? Number(values.female_count) : 0;
    const genderParts = [];
    if (maleCount > 0) genderParts.push(`남${maleCount}`);
    if (femaleCount > 0) genderParts.push(`여${femaleCount}`);
    values.gender = genderParts.join('') || null;
    values.party_size = (maleCount + femaleCount) || null;
    values.male_count = maleCount || null;
    values.female_count = femaleCount || null;

    // 연박: check_out_date 계산
    if (values.multi_night && values.nights && values.nights >= 2 && values.date) {
      const checkIn = dayjs(values.date);
      values.check_out_date = checkIn.add(values.nights, 'day').format('YYYY-MM-DD');
    }
    delete values.multi_night;
    delete values.nights;

    // Map field names to backend schema
    values.check_in_date = values.date;
    values.check_in_time = values.time || '00:00';
    delete values.date;
    delete values.time;

    if (!editingId && values.guest_type) {
      if (values.guest_type === 'party_only') {
        values.naver_room_type = '파티만';
        values.section = 'party';
      } else {
        // 수동 추가 - 미배정: naver_room_type을 '수동추가'로 설정
        if (!values.naver_room_type) {
          values.naver_room_type = '수동추가';
        }
      }
      delete values.guest_type;
    }

    setSavingReservation(true);
    try {
      if (editingId) {
        await reservationsAPI.update(editingId, values);
        toast.success('수정 완료');
      } else {
        await reservationsAPI.create(values);
        toast.success('추가 완료');
      }
      setModalVisible(false);
      fetchReservations(selectedDate);
    } catch {
      toast.error('저장 실패');
    } finally {
      setSavingReservation(false);
    }
  };


  const updateReservationSms = (resId: number, updater: (assignments: Reservation['sms_assignments']) => Reservation['sms_assignments']) => {
    setReservations(prev => prev.map(r =>
      r.id === resId ? { ...r, sms_assignments: updater(r.sms_assignments || []) } : r
    ));
  };

  const handleSmsToggle = async (resId: number, templateKey: string) => {
    const res = reservations.find(r => r.id === resId);
    const dateStr = selectedDate.format('YYYY-MM-DD');
    const assignment = res?.sms_assignments?.find(a => a.template_key === templateKey && a.date === dateStr)
      || res?.sms_assignments?.find(a => a.template_key === templateKey);
    const wasSent = !!assignment?.sent_at;

    const tpl = templateLabels.find(t => t.template_key === templateKey);
    setSendConfirm({
      type: 'toggle',
      resId,
      templateKey,
      customerName: res?.customer_name || '',
      templateName: tpl?.name || templateKey,
    });
  };

  const doSmsToggle = async (resId: number, templateKey: string, skipSend?: boolean) => {
    const res = reservations.find(r => r.id === resId);
    const dateStr = selectedDate.format('YYYY-MM-DD');
    const assignment = res?.sms_assignments?.find(a => a.template_key === templateKey && a.date === dateStr)
      || res?.sms_assignments?.find(a => a.template_key === templateKey);
    const wasSent = !!assignment?.sent_at;
    // Optimistic update
    updateReservationSms(resId, assignments =>
      assignments.map(a => a.template_key === templateKey
        ? { ...a, sent_at: wasSent ? null : new Date().toISOString() }
        : a
      )
    );
    try {
      await smsAssignmentsAPI.toggle(resId, templateKey, skipSend, assignment?.date || selectedDate.format('YYYY-MM-DD'));
    } catch {
      // Revert on failure
      updateReservationSms(resId, assignments =>
        assignments.map(a => a.template_key === templateKey
          ? { ...a, sent_at: wasSent ? assignment!.sent_at : null }
          : a
        )
      );
      toast.error('발송 상태 변경 실패');
    }
  };

  const handleSmsAssign = async (resId: number, templateKey: string) => {
    // Optimistic update
    updateReservationSms(resId, assignments => [
      ...assignments,
      { id: 0, reservation_id: resId, template_key: templateKey, assigned_at: new Date().toISOString(), sent_at: null, assigned_by: 'manual', date: selectedDate.format('YYYY-MM-DD') },
    ]);
    try {
      await smsAssignmentsAPI.assign(resId, { template_key: templateKey, date: selectedDate.format('YYYY-MM-DD') });
    } catch {
      // Revert on failure
      updateReservationSms(resId, assignments =>
        assignments.filter(a => a.template_key !== templateKey)
      );
      toast.error('할당 실패');
    }
  };

  const handleSmsRemove = async (resId: number, templateKey: string) => {
    const res = reservations.find(r => r.id === resId);
    const dateStr = selectedDate.format('YYYY-MM-DD');
    const removed = res?.sms_assignments?.find(a => a.template_key === templateKey && a.date === dateStr)
      || res?.sms_assignments?.find(a => a.template_key === templateKey);
    // Optimistic update
    updateReservationSms(resId, assignments =>
      assignments.filter(a => a.template_key !== templateKey)
    );
    try {
      await smsAssignmentsAPI.remove(resId, templateKey, selectedDate.format('YYYY-MM-DD'));
    } catch {
      // Revert on failure
      if (removed) {
        updateReservationSms(resId, assignments => [...assignments, removed]);
      }
      toast.error('제거 실패');
    }
  };

  // ===== Select mode handlers =====
  const onGripClick = useCallback((e: React.MouseEvent | React.PointerEvent, resId: number) => {
    const pe = e as React.PointerEvent;
    if (pe.button !== 0 && pe.pointerType === 'mouse') return;
    e.preventDefault();
    e.stopPropagation();

    const isTouch = pe.pointerType === 'touch';
    const row = (e.target as HTMLElement).closest('.group\\/guest') as HTMLElement | null;

    const res = findReservation(resId)?.res;
    let newTargetIds: number[] = [];

    setSelectedGuestIds(prev => {
      const next = new Set(prev);
      if (e.shiftKey || e.ctrlKey || e.metaKey) {
        if (res?.is_long_stay) {
          toast.warning('연박자는 개별 선택만 가능합니다');
          return prev;
        }
        if ([...prev].some(id => findReservation(id)?.res?.is_long_stay)) {
          toast.warning('연박자가 포함된 상태에서 멀티셀렉트할 수 없습니다');
          return prev;
        }
        if (next.has(resId)) next.delete(resId);
        else next.add(resId);
      } else {
        if (next.has(resId) && next.size === 1) {
          next.clear();
        } else {
          next.clear();
          next.add(resId);
        }
      }
      newTargetIds = [...next];
      return next;
    });

    // Mobile: auto-show context menu at row bottom-right on select
    if (isTouch && row) {
      if (newTargetIds.length > 0) {
        const rect = row.getBoundingClientRect();
        setContextMenu({ x: rect.right - 8, y: rect.bottom, targetIds: newTargetIds });
      } else {
        setContextMenu(null);
      }
    }
  }, [findReservation]);

  const onDropZoneClick = useCallback((e: React.MouseEvent) => {
    if (selectedGuestIds.size === 0) return;

    const interactive = (e.target as HTMLElement).closest('button, a, input, select, textarea, [role="button"], [data-interactive]');
    if (interactive) return;

    const target = (e.target as HTMLElement).closest<HTMLElement>('[data-drop-zone]');
    if (!target) return;
    const zoneId = target.dataset.dropZone || '';

    const ids = [...selectedGuestIds];
    setSelectedGuestIds(new Set());

    if (zoneId.startsWith('next-room-')) {
      const roomId = Number(zoneId.replace('next-room-', ''));
      const targetDate = selectedDate.add(1, 'day');
      const hasCrossDay = ids.some(id => {
        const f = findReservation(id);
        return f && !f.isNextDay;
      });
      if (hasCrossDay) {
        showConfirm('날짜 이동 확인', '오늘 체크인 게스트를 내일 방에 배정하시겠습니까?\n예약 날짜가 내일로 변경됩니다.', () => {
          ids.forEach(id => handleDropOnRoom(id, roomId, targetDate));
        });
        return;
      }
      ids.forEach(id => handleDropOnRoom(id, roomId, targetDate));
    } else if (zoneId.startsWith('room-')) {
      const roomId = Number(zoneId.replace('room-', ''));
      const hasCrossDay = ids.some(id => {
        const f = findReservation(id);
        return f && f.isNextDay;
      });
      if (hasCrossDay) {
        showConfirm('날짜 이동 확인', '내일 체크인 게스트를 오늘 방에 배정하시겠습니까?\n예약 날짜가 오늘로 변경됩니다.', () => {
          ids.forEach(id => handleDropOnRoom(id, roomId));
        });
        return;
      }
      ids.forEach(id => handleDropOnRoom(id, roomId));
    } else if (zoneId === 'next-pool') {
      ids.forEach(id => handleDropOnPool(id, selectedDate.add(1, 'day')));
    } else if (zoneId === 'next-party') {
      ids.forEach(id => handleDropOnParty(id, selectedDate.add(1, 'day')));
    } else if (zoneId === 'pool') {
      ids.forEach(id => handleDropOnPool(id));
    } else if (zoneId === 'party') {
      ids.forEach(id => handleDropOnParty(id));
    }
  }, [selectedGuestIds, handleDropOnRoom, handleDropOnPool, handleDropOnParty, selectedDate, findReservation]);

  const onZoneHover = useCallback((zoneId: string) => {
    if (selectedGuestIds.size === 0) return;
    if (zoneId.startsWith('next-room-')) {
      setDragOverNextRoom(Number(zoneId.replace('next-room-', '')));
      setDragOverRoom(null);
    } else if (zoneId.startsWith('room-')) {
      setDragOverRoom(Number(zoneId.replace('room-', '')));
      setDragOverNextRoom(null);
    } else {
      setDragOverRoom(null);
      setDragOverNextRoom(null);
      if (zoneId === 'next-pool') { setDragOverNextPool(true); setDragOverPool(false); }
      else if (zoneId === 'next-party') { setDragOverNextParty(true); setDragOverPartyZone(false); }
      else if (zoneId === 'pool') { setDragOverPool(true); setDragOverNextPool(false); }
      else if (zoneId === 'party') { setDragOverPartyZone(true); setDragOverNextParty(false); }
    }
  }, [selectedGuestIds.size]);

  const onZoneLeave = useCallback(() => {
    setDragOverRoom(null);
    setDragOverNextRoom(null);
    setDragOverPool(false);
    setDragOverPartyZone(false);
    setDragOverNextPool(false);
    setDragOverNextParty(false);
  }, []);

  const renderGuestRow = (res: Reservation, showGrip: boolean, zone?: string) => {
    const genderPeople = formatGenderPeople(res);
    const longStay = !!res.is_long_stay;
    const isSelected = selectedGuestIds.has(res.id);
    const isCustomHex = isCustomHexColor(res.highlight_color);
    const highlightStyle = !isCustomHex && res.highlight_color ? PRESET_HIGHLIGHT_STYLES[res.highlight_color] : null;
    const hasCustomText = isCustomHex || !!highlightStyle?.text;
    const cellText = hasCustomText ? 'text-inherit' : 'text-[#191F28] dark:text-white';

    return (
      <div key={res.id}
        className={`group/guest flex items-center h-10 ${showGrip ? '' : 'pl-10'} transition-colors duration-150 ${
          isSelected
            ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/15 ring-1 ring-inset ring-[#3182F6]/30'
            : isCustomHex
              ? `${getCustomTextClass(res.highlight_color!)} hover:brightness-[0.97] dark:hover:brightness-110`
              : highlightStyle
                ? `${highlightStyle.bg} ${highlightStyle.hover} ${highlightStyle.text || ''}`
                : longStay ? 'bg-[#FFF0E0] dark:bg-[#FF9500]/15 hover:bg-[#FFE4CC] dark:hover:bg-[#FF9500]/20' : 'hover:bg-[#E8F3FF] dark:hover:bg-[#3182F6]/8'
        } cursor-pointer`}
        style={isCustomHex && !isSelected ? getCustomBgStyle(res.highlight_color!, isDarkMode) : undefined}
        onContextMenu={(e) => onGuestContextMenu(e, res.id, zone)}
        onClick={(e: React.MouseEvent) => {
          if (showGrip && !(e.target as HTMLElement).closest('input, textarea, select, [data-interactive], button, a, [role="button"]')) {
            if (selectionActive && !selectedGuestIds.has(res.id)) {
              return;
            }
            onGripClick(e, res.id);
          }
        }}
      >
        {showGrip && (
          <div
            className={`flex items-center justify-center w-10 px-0.5 flex-shrink-0 cursor-pointer text-[#B0B8C1] dark:text-[#4E5968] transition-all duration-200 ${
              isSelected
                ? 'text-[#3182F6] dark:text-[#3182F6]'
                : longStay ? 'group-hover/guest:text-[#FFB366] dark:group-hover/guest:text-[#FFB366]' : 'group-hover/guest:text-[#3182F6] dark:group-hover/guest:text-[#3182F6]'
            }`}
          >
            <span className="relative flex items-center justify-center w-[18px] h-[18px] group/circle">
              <span className={`absolute inset-0 rounded-full bg-[#3182F6] transition-all duration-300 ease-out ${
                isSelected ? 'scale-[0.55] opacity-80' : 'scale-0 opacity-0 group-hover/circle:scale-[0.55] group-hover/circle:opacity-30'
              }`} />
              <Circle size={18} strokeWidth={1} className={`relative z-10 transition-colors duration-200 ${isSelected ? 'text-[#3182F6]' : ''}`} />
            </span>
          </div>
        )}
        <div
          className="flex-1 grid items-center py-1"
          style={{ gridTemplateColumns: GUEST_COLS }}
        >
          <div className="overflow-hidden px-1.5 flex items-center gap-0.5">
            <span className="flex items-center gap-1">
              <InlineInput value={res.customer_name} field="customer_name" resId={res.id} onSave={handleFieldSave} className={`font-medium ${cellText}`} placeholder="이름" autoFocus={res.id === quickAddedId} disabled={selectionActive} />
              {res.has_unstable_booking && <span className="inline-block h-[6px] w-[6px] rounded-full bg-[#7B61FF] flex-shrink-0" title="언스테이블 파티 예약 확인" />}
            </span>
          </div>
          <div className="overflow-hidden px-1.5">
            <InlineInput value={res.phone} field="phone" resId={res.id} onSave={handleFieldSave} className={`${cellText} tabular-nums`} placeholder="연락처" disabled={selectionActive} />
          </div>
          <div className="overflow-hidden text-center px-1.5">
            <InlineInput value={res.party_type || ''} field="party_type" resId={res.id} onSave={handleFieldSave} className={`${cellText} font-medium text-center`} placeholder="-" disabled={selectionActive} />
          </div>
          <div className="overflow-hidden text-center px-1.5">
            <InlineInput value={genderPeople} field="genderPeople" resId={res.id} onSave={handleFieldSave} className={`${cellText} font-medium text-center`} placeholder="-" disabled={selectionActive} />
          </div>
          <div className="overflow-hidden truncate text-body text-[#8B95A1] dark:text-[#8B95A1] text-center px-1.5">{res.naver_room_type || <span className="text-[#B0B8C1] dark:text-[#4E5968]">-</span>}</div>
          <div className="overflow-hidden px-1.5">
            <InlineInput value={res.notes || ''} field="notes" resId={res.id} onSave={handleFieldSave} className={cellText} placeholder="" disabled={selectionActive} />
          </div>
          <div className="overflow-visible px-1.5">
            <SmsCell reservation={res} templateLabels={templateLabels} selectedDate={selectedDate.format('YYYY-MM-DD')} onToggle={handleSmsToggle} onAssign={handleSmsAssign} onRemove={handleSmsRemove} />
          </div>
        </div>
      </div>
    );
  };

  const renderRoomRow = (entry: { room_id: number; room_number: string; isDormitory: boolean; bed_capacity: number }, rowIndex: number) => {
    const { room_id, room_number, isDormitory, bed_capacity } = entry;
    const groupInfo = roomGroupMap.get(room_id);
    const guestsRaw = assignedRooms.get(room_id) || [];
    const isDragOver = dragOverRoom === room_id;
    const nextGuestsRaw = nextDayRoomMap.get(room_id) || [];

    // 도미토리: bed_order 기준 정렬 (백엔드에서 연박자 행 위치 통일)
    let guests = guestsRaw;
    let nextGuests = nextGuestsRaw;
    if (isDormitory) {
      guests = [...guestsRaw].sort((a, b) => (a.bed_order || 0) - (b.bed_order || 0) || a.id - b.id);
      nextGuests = [...nextGuestsRaw].sort((a, b) => (a.bed_order || 0) - (b.bed_order || 0) || a.id - b.id);
    }

    const maxOccupancy = Math.max(guests.length, nextGuests.length, 1);
    const visibleRows = isDormitory
      ? Math.min(bed_capacity, maxOccupancy)
      : Math.max(1, guests.length);
    const totalRows = visibleRows;
    const hasGuests = guests.length > 0;
    const rowHeight = hasGuests ? 40 : 36;
    const stripeKey = groupInfo ? groupInfo.groupIndex : rowIndex;
    const isOverbooking = !isDormitory && guests.length >= 2;

    // Dynamic stripe colors from row color settings
    const stripeBgStyle: React.CSSProperties = isOverbooking
      ? { backgroundColor: isDarkMode ? `${rowColors.overbooking}1A` : rowColors.overbooking }
      : stripeKey % 2 === 0
        ? { backgroundColor: isDarkMode ? rowColors.evenDark : rowColors.even }
        : { backgroundColor: isDarkMode ? rowColors.oddDark : rowColors.odd };

    // Dynamic group border color
    const groupLast = groupInfo?.isLast;
    const groupColor = groupLast && groupInfo
      ? roomGroups.find(g => g.id === groupInfo.group_id)?.color
      : undefined;
    const borderStyle: React.CSSProperties | undefined = groupLast
      ? { borderBottomColor: isDarkMode ? (groupColor || '#4E5968') : (groupColor || '#D1D5DB') }
      : { borderBottomColor: isDarkMode ? '#2C2C34' : '#E5E8EB' };

    return (
      <div
        key={room_id}
        className={`group flex select-none transition-colors
          ${isDragOver
            ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/8 ring-1 ring-inset ring-[#3182F6]/30 dark:ring-[#3182F6]/30'
            : ''
          } ${selectionActive ? 'cursor-pointer' : ''}`}
        style={{ minHeight: `${totalRows * rowHeight}px`, ...(isDragOver ? {} : stripeBgStyle) }}
        data-drop-zone={`room-${room_id}`}
        onClick={onDropZoneClick}
        onMouseEnter={() => onZoneHover(`room-${room_id}`)}
        onMouseLeave={onZoneLeave}
      >
        {/* Room label - vertically centered, spans all rows */}
        <div className="flex items-center gap-1.5 flex-shrink-0 w-42 pl-3 pr-2 py-2 border-r border-b" style={{ ...borderStyle, ...stripeBgStyle }}>
          <span className="font-semibold text-[#191F28] dark:text-white text-body">{room_number}</span>
          {roomInfoMap[room_number] && (
            <span className="text-caption text-[#B0B8C1] dark:text-[#8B95A1] truncate">{roomInfoMap[room_number]}</span>
          )}
        </div>

        {/* Guest rows */}
        <div className="flex-1 divide-y divide-[#F2F4F6] dark:divide-[#2C2C34] border-b" style={borderStyle}>
          {isDormitory ? (
            // Dormitory: show beds as rows, filled or empty
            Array.from({ length: totalRows }).map((_, i) => {
              const guest = guests[i];
              if (guest) {
                return renderGuestRow(guest, true);
              }
              return (
                <div key={`empty-${i}`} className={`flex items-center h-9 cursor-default`}>
                  <div
                    className="flex-1 grid items-center py-1"
                    style={{ gridTemplateColumns: GUEST_COLS }}
                  >
                    <div className="overflow-hidden truncate col-span-full text-body text-[#B0B8C1] dark:text-[#4E5968] italic px-1.5">
                      {isDragOver ? '여기에 놓으세요' : ''}
                    </div>
                  </div>
                </div>
              );
            })
          ) : guests.length > 0 ? (
            guests.map((res) => renderGuestRow(res, true))
          ) : (
            <div className={`flex items-center h-9 cursor-default`}>
              <div
                className="flex-1 grid items-center py-1"
                style={{ gridTemplateColumns: GUEST_COLS }}
              >
                <div className="overflow-hidden truncate col-span-full text-body text-[#3182F6] dark:text-[#3182F6] italic px-1.5">
                  {isDragOver ? '여기에 놓으세요' : ''}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Next day column */}
        <div
          className={`flex-shrink-0 border-l-8 border-white dark:border-[#2C2C34] shadow-[inset_1px_0_0_#E5E8EB,-1px_0_0_#E5E8EB] z-[2] border-b transition-all duration-200 ${
            dragOverNextRoom === room_id
              ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/8 ring-1 ring-inset ring-[#3182F6]/30'
              : ''
          } ${selectionActive ? 'cursor-pointer' : ''}`}
          style={{ width: nextDayExpanded ? NEXT_DAY_EXPANDED_WIDTH : colWidths.nextDay, ...(dragOverNextRoom === room_id ? {} : { ...borderStyle, ...stripeBgStyle }) }}
          data-drop-zone={nextDayExpanded ? `next-room-${room_id}` : undefined}
          onClick={onDropZoneClick}
          onMouseEnter={nextDayExpanded ? () => onZoneHover(`next-room-${room_id}`) : undefined}
          onMouseLeave={nextDayExpanded ? onZoneLeave : undefined}
        >
          <div className="divide-y divide-[#F2F4F6] dark:divide-[#2C2C34]">
            {Array.from({ length: totalRows }).map((_, i) => {
              const nextGuest = nextGuests[i];
              const gp = nextGuest ? formatGenderPeople(nextGuest) : '';
              return (
                <div key={`next-${i}`} className={`flex items-center ${nextDayExpanded ? 'justify-start' : 'justify-center'} ${hasGuests ? 'h-10' : 'h-9'} px-1 ${nextGuest?.is_long_stay ? 'bg-[#FFF0E0] dark:bg-[#FF9500]/15' : ''}`}>
                  {nextGuest ? (
                    nextDayExpanded ? (
                      <div className="group/guest flex items-center h-10 w-full"
                        onContextMenu={(e) => onGuestContextMenu(e, nextGuest.id)}
                      >
                        {/* Selection grip */}
                        <div
                          onClick={(e: React.MouseEvent) => onGripClick(e, nextGuest.id)}
                          className={`flex items-center justify-center w-8 px-0.5 flex-shrink-0 cursor-pointer text-[#B0B8C1] dark:text-[#4E5968] transition-all duration-200 ${
                            selectedGuestIds.has(nextGuest.id)
                              ? 'text-[#3182F6] dark:text-[#3182F6]'
                              : 'group-hover/guest:text-[#3182F6] dark:group-hover/guest:text-[#3182F6]'
                          }`}
                        >
                          <span className="relative flex items-center justify-center w-[16px] h-[16px] group/circle">
                            <span className={`absolute inset-0 rounded-full bg-[#3182F6] transition-all duration-300 ease-out ${
                              selectedGuestIds.has(nextGuest.id) ? 'scale-[0.55] opacity-80' : 'scale-0 opacity-0 group-hover/circle:scale-[0.55] group-hover/circle:opacity-30'
                            }`} />
                            <Circle size={16} strokeWidth={1} className={`relative z-10 transition-colors duration-200 ${selectedGuestIds.has(nextGuest.id) ? 'text-[#3182F6]' : ''}`} />
                          </span>
                        </div>
                        {/* Editable fields */}
                        <div
                          className="flex-1 grid items-center py-1"
                          style={{ gridTemplateColumns: NEXT_GUEST_COLS }}
                        >
                          <div className="overflow-hidden px-1">
                            <InlineInput value={nextGuest.customer_name} field="customer_name" resId={nextGuest.id}
                              onSave={(id, f, v) => handleFieldSave(id, f, v, selectedDate.add(1, 'day'))}
                              className="font-medium text-[#191F28] dark:text-white text-caption" placeholder="이름" disabled={selectionActive} />
                          </div>
                          <div className="overflow-hidden px-1">
                            <InlineInput value={nextGuest.phone || ''} field="phone" resId={nextGuest.id}
                              onSave={(id, f, v) => handleFieldSave(id, f, v, selectedDate.add(1, 'day'))}
                              className="text-[#191F28] dark:text-white tabular-nums text-caption" placeholder="연락처" disabled={selectionActive} />
                          </div>
                          <div className="overflow-hidden text-center px-1">
                            <InlineInput value={nextGuest.party_type || ''} field="party_type" resId={nextGuest.id}
                              onSave={(id, f, v) => handleFieldSave(id, f, v, selectedDate.add(1, 'day'))}
                              className="text-[#191F28] dark:text-white font-medium text-center text-caption" placeholder="-" disabled={selectionActive} />
                          </div>
                          <div className="overflow-hidden text-center px-1">
                            <InlineInput value={gp} field="genderPeople" resId={nextGuest.id}
                              onSave={(id, f, v) => handleFieldSave(id, f, v, selectedDate.add(1, 'day'))}
                              className="text-[#191F28] dark:text-white font-medium text-center text-caption" placeholder="-" disabled={selectionActive} />
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-center gap-1.5 truncate">
                        <span className="truncate text-caption text-[#4E5968] dark:text-[#8B95A1]">{nextGuest.customer_name}</span>
                        {gp && <span className="flex-shrink-0 text-caption text-[#8B95A1] dark:text-[#4E5968]">{gp}</span>}
                      </div>
                    )
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    );
  };

  const navigateDate = useCallback(
    (direction: 'prev' | 'next') => {
      if (animDirection !== 'none') return;
      setAnimDirection(direction === 'prev' ? 'left' : 'right');

      const newDate = direction === 'prev'
        ? selectedDate.subtract(1, 'day')
        : selectedDate.add(1, 'day');

      // 애니메이션(200ms) + 데이터 fetch를 동시에 시작
      const animPromise = new Promise((r) => setTimeout(r, 200));
      const dateStr = newDate.format('YYYY-MM-DD');
      const diff = direction === 'next' ? 1 : -1;

      let dataPromise: Promise<void>;

      if (diff === 1 && nextDayRef.current.length > 0) {
        // 다음: 시프트 + 익일만 fetch
        const newCurrent = nextDayRef.current;
        dataPromise = reservationsAPI.getAll({ date: newDate.add(1, 'day').format('YYYY-MM-DD'), limit: 200 })
          .catch(() => ({ data: { items: [] } }))
          .then((res: any) => {
            const nextData = filterActive(res.data.items ?? res.data);
            reservationsRef.current = newCurrent;
            nextDayRef.current = nextData;
            setReservations(newCurrent);
            setNextDayReservations(nextData);
          });
      } else {
        // 폴백: 당일 먼저
        dataPromise = reservationsAPI.getAll({ date: dateStr, limit: 200 })
          .then((res) => {
            const curr = filterActive(res.data.items ?? res.data);
            reservationsRef.current = curr;
            setReservations(curr);
            // 다음날 백그라운드
            reservationsAPI.getAll({ date: newDate.add(1, 'day').format('YYYY-MM-DD'), limit: 200 })
              .then(r => { const d = filterActive(r.data.items ?? r.data); setNextDayReservations(d); nextDayRef.current = d; })
              .catch(() => { setNextDayReservations([]); nextDayRef.current = []; });
          })
          .catch(() => { toast.error('예약 목록을 불러오지 못했습니다.'); });
      }

      // 애니메이션과 fetch 둘 다 끝나면 날짜 전환
      Promise.all([animPromise, dataPromise]).then(() => {
        prevDateRef.current = newDate;
        setSelectedDate(newDate);
        setAnimDirection('none');
      });
    },
    [animDirection, selectedDate, filterActive],
  );

  // suppress unused handleEditGuest warning — used via modal open
  void handleEditGuest;

  // Summary stats
  const summary = useMemo(() => {
    // Room guest totals (복사본 = unstable_party=true인 비-unstable 예약자 제외)
    let roomTotal = 0, roomMale = 0, roomFemale = 0;
    for (const r of reservations) {
      if (r.section !== 'unstable' && r.unstable_party) continue; // 복사본 제외
      const m = r.male_count || 0;
      const f = r.female_count || 0;
      roomMale += m;
      roomFemale += f;
      roomTotal += m + f;
    }

    // Party guest totals (only those with party_type)
    const partyGuests = reservations.filter((r) => r.party_type);
    let partyMale = 0, partyFemale = 0;
    let firstMale = 0, firstFemale = 0;
    let secondOnlyMale = 0, secondOnlyFemale = 0;

    for (const r of partyGuests) {
      const m = r.male_count || 0;
      const f = r.female_count || 0;
      partyMale += m;
      partyFemale += f;

      if (r.party_type === '1' || r.party_type === '2') {
        // 1차 참여 = 1차만 + 1,2차
        firstMale += m;
        firstFemale += f;
      }
      if (r.party_type === '2차만') {
        secondOnlyMale += m;
        secondOnlyFemale += f;
      }
    }

    const partyTotal = partyMale + partyFemale;
    const firstTotal = firstMale + firstFemale;
    const secondOnlyTotal = secondOnlyMale + secondOnlyFemale;
    // 2차 전환율 = 1차 중 2차도 참여한 인원 / 1차 전체
    const bothGuests = partyGuests.filter((r) => r.party_type === '2');
    const bothTotal = bothGuests.reduce((sum, r) => sum + (r.male_count || 0) + (r.female_count || 0), 0);
    const conversionRate = firstTotal > 0 ? Math.round((bothTotal / firstTotal) * 100) : 0;
    const genderRatio = firstFemale > 0 ? `${(firstMale / firstFemale).toFixed(1)}:1` : firstMale > 0 ? `${firstMale}:0` : '-';

    // Unstable guest totals (순수 section="unstable" + 복사된 unstable_party=true)
    let unstableMale = 0, unstableFemale = 0;
    for (const r of unstableGuests) {
      unstableMale += r.male_count || 0;
      unstableFemale += r.female_count || 0;
    }
    const unstableTotal = unstableMale + unstableFemale;

    return {
      roomTotal, roomMale, roomFemale,
      partyTotal, partyMale, partyFemale,
      firstTotal, firstMale, firstFemale,
      secondOnlyTotal, secondOnlyMale, secondOnlyFemale,
      conversionRate, genderRatio,
      unstableTotal, unstableMale, unstableFemale,
    };
  }, [reservations, unstableGuests]);

  return (
    <div className={`space-y-4 pb-14 min-w-max ${processing ? 'opacity-60 pointer-events-none' : ''}`}>

      {/* Page header */}
      <div>
        <div className="flex items-center gap-2.5">
          <div className="stat-icon bg-[#E8F3FF] text-[#3182F6] dark:bg-[#3182F6]/15 dark:text-[#3182F6]">
            <BedDouble size={20} />
          </div>
          <div>
            <h1 className="page-title">객실 배정</h1>
            <p className="page-subtitle">날짜별 객실을 배정하고 SMS를 발송하세요</p>
          </div>
        </div>
      </div>

      {/* Summary stats */}
      <div className="flex flex-wrap gap-3 items-stretch">
        {/* 그룹 카드 */}
        <div className="stat-card flex overflow-hidden !p-0">
          <div className="w-[130px] flex flex-col items-center justify-center px-3 py-4">
            <span className="stat-label whitespace-nowrap">총 예약자</span>
            <div className="flex items-center justify-center gap-2.5 mt-1">
              <span className="stat-value tabular-nums text-[#4A90D9]">{summary.roomMale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
              <span className="h-3 w-px bg-[#E5E8EB] dark:bg-[#2C2C34]" />
              <span className="stat-value tabular-nums text-[#E05263]">{summary.roomFemale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
            </div>
          </div>
          <div className="w-px bg-[#E5E8EB] dark:bg-[#2C2C34] my-3" />
          <div className="w-[130px] flex flex-col items-center justify-center px-3 py-4">
            <span className="stat-label whitespace-nowrap">현재 신청인원</span>
            <div className="stat-value tabular-nums mt-1">{summary.partyTotal}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></div>
          </div>
          <div className="w-px bg-[#E5E8EB] dark:bg-[#2C2C34] my-3" />
          <div className="w-[130px] flex flex-col items-center justify-center px-3 py-4">
            <span className="stat-label whitespace-nowrap">1차</span>
            <div className="flex items-center justify-center gap-2.5 mt-1">
              <span className="stat-value tabular-nums text-[#4A90D9]">{summary.firstMale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
              <span className="h-3 w-px bg-[#E5E8EB] dark:bg-[#2C2C34]" />
              <span className="stat-value tabular-nums text-[#E05263]">{summary.firstFemale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
            </div>
          </div>
          <div className="w-px bg-[#E5E8EB] dark:bg-[#2C2C34] my-3" />
          <div className="w-[130px] flex flex-col items-center justify-center px-3 py-4">
            <span className="stat-label whitespace-nowrap">2차만</span>
            <div className="flex items-center justify-center gap-2.5 mt-1">
              <span className="stat-value tabular-nums text-[#4A90D9]">{summary.secondOnlyMale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
              <span className="h-3 w-px bg-[#E5E8EB] dark:bg-[#2C2C34]" />
              <span className="stat-value tabular-nums text-[#E05263]">{summary.secondOnlyFemale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
            </div>
          </div>
          {hasUnstable && summary.unstableTotal > 0 && (
            <>
              <div className="w-px bg-[#E5E8EB] dark:bg-[#2C2C34] my-3" />
              <div className="w-[130px] flex flex-col items-center justify-center px-3 py-4">
                <span className="stat-label whitespace-nowrap text-[#FF6B2C]">언스테이블</span>
                <div className="flex items-center justify-center gap-2.5 mt-1">
                  <span className="stat-value tabular-nums text-[#4A90D9]">{summary.unstableMale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
                  <span className="h-3 w-px bg-[#E5E8EB] dark:bg-[#2C2C34]" />
                  <span className="stat-value tabular-nums text-[#E05263]">{summary.unstableFemale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
                </div>
              </div>
            </>
          )}
          <div className="w-px bg-[#E5E8EB] dark:bg-[#2C2C34] my-3" />
          <div className="w-[130px] flex flex-col items-center justify-center px-3 py-4">
            <span className="stat-label whitespace-nowrap">전체</span>
            <div className="flex items-center justify-center gap-2.5 mt-1">
              <span className="stat-value tabular-nums text-[#4A90D9]">{summary.partyMale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
              <span className="h-3 w-px bg-[#E5E8EB] dark:bg-[#2C2C34]" />
              <span className="stat-value tabular-nums text-[#E05263]">{summary.partyFemale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
            </div>
          </div>
        </div>
        <div className="stat-card w-[120px] flex flex-col items-center justify-center">
          <span className="stat-label">2차 전환율</span>
          <div className="stat-value tabular-nums mt-1">{summary.conversionRate}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">%</span></div>
        </div>
        <div className="stat-card w-[120px] flex flex-col items-center justify-center">
          <span className="stat-label">파티 성비</span>
          <div className="stat-value tabular-nums mt-1">{summary.genderRatio}</div>
        </div>
      </div>

      {/* Campaign controls */}
      <div className="section-card !overflow-visible">
        <div className="section-body py-3">
          <div className="flex flex-wrap gap-2 items-center">
            {/* Campaign dropdown selector */}
            <div className="relative" ref={campaignDropdownRef}>
              <button
                type="button"
                onClick={() => setCampaignDropdownOpen(!campaignDropdownOpen)}
                className="flex items-center justify-between gap-2 px-3 py-1.5 text-sm font-medium rounded-lg border border-[#E5E8EB] dark:border-[#2C2C34] bg-white dark:bg-[#1E1E24] text-[#191F28] dark:text-white hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34] transition-colors cursor-pointer min-w-[160px]"
              >
                {selectedTemplateKey
                  ? templateLabels.find(t => t.template_key === selectedTemplateKey)?.name || '템플릿 선택'
                  : '템플릿 선택'}
                <ChevronDown size={14} className={`text-[#8B95A1] transition-transform ${campaignDropdownOpen ? 'rotate-180' : ''}`} />
              </button>
              {campaignDropdownOpen && (
                <div className="absolute top-full left-0 mt-1 z-30 min-w-[160px] rounded-xl border border-[#E5E8EB] dark:border-[#2C2C34] bg-white dark:bg-[#1E1E24] shadow-lg shadow-black/8 py-1 animate-in fade-in slide-in-from-top-1 duration-150">
                  {templateLabels.map(t => (
                    <button
                      key={t.template_key}
                      type="button"
                      onClick={() => { setSelectedTemplateKey(t.template_key); setCampaignDropdownOpen(false); setTargets([]); }}
                      className={`w-full text-left px-3 py-2 text-sm transition-colors cursor-pointer
                        ${selectedTemplateKey === t.template_key ? 'bg-[#F2F4F6] dark:bg-[#2C2C34] text-[#3182F6] font-medium' : 'text-[#4E5968] dark:text-white hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34]'}`}
                    >
                      {t.name}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <Button
              color="light"
              size="sm"
              onClick={loadTargets}
              disabled={!selectedTemplateKey}
            >
              <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
              대상조회
            </Button>
            <Button
              color="blue"
              size="sm"
              onClick={requestSendCampaign}
              disabled={sending || targets.length === 0 || !selectedTemplateKey}
            >
              {sending ? (
                <Spinner size="sm" className="mr-1.5" />
              ) : (
                <Send className="h-3.5 w-3.5 mr-1.5" />
              )}
              발송 ({targets.length}건)
            </Button>

            <div className="ml-auto flex items-center gap-2">
              <Button
                color="light"
                size="sm"
                onClick={() => setTableSettingsOpen(true)}
              >
                <Layers className="h-3.5 w-3.5 mr-1.5" />
                테이블 설정
              </Button>

              <Button
                color="light"
                size="sm"
                onClick={handleAddPartyGuest}
              >
                <UserPlus className="h-3.5 w-3.5 mr-1.5" />
                예약자 추가
              </Button>
            </div>
          </div>

          {targets.length > 0 && (
            <div className="mt-3 rounded-lg border border-[#E5E8EB] dark:border-[#2C2C34] bg-[#F8F9FA] dark:bg-[#17171C] p-3">
              <div className="flex justify-between items-center mb-2">
                <Badge color="info" size="sm">발송 대상 {targets.length}건</Badge>
                <Button
                  color="light"
                  size="xs"
                  onClick={() => setTargets([])}
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {targets.map((t) => (
                  <Badge key={t.id} color="gray" size="sm">
                    {t.customer_name} {t.phone} {t.room_number || ''}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Main grid card */}
      <div className="section-card !overflow-visible w-max min-w-full">
        {/* Date navigation header — sticky */}
        <div ref={dateHeaderRef} className="sticky top-0 z-20">
          <div className="section-header justify-center bg-white dark:bg-[#1E1E24]">
            <div className="flex items-center gap-1">
              <button
                onClick={() => navigateDate('prev')}
                className="cursor-pointer p-1 text-[#B0B8C1] hover:text-[#191F28] dark:text-[#4E5968] dark:hover:text-white transition-colors bg-transparent border-none"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <TextInput
                type="date"
                sizing="sm"
                value={selectedDate.format('YYYY-MM-DD')}
                onChange={(e) => {
                  if (e.target.value) setSelectedDate(dayjs(e.target.value));
                }}
              />
              <button
                onClick={() => navigateDate('next')}
                className="cursor-pointer p-1 text-[#B0B8C1] hover:text-[#191F28] dark:text-[#4E5968] dark:hover:text-white transition-colors bg-transparent border-none"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        <div className="section-body !pt-2">
          <div
            key={selectedDate.format('YYYY-MM-DD')}
            className={
              animDirection === 'left'
                ? 'date-slide-left'
                : animDirection === 'right'
                  ? 'date-slide-right'
                  : ''
            }
          >
            {/* Unified Table */}
            <div ref={tableContainerRef} className="relative rounded-xl border border-[#F2F4F6] dark:border-[#2C2C34]">
              {resizeGuideX !== null && (
                <div className="absolute top-0 bottom-0 w-px bg-[#3182F6] z-50 pointer-events-none" style={{ left: resizeGuideX }} />
              )}
              {/* Header */}
              <div className="flex items-center h-10 bg-[#F2F4F6] dark:bg-[#17171C] border-b border-[#D1D5DB] dark:border-[#4E5968] sticky z-[19]" style={{ top: dateHeaderH }}>
                <div className="flex-shrink-0 pl-3 pr-2 w-42 border-r border-[#F2F4F6] dark:border-[#2C2C34]">
                  <span className="text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">객실</span>
                </div>
                <div className="w-10 flex-shrink-0" />
                <div
                  className="flex-1 grid items-center"
                  style={{ gridTemplateColumns: GUEST_COLS }}
                >
                  <div className="relative pl-[9px] pr-1.5 text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">이름<div onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); resizeStartXRef.current = e.clientX; resizeStartWidthRef.current = colWidths.name; setResizeCol('name'); }} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                  <div className="relative pl-[9px] pr-1.5 text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">전화번호<div onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); resizeStartXRef.current = e.clientX; resizeStartWidthRef.current = colWidths.phone; setResizeCol('phone'); }} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                  <div className="relative px-1.5 text-center text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">파티<div onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); resizeStartXRef.current = e.clientX; resizeStartWidthRef.current = colWidths.party; setResizeCol('party'); }} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                  <div className="relative px-1.5 text-center text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">성별<div onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); resizeStartXRef.current = e.clientX; resizeStartWidthRef.current = colWidths.gender; setResizeCol('gender'); }} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                  <div className="relative px-1.5 text-center text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">예약객실<div onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); resizeStartXRef.current = e.clientX; resizeStartWidthRef.current = colWidths.roomType; setResizeCol('roomType'); }} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                  <div className="relative pl-[9px] pr-1.5 text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">메모<div onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); resizeStartXRef.current = e.clientX; resizeStartWidthRef.current = colWidths.notes; setResizeCol('notes'); }} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                  <div className="relative pl-[9px] pr-1.5 text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">문자<div onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); resizeStartXRef.current = e.clientX; resizeStartWidthRef.current = colWidths.sms; setResizeCol('sms'); }} className="absolute right-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:right-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" /></div>
                </div>
                <div className="relative flex-shrink-0 border-l-8 border-white dark:border-[#2C2C34] shadow-[inset_1px_0_0_#E5E8EB,-1px_0_0_#E5E8EB] z-[2] flex flex-col justify-center self-stretch transition-all duration-200" style={{ width: nextDayExpanded ? NEXT_DAY_EXPANDED_WIDTH : colWidths.nextDay }}>
                  {!nextDayExpanded && (
                    <div onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); resizeStartXRef.current = e.clientX; resizeStartWidthRef.current = colWidths.nextDay; setResizeCol('nextDay'); }} className="absolute left-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:left-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" />
                  )}
                  {!nextDayExpanded ? (
                    <div className="flex items-center justify-center gap-1 px-2">
                      <button onClick={() => setNextDayExpanded(true)} className="text-[#8B95A1] hover:text-[#3182F6] transition-colors cursor-pointer" title="펼치기">
                        <ChevronsLeft className="h-3.5 w-3.5" />
                      </button>
                      <span className="text-caption font-semibold text-[#8B95A1] dark:text-[#8B95A1]">{selectedDate.add(1, 'day').format('M/D')}</span>
                    </div>
                  ) : (
                    <div className="flex items-center">
                      <button onClick={() => setNextDayExpanded(false)} className="w-8 flex-shrink-0 flex items-center justify-center text-[#8B95A1] hover:text-[#3182F6] transition-colors cursor-pointer" title="접기">
                        <ChevronsRight className="h-3.5 w-3.5" />
                      </button>
                      <div className="flex-1 grid items-center" style={{ gridTemplateColumns: NEXT_GUEST_COLS }}>
                        <div className="px-1 text-caption font-semibold text-[#8B95A1] whitespace-nowrap">{selectedDate.add(1, 'day').format('M/D')}</div>
                        <div className="px-1 text-[10px] font-semibold text-[#8B95A1]">전화번호</div>
                        <div className="px-1 text-center text-[10px] font-semibold text-[#8B95A1]">파티</div>
                        <div className="px-1 text-center text-[10px] font-semibold text-[#8B95A1]">성별</div>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Selection mode toast is handled via useEffect */}

              {/* Room Rows (stale-while-revalidate: 이전 데이터 유지, 새 데이터 조용히 교체) */}
              <div className={loading ? 'pointer-events-none' : ''} onContextMenu={(e) => { if (!(e.target as HTMLElement).closest('[data-allow-context]')) e.preventDefault(); }}>
                {(() => {
                  let rowIdx = 0;
                  return buildingGroups.map((group) => {
                    const isCollapsed = collapsedBuildings.has(group.building_id);
                    const buildingLabel = group.building_name || '기타';
                    const summary = `${group.assignedCount}/${group.totalCount}`;

                    const roomRows = !isCollapsed
                      ? group.entries.map((entry) => {
                          const row = renderRoomRow(entry, rowIdx);
                          rowIdx++;
                          return row;
                        })
                      : (() => { rowIdx += group.entries.length; return null; })();

                    return (
                      <div key={`building-${group.building_id ?? 'none'}`} className="relative">
                        {/* Bookmark tab */}
                        <div
                          className="absolute -left-[2px] top-0 z-10 flex items-center justify-center cursor-pointer select-none rounded-l-md w-4 h-6 border border-r-0 border-[#E5E8EB] dark:border-[#2C2C34] bg-white dark:bg-[#1E1E24] hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34] transition-colors shadow-sm"
                          style={{ transform: 'translateX(-100%)' }}
                          onClick={() => toggleBuildingCollapse(group.building_id)}
                          title={`${buildingLabel} ${summary}`}
                        >
                          {isCollapsed
                            ? <Plus className="h-2.5 w-2.5 text-[#8B95A1]" />
                            : <Minus className="h-2.5 w-2.5 text-[#8B95A1]" />}
                        </div>
                        {isCollapsed ? (
                          <div
                            className="flex items-center h-8 px-3 border-b border-[#E5E8EB] dark:border-[#2C2C34] bg-[#F8F9FA]/50 dark:bg-[#17171C]/30 cursor-pointer"
                            onClick={() => toggleBuildingCollapse(group.building_id)}
                          >
                            <span className="text-caption text-[#B0B8C1] dark:text-gray-600">{buildingLabel} ({summary})</span>
                          </div>
                        ) : roomRows}
                      </div>
                    );
                  });
                })()}
              </div>

              {/* Unassigned Pool */}
              <div
                className={`group flex select-none transition-colors ${
                  dragOverPool
                    ? 'bg-[#FF9500]/50 dark:bg-[#FF9500]/8'
                    : unassigned.length > 0 ? 'bg-white dark:bg-[#1E1E24]' : 'bg-[#F2F4F6]/50 dark:bg-[#17171C]/30'
                } ${selectionActive ? 'cursor-pointer' : ''}`}
                style={{ minHeight: `${Math.max(Math.max(1, unassigned.length), Math.max(1, nextDayUnassigned.length)) * 40}px` }}
                data-drop-zone="pool"
                onClick={onDropZoneClick}
                onMouseEnter={() => onZoneHover('pool')}
                onMouseLeave={onZoneLeave}
              >
                {/* Room label */}
                <div className="flex items-center gap-1.5 flex-shrink-0 w-42 pl-3 pr-2 py-2 border-r border-b border-[#E5E8EB] dark:border-[#2C2C34] bg-white dark:bg-[#1E1E24]">
                  <span className="font-semibold text-[#FF9500] dark:text-[#FF9500] text-body">미배정</span>
                </div>

                {/* Guest area */}
                <div className="flex-1 divide-y divide-[#F2F4F6] dark:divide-[#2C2C34] border-b border-[#E5E8EB] dark:border-[#2C2C34]">
                  {unassigned.length > 0 ? (
                    unassigned.map((res) => renderGuestRow(res, true))
                  ) : (
                    <div className={`flex items-center h-10 cursor-default`}>
                      <div className="flex-1 grid items-center py-1" style={{ gridTemplateColumns: GUEST_COLS }}>
                        <div className="overflow-hidden truncate col-span-full text-body text-[#FF9500] dark:text-[#FF9500] italic px-1.5">
                          {dragOverPool ? '클릭하면 배정 해제' : ''}
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* Next day column for pool */}
                <div
                  className={`flex-shrink-0 border-l-8 border-white dark:border-[#2C2C34] shadow-[inset_1px_0_0_#E5E8EB,-1px_0_0_#E5E8EB] z-[2] bg-[#F8F9FA] dark:bg-[#17171C] border-b border-b-[#E5E8EB] dark:border-b-gray-700 transition-all duration-200 ${
                    dragOverNextPool ? 'bg-[#FF9500]/50 dark:bg-[#FF9500]/8' : ''
                  } ${selectionActive ? 'cursor-pointer' : ''}`}
                  style={{ width: nextDayExpanded ? NEXT_DAY_EXPANDED_WIDTH : colWidths.nextDay, minHeight: `${Math.max(1, nextDayUnassigned.length) * 40}px` }}
                  data-drop-zone={nextDayExpanded ? 'next-pool' : undefined}
                  onClick={onDropZoneClick}
                  onMouseEnter={nextDayExpanded ? () => onZoneHover('next-pool') : undefined}
                  onMouseLeave={nextDayExpanded ? onZoneLeave : undefined}
                >
                  <div className="divide-y divide-[#F2F4F6] dark:divide-[#2C2C34]">
                    {nextDayUnassigned.length > 0 ? (
                      nextDayUnassigned.map((res) => {
                        const gp = formatGenderPeople(res);
                        return (
                          <div key={`next-pool-${res.id}`} className={`flex items-center h-10 px-1 ${!nextDayExpanded ? 'justify-center' : ''}`}>
                            {nextDayExpanded ? (
                              <div className="group/guest flex items-center h-10 w-full"

                                onContextMenu={(e) => onGuestContextMenu(e, res.id)}
                              >
                                <div
                                  onClick={(e: React.MouseEvent) => onGripClick(e, res.id)}
                                  className={`flex items-center justify-center w-8 px-0.5 flex-shrink-0 cursor-pointer text-[#B0B8C1] dark:text-[#4E5968] transition-all duration-200 ${
                                    selectedGuestIds.has(res.id) ? 'text-[#3182F6]' : 'group-hover/guest:text-[#3182F6]'
                                  }`}
                                >
                                  <span className="relative flex items-center justify-center w-[16px] h-[16px] group/circle">
                                    <span className={`absolute inset-0 rounded-full bg-[#3182F6] transition-all duration-300 ease-out ${
                                      selectedGuestIds.has(res.id) ? 'scale-[0.55] opacity-80' : 'scale-0 opacity-0 group-hover/circle:scale-[0.55] group-hover/circle:opacity-30'
                                    }`} />
                                    <Circle size={16} strokeWidth={1} className={`relative z-10 transition-colors duration-200 ${selectedGuestIds.has(res.id) ? 'text-[#3182F6]' : ''}`} />
                                  </span>
                                </div>
                                <div className="flex-1 grid items-center py-1" style={{ gridTemplateColumns: NEXT_GUEST_COLS }}>
                                  <div className="overflow-hidden px-1">
                                    <InlineInput value={res.customer_name} field="customer_name" resId={res.id}
                                      onSave={(id, f, v) => handleFieldSave(id, f, v, selectedDate.add(1, 'day'))}
                                      className="font-medium text-[#191F28] dark:text-white text-caption" placeholder="이름" disabled={selectionActive} />
                                  </div>
                                  <div className="overflow-hidden px-1">
                                    <InlineInput value={res.phone || ''} field="phone" resId={res.id}
                                      onSave={(id, f, v) => handleFieldSave(id, f, v, selectedDate.add(1, 'day'))}
                                      className="text-[#191F28] dark:text-white tabular-nums text-caption" placeholder="연락처" disabled={selectionActive} />
                                  </div>
                                  <div className="overflow-hidden text-center px-1">
                                    <InlineInput value={res.party_type || ''} field="party_type" resId={res.id}
                                      onSave={(id, f, v) => handleFieldSave(id, f, v, selectedDate.add(1, 'day'))}
                                      className="text-[#191F28] dark:text-white font-medium text-center text-caption" placeholder="-" disabled={selectionActive} />
                                  </div>
                                  <div className="overflow-hidden text-center px-1">
                                    <InlineInput value={gp} field="genderPeople" resId={res.id}
                                      onSave={(id, f, v) => handleFieldSave(id, f, v, selectedDate.add(1, 'day'))}
                                      className="text-[#191F28] dark:text-white font-medium text-center text-caption" placeholder="-" disabled={selectionActive} />
                                  </div>
                                </div>
                              </div>
                            ) : (
                              <div className="flex items-center gap-1.5 truncate">
                                <span className="truncate text-caption text-[#4E5968] dark:text-[#8B95A1]">{res.customer_name}</span>
                                {gp && <span className="flex-shrink-0 text-caption text-[#8B95A1] dark:text-[#4E5968]">{gp}</span>}
                              </div>
                            )}
                          </div>
                        );
                      })
                    ) : (
                      <div className="flex items-center h-10 px-1">
                        <span className="text-caption text-[#FF9500] italic">
                          {dragOverNextPool ? '클릭하면 배정 해제' : ''}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Party-Only */}
              <div
                className={`group flex select-none transition-colors ${
                  dragOverPartyZone
                    ? 'bg-[#7B61FF]/5 dark:bg-[#7B61FF]/8'
                    : partyOnly.length > 0 ? 'bg-white dark:bg-[#1E1E24]' : 'bg-[#F2F4F6]/50 dark:bg-[#17171C]/30'
                } ${selectionActive ? 'cursor-pointer' : ''}`}
                style={{ minHeight: `${Math.max(Math.max(1, partyOnly.length), Math.max(1, nextDayPartyOnly.length)) * 40}px` }}
                data-drop-zone="party"
                onClick={onDropZoneClick}
                onMouseEnter={() => onZoneHover('party')}
                onMouseLeave={onZoneLeave}
              >
                {/* Room label */}
                <div className="flex items-center gap-1.5 flex-shrink-0 w-42 pl-3 pr-2 py-2 border-r border-b border-[#E5E8EB] dark:border-[#2C2C34] bg-white dark:bg-[#1E1E24]">
                  <span className="font-semibold text-[#7B61FF] dark:text-[#7B61FF] text-body">파티만</span>
                </div>

                {/* Guest area */}
                <div className="flex-1 divide-y divide-[#F2F4F6] dark:divide-[#2C2C34] border-b border-[#E5E8EB] dark:border-[#2C2C34]">
                  {partyOnly.length > 0 ? (
                    partyOnly.map((res) => renderGuestRow(res, true))
                  ) : (
                    <div className={`flex items-center h-10 cursor-default`}>
                      <div className="flex-1 grid items-center py-1" style={{ gridTemplateColumns: GUEST_COLS }}>
                        <div className="overflow-hidden truncate col-span-full text-body text-[#7B61FF] dark:text-[#7B61FF] italic px-1.5">
                          {dragOverPartyZone ? '클릭하면 파티만으로 전환' : ''}
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* Next day column for party */}
                <div
                  className={`flex-shrink-0 border-l-8 border-white dark:border-[#2C2C34] shadow-[inset_1px_0_0_#E5E8EB,-1px_0_0_#E5E8EB] z-[2] bg-[#F8F9FA] dark:bg-[#17171C] border-b border-b-[#E5E8EB] dark:border-b-gray-700 transition-all duration-200 ${
                    dragOverNextParty ? 'bg-[#7B61FF]/5 dark:bg-[#7B61FF]/8' : ''
                  } ${selectionActive ? 'cursor-pointer' : ''}`}
                  style={{ width: nextDayExpanded ? NEXT_DAY_EXPANDED_WIDTH : colWidths.nextDay, minHeight: `${Math.max(1, nextDayPartyOnly.length) * 40}px` }}
                  data-drop-zone={nextDayExpanded ? 'next-party' : undefined}
                  onClick={onDropZoneClick}
                  onMouseEnter={nextDayExpanded ? () => onZoneHover('next-party') : undefined}
                  onMouseLeave={nextDayExpanded ? onZoneLeave : undefined}
                >
                  <div className="divide-y divide-[#F2F4F6] dark:divide-[#2C2C34]">
                    {nextDayPartyOnly.length > 0 ? (
                      nextDayPartyOnly.map((res) => {
                        const gp = formatGenderPeople(res);
                        return (
                          <div key={`next-party-${res.id}`} className={`flex items-center h-10 px-1 ${!nextDayExpanded ? 'justify-center' : ''}`}>
                            {nextDayExpanded ? (
                              <div className="group/guest flex items-center h-10 w-full"

                                onContextMenu={(e) => onGuestContextMenu(e, res.id)}
                              >
                                <div
                                  onClick={(e: React.MouseEvent) => onGripClick(e, res.id)}
                                  className={`flex items-center justify-center w-8 px-0.5 flex-shrink-0 cursor-pointer text-[#B0B8C1] dark:text-[#4E5968] transition-all duration-200 ${
                                    selectedGuestIds.has(res.id) ? 'text-[#3182F6]' : 'group-hover/guest:text-[#3182F6]'
                                  }`}
                                >
                                  <span className="relative flex items-center justify-center w-[16px] h-[16px] group/circle">
                                    <span className={`absolute inset-0 rounded-full bg-[#3182F6] transition-all duration-300 ease-out ${
                                      selectedGuestIds.has(res.id) ? 'scale-[0.55] opacity-80' : 'scale-0 opacity-0 group-hover/circle:scale-[0.55] group-hover/circle:opacity-30'
                                    }`} />
                                    <Circle size={16} strokeWidth={1} className={`relative z-10 transition-colors duration-200 ${selectedGuestIds.has(res.id) ? 'text-[#3182F6]' : ''}`} />
                                  </span>
                                </div>
                                <div className="flex-1 grid items-center py-1" style={{ gridTemplateColumns: NEXT_GUEST_COLS }}
                                >
                                  <div className="overflow-hidden px-1">
                                    <InlineInput value={res.customer_name} field="customer_name" resId={res.id}
                                      onSave={(id, f, v) => handleFieldSave(id, f, v, selectedDate.add(1, 'day'))}
                                      className="font-medium text-[#191F28] dark:text-white text-caption" placeholder="이름" disabled={selectionActive} />
                                  </div>
                                  <div className="overflow-hidden px-1">
                                    <InlineInput value={res.phone || ''} field="phone" resId={res.id}
                                      onSave={(id, f, v) => handleFieldSave(id, f, v, selectedDate.add(1, 'day'))}
                                      className="text-[#191F28] dark:text-white tabular-nums text-caption" placeholder="연락처" disabled={selectionActive} />
                                  </div>
                                  <div className="overflow-hidden text-center px-1">
                                    <InlineInput value={res.party_type || ''} field="party_type" resId={res.id}
                                      onSave={(id, f, v) => handleFieldSave(id, f, v, selectedDate.add(1, 'day'))}
                                      className="text-[#191F28] dark:text-white font-medium text-center text-caption" placeholder="-" disabled={selectionActive} />
                                  </div>
                                  <div className="overflow-hidden text-center px-1">
                                    <InlineInput value={gp} field="genderPeople" resId={res.id}
                                      onSave={(id, f, v) => handleFieldSave(id, f, v, selectedDate.add(1, 'day'))}
                                      className="text-[#191F28] dark:text-white font-medium text-center text-caption" placeholder="-" disabled={selectionActive} />
                                  </div>
                                </div>
                              </div>
                            ) : (
                              <div className="flex items-center gap-1.5 truncate">
                                <span className="truncate text-caption text-[#4E5968] dark:text-[#8B95A1]">{res.customer_name}</span>
                                {gp && <span className="flex-shrink-0 text-caption text-[#8B95A1] dark:text-[#4E5968]">{gp}</span>}
                              </div>
                            )}
                          </div>
                        );
                      })
                    ) : (
                      <div className="flex items-center h-10 px-1">
                        <span className="text-caption text-[#7B61FF] italic">
                          {dragOverNextParty ? '클릭하면 파티만으로 전환' : ''}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Unstable */}
              {unstableGuests.length > 0 && (
                <div
                  className="group flex select-none bg-white dark:bg-[#1E1E24]"
                  style={{ minHeight: `${Math.max(1, unstableGuests.length) * 40}px` }}
                >
                  {/* Room label */}
                  <div className="flex items-center gap-1.5 flex-shrink-0 w-42 pl-3 pr-2 py-2 border-r border-b border-[#E5E8EB] dark:border-[#2C2C34] bg-white dark:bg-[#1E1E24]">
                    <span className="font-semibold text-[#FF6B2C] dark:text-[#FF8A50] text-body">언스테이블</span>
                  </div>

                  {/* Guest area */}
                  <div className="flex-1 divide-y divide-[#F2F4F6] dark:divide-[#2C2C34] border-b border-[#E5E8EB] dark:border-[#2C2C34]">
                    {unstableGuests.map((res) => renderGuestRow(res, true, 'unstable'))}
                  </div>

                  {/* Next day column - empty */}
                  <div className="flex-shrink-0 border-l-8 border-white dark:border-[#2C2C34] shadow-[inset_1px_0_0_#E5E8EB,-1px_0_0_#E5E8EB] z-[2] bg-[#F8F9FA] dark:bg-[#17171C] border-b border-b-[#E5E8EB] dark:border-b-gray-700 transition-all duration-200" style={{ width: nextDayExpanded ? NEXT_DAY_EXPANDED_WIDTH : colWidths.nextDay }} />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Guest Form Modal */}
      <Modal show={modalVisible} onClose={() => setModalVisible(false)} size="md">
        <ModalHeader>{editingId ? '게스트 수정' : '예약자 추가'}</ModalHeader>
        <ModalBody>
          <div className="flex flex-col gap-4">
            {!editingId && (
              <div className="flex gap-2">
                {[
                  { value: 'party_only', label: '파티만' },
                  { value: 'manual', label: '객실 포함' },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => {
                      setFormValues({ ...formValues, guest_type: opt.value });
                    }}
                    className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors cursor-pointer
                      ${(formValues.guest_type || 'party_only') === opt.value
                        ? 'bg-[#3182F6] text-white'
                        : 'bg-[#F2F4F6] text-[#4E5968] hover:bg-[#E5E8EB] dark:bg-[#2C2C34] dark:text-white dark:hover:bg-[#2C2C34]'
                      }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            )}

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="customer-name">이름 <span className="text-[#F04452] dark:text-[#F04452]">*</span></Label>
                <TextInput
                  id="customer-name"
                  value={formValues.customer_name || ''}
                  onChange={(e) => setFormValues({ ...formValues, customer_name: e.target.value })}
                  placeholder="이름"
                  sizing="sm"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="phone">전화번호 <span className="text-[#F04452] dark:text-[#F04452]">*</span></Label>
                <TextInput
                  id="phone"
                  value={formValues.phone || ''}
                  onChange={(e) => setFormValues({ ...formValues, phone: e.target.value })}
                  placeholder="010-1234-5678"
                  sizing="sm"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="date">날짜 <span className="text-[#F04452] dark:text-[#F04452]">*</span></Label>
              <div className="flex gap-3 items-center">
                <TextInput
                  id="date"
                  type="date"
                  value={formValues.date || ''}
                  onChange={(e) => setFormValues({ ...formValues, date: e.target.value })}
                  sizing="sm"
                  className="flex-1"
                />
                <label className="flex items-center gap-1.5 cursor-pointer select-none whitespace-nowrap">
                  <input
                    type="checkbox"
                    checked={!!formValues.multi_night}
                    onChange={(e) => setFormValues({ ...formValues, multi_night: e.target.checked, nights: e.target.checked ? (formValues.nights || 2) : null })}
                    className="rounded border-[#E5E8EB] text-[#3182F6] focus:ring-[#3182F6]"
                  />
                  <span className="text-sm text-[#4E5968] dark:text-gray-300">연박</span>
                </label>
                <div className="flex items-center gap-0">
                  <input
                    type="number"
                    min={2}
                    max={30}
                    value={formValues.multi_night ? (formValues.nights || 2) : ''}
                    onChange={(e) => setFormValues({ ...formValues, nights: e.target.value ? Number(e.target.value) : 2 })}
                    disabled={!formValues.multi_night}
                    placeholder="2"
                    className={`w-16 rounded-l-lg border border-r-0 border-[#E5E8EB] dark:border-[#2C2C34] text-sm text-center px-2 py-1.5 focus:border-[#3182F6] focus:ring-[#3182F6] outline-none ${
                      formValues.multi_night
                        ? 'bg-white dark:bg-[#1E1E24] text-[#191F28] dark:text-white'
                        : 'bg-[#F2F4F6] dark:bg-[#2C2C34] text-[#B0B8C1] dark:text-gray-600 cursor-not-allowed'
                    }`}
                  />
                  <span className={`flex-shrink-0 px-2 py-1.5 rounded-r-lg border border-[#E5E8EB] dark:border-[#2C2C34] text-sm font-medium ${
                    formValues.multi_night
                      ? 'bg-[#F2F4F6] dark:bg-[#2C2C34] text-[#4E5968] dark:text-white'
                      : 'bg-[#F2F4F6] dark:bg-[#2C2C34] text-[#B0B8C1] dark:text-gray-600'
                  }`}>박</span>
                </div>
              </div>
            </div>

            <div className="space-y-2">
              <Label>성별 / 인원</Label>
              <div className="flex gap-3">
                <div className="flex items-center gap-0 flex-1">
                  <span className="flex-shrink-0 px-3 py-1.5 rounded-l-lg bg-[#F2F4F6] dark:bg-[#2C2C34] border border-r-0 border-[#E5E8EB] dark:border-[#2C2C34] text-sm font-medium text-[#4E5968] dark:text-white">남</span>
                  <input
                    type="number"
                    min={0}
                    value={formValues.male_count ?? ''}
                    onChange={(e) => setFormValues({ ...formValues, male_count: e.target.value ? Number(e.target.value) : null })}
                    placeholder="0"
                    className="w-full rounded-r-lg rounded-l-none border border-[#E5E8EB] dark:border-[#2C2C34] bg-white dark:bg-[#1E1E24] text-sm text-[#191F28] dark:text-white px-3 py-1.5 focus:border-[#3182F6] focus:ring-[#3182F6] outline-none"
                  />
                </div>
                <div className="flex items-center gap-0 flex-1">
                  <span className="flex-shrink-0 px-3 py-1.5 rounded-l-lg bg-[#F2F4F6] dark:bg-[#2C2C34] border border-r-0 border-[#E5E8EB] dark:border-[#2C2C34] text-sm font-medium text-[#4E5968] dark:text-white">여</span>
                  <input
                    type="number"
                    min={0}
                    value={formValues.female_count ?? ''}
                    onChange={(e) => setFormValues({ ...formValues, female_count: e.target.value ? Number(e.target.value) : null })}
                    placeholder="0"
                    className="w-full rounded-r-lg rounded-l-none border border-[#E5E8EB] dark:border-[#2C2C34] bg-white dark:bg-[#1E1E24] text-sm text-[#191F28] dark:text-white px-3 py-1.5 focus:border-[#3182F6] focus:ring-[#3182F6] outline-none"
                  />
                </div>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="notes">메모</Label>
              <TextInput
                id="notes"
                value={formValues.notes || ''}
                onChange={(e) => setFormValues({ ...formValues, notes: e.target.value })}
                placeholder="메모"
                sizing="sm"
              />
            </div>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button color="light" onClick={() => setModalVisible(false)}>취소</Button>
          <Button color="blue" onClick={handleSubmit} disabled={savingReservation}>
            {savingReservation ? '저장 중...' : '저장'}
          </Button>
        </ModalFooter>
      </Modal>

      {/* Quick Menu — fixed bottom bar */}
      <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 rounded-2xl shadow-lg bg-white dark:bg-[#1E1E24] border border-[#E5E8EB] dark:border-gray-800 px-4 py-2.5">
        <div className="flex items-center gap-3">
          <span className="text-[9px] font-bold tracking-widest leading-tight text-[#B0B8C1] dark:text-[#4E5968]">QUICK<br/>MENU</span>
          <Tooltip content={autoAssigning ? '배정 중...' : '객실 자동 배정'} placement="top">
            <div className="inline-block">
              <button
                onClick={() => setAutoAssignConfirm(true)}
                disabled={autoAssigning}
                className="h-10 w-10 flex items-center justify-center rounded-full bg-[#3182F6] text-white hover:bg-[#1B64DA] active:bg-[#1554B5] disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
              >
                {autoAssigning ? <Spinner size="sm" /> : <BedDouble className="h-[18px] w-[18px]" />}
              </button>
            </div>
          </Tooltip>
          <Tooltip content="파티 게스트 추가" placement="top">
            <div className="inline-block">
              <button
                onClick={handleQuickAddParty}
                className="h-10 w-10 flex items-center justify-center rounded-full bg-white dark:bg-[#2C2C34] border border-[#E5E8EB] dark:border-gray-700 text-[#4E5968] dark:text-gray-300 hover:bg-[#F2F4F6] dark:hover:bg-[#35353E] active:bg-[#E5E8EB] transition-colors cursor-pointer"
              >
                <UserRoundPlus className="h-[18px] w-[18px]" />
              </button>
            </div>
          </Tooltip>
        </div>
      </div>

      {/* Confirm Dialog */}
      <Modal
        show={confirmState.open}
        onClose={() => setConfirmState((s) => ({ ...s, open: false }))}
        size="sm"
      >
        <ModalBody>
          <div className="text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-[#F04452]/10 dark:bg-[#F04452]/10">
              <Trash2 className="h-6 w-6 text-[#F04452]" />
            </div>
            <h3 className="mb-2 text-lg font-semibold text-[#191F28] dark:text-white">{confirmState.title}</h3>
            <p className="mb-5 text-sm text-[#8B95A1] dark:text-[#8B95A1]">{confirmState.content}</p>
            <div className="flex justify-center gap-3">
              <Button
                color="blue"
                onClick={() => {
                  setConfirmState((s) => ({ ...s, open: false }));
                  confirmState.onOk();
                }}
              >
                확인
              </Button>
              <Button
                color="light"
                onClick={() => setConfirmState((s) => ({ ...s, open: false }))}
              >
                취소
              </Button>
            </div>
          </div>
        </ModalBody>
      </Modal>

      {/* Multi-night room move confirmation */}
      <Modal
        show={!!multiNightConfirm?.open}
        onClose={() => setMultiNightConfirm(null)}
        size="sm"
      >
        <ModalBody>
          <div className="text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-[#E8F3FF] dark:bg-[#3182F6]/10">
              <BedDouble className="h-6 w-6 text-[#3182F6]" />
            </div>
            <h3 className="mb-2 text-lg font-semibold text-[#191F28] dark:text-white">연박 객실 이동</h3>
            <p className="mb-5 text-sm text-[#8B95A1] dark:text-[#8B95A1]">
              <span className="font-semibold text-[#191F28] dark:text-white">{multiNightConfirm?.resName}</span> 님을{' '}
              <span className="font-semibold text-[#3182F6]">{multiNightConfirm?.roomNumber}</span>(으)로 이동합니다.
              <br />이후 날짜도 같은 객실로 배정하시겠습니까?
            </p>
            <div className="flex justify-center gap-3">
              <Button
                color="blue"
                onClick={() => multiNightConfirm?.onConfirm(true)}
              >
                전체 날짜 적용
              </Button>
              <Button
                color="light"
                onClick={() => multiNightConfirm?.onConfirm(false)}
              >
                오늘만 적용
              </Button>
              <Button
                color="light"
                onClick={() => setMultiNightConfirm(null)}
              >
                취소
              </Button>
            </div>
          </div>
        </ModalBody>
      </Modal>

      {/* 발송 확인 모달 */}
      <Modal show={!!sendConfirm} onClose={() => setSendConfirm(null)} size="md" popup>
        <ModalHeader />
        <ModalBody>
          <div className="text-center">
            <Send className="mx-auto mb-4 h-10 w-10 text-[#3182F6]" />
            <h3 className="mb-2 text-heading font-semibold text-gray-800 dark:text-white">
              SMS 발송 확인
            </h3>
            <p className="mb-6 text-body text-[#4E5968] dark:text-gray-300">
              {sendConfirm?.type === 'campaign'
                ? `${templateLabels.find(t => t.template_key === selectedTemplateKey)?.name || selectedTemplateKey} — ${targets.length}건을 발송하시겠습니까?`
                : (() => {
                    const r = reservations.find(r => r.id === sendConfirm?.resId);
                    const dateStr = selectedDate.format('YYYY-MM-DD');
                    const todayAssignment = r?.sms_assignments?.find(a => a.template_key === sendConfirm?.templateKey && a.date === dateStr)
                      || r?.sms_assignments?.find(a => a.template_key === sendConfirm?.templateKey);
                    const isSent = todayAssignment ? !!todayAssignment.sent_at : false;
                    return isSent
                      ? `${sendConfirm?.customerName}님의 ${sendConfirm?.templateName} 발송을 취소하시겠습니까?`
                      : `${sendConfirm?.customerName}님에게 ${sendConfirm?.templateName}을(를) 발송하시겠습니까?`;
                  })()}
            </p>
            <div className="flex flex-col items-center gap-4">
              <div className="flex justify-center gap-3">
                <Button color="blue" onClick={() => {
                  if (sendConfirm?.type === 'campaign') {
                    handleSendCampaign();
                  } else if (sendConfirm?.type === 'toggle' && sendConfirm.resId && sendConfirm.templateKey) {
                    setSendConfirm(null);
                    doSmsToggle(sendConfirm.resId, sendConfirm.templateKey);
                  }
                }}>
                  {(() => {
                    const r = reservations.find(r => r.id === sendConfirm?.resId);
                    const dStr = selectedDate.format('YYYY-MM-DD');
                    const ta = r?.sms_assignments?.find(a => a.template_key === sendConfirm?.templateKey && a.date === dStr)
                      || r?.sms_assignments?.find(a => a.template_key === sendConfirm?.templateKey);
                    const isSent = ta ? !!ta.sent_at : false;
                    return isSent ? '발송 취소' : '발송';
                  })()}
                </Button>
                <Button color="light" onClick={() => setSendConfirm(null)}>
                  취소
                </Button>
              </div>
              {sendConfirm?.type === 'toggle' && (() => {
                const r = reservations.find(r => r.id === sendConfirm?.resId);
                const dStr = selectedDate.format('YYYY-MM-DD');
                const ta = r?.sms_assignments?.find(a => a.template_key === sendConfirm?.templateKey && a.date === dStr);
                const isSent = ta ? !!ta.sent_at : false;
                if (isSent) return null;
                return (
                  <button
                    className="text-caption text-[#8B95A1] underline hover:text-[#4E5968] dark:text-gray-500 dark:hover:text-gray-300"
                    onClick={() => {
                      if (sendConfirm.resId && sendConfirm.templateKey) {
                        setSendConfirm(null);
                        doSmsToggle(sendConfirm.resId, sendConfirm.templateKey, true);
                      }
                    }}
                  >
                    발송 없이 완료 처리
                  </button>
                );
              })()}
            </div>
          </div>
        </ModalBody>
      </Modal>

      {/* Slide animations (transform only, no opacity = no flicker) */}
      <style>{`
        @keyframes slideLeft {
          from { transform: translateX(-8px); }
          to   { transform: translateX(0); }
        }
        @keyframes slideRight {
          from { transform: translateX(8px); }
          to   { transform: translateX(0); }
        }
        .date-slide-left  { animation: slideLeft  0.15s ease-out; }
        .date-slide-right { animation: slideRight 0.15s ease-out; }
      `}</style>

      {/* 객실 자동 배정 모달 */}
      <Modal size="md" show={autoAssignConfirm} onClose={() => setAutoAssignConfirm(false)}>
        <ModalHeader>객실 자동 배정</ModalHeader>
        <ModalBody>
          <p className="text-body text-[#4E5968] dark:text-gray-300 mb-4">
            미배정 예약자를 상품 매칭에 따라 객실에 자동 배정합니다.
          </p>
          <p className="text-label font-medium text-[#8B95A1] mb-2">
            배정 대상 ({unassigned.length}명)
          </p>
          {unassigned.length === 0 ? (
            <p className="text-body text-[#8B95A1] py-4 text-center">미배정 예약자가 없습니다.</p>
          ) : (
            <div className="divide-y divide-[#E5E8EB] dark:divide-gray-700">
              {unassigned.map((guest) => (
                <div key={guest.id} className="flex items-center justify-between py-2.5">
                  <div className="flex items-center gap-2">
                    <span className="text-body font-medium text-[#191F28] dark:text-white">
                      {guest.customer_name}
                    </span>
                    <span className="text-caption text-[#8B95A1]">{guest.phone}</span>
                  </div>
                  <span className="text-caption text-[#8B95A1]">
                    {guest.naver_room_type || '-'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </ModalBody>
        <ModalFooter>
          <Button color="light" onClick={() => setAutoAssignConfirm(false)}>
            취소
          </Button>
          <Button color="blue" onClick={handleAutoAssign} disabled={autoAssigning}>
            {autoAssigning ? <><Spinner size="sm" className="mr-2" />배정 중...</> : '배정 진행'}
          </Button>
        </ModalFooter>
      </Modal>

      {/* Table Settings Modal (replaces old Group Settings Modal) */}
      <TableSettingsModal
        show={tableSettingsOpen}
        onClose={() => setTableSettingsOpen(false)}
        customColors={customHighlightColors}
        onSaveCustomColors={async (colors) => {
          await settingsAPI.updateHighlightColors(colors);
          setCustomHighlightColors(colors);
          toast.success('커스텀 색상이 저장되었습니다');
        }}
        activeRoomEntries={activeRoomEntries}
        roomGroups={roomGroups}
        roomInfoMap={roomInfoMap}
        onSaveDividers={async (dividers, dividerColors) => {
          try {
            // Delete all existing groups
            for (const rg of roomGroups) {
              await roomsAPI.deleteGroup(rg.id);
            }

            // Convert dividers → groups
            const roomIds = activeRoomEntries.map(e => e.room_id);
            const groups: { name: string; room_ids: number[]; sort_order: number; color?: string }[] = [];
            let current: number[] = [];
            let groupIdx = 0;

            roomIds.forEach((id, i) => {
              current.push(id);
              if (dividers.has(i) || i === roomIds.length - 1) {
                const existingName = roomGroups[groupIdx]?.name;
                groups.push({
                  name: existingName || `그룹 ${groupIdx + 1}`,
                  room_ids: current,
                  sort_order: groupIdx,
                  color: dividerColors.get(i) || undefined,
                });
                current = [];
                groupIdx++;
              }
            });

            // Only create groups if there are dividers (more than 1 group)
            if (groups.length > 1) {
              for (const g of groups) {
                await roomsAPI.createGroup(g);
              }
            }

            toast.success('구분선 설정이 저장되었습니다');
            setTableSettingsOpen(false);
            await Promise.all([fetchRooms(), fetchRoomGroups()]);
          } catch {
            toast.error('구분선 설정 저장에 실패했습니다');
          }
        }}
        rowColors={rowColors}
        onSaveRowColors={(colors) => {
          setRowColors(colors);
          saveRowColors(colors);
          toast.success('행 스타일이 저장되었습니다');
          setTableSettingsOpen(false);
        }}
      />

      {/* Stay Group Link Modal */}
      <Modal show={showStayGroupModal} onClose={() => setShowStayGroupModal(false)} size="lg">
        <ModalHeader>
          연박 묶기 — 연결할 예약자 선택
        </ModalHeader>
        <ModalBody>
          <div className="space-y-4">
            {/* Chain with bidirectional + buttons */}
            {stayGroupChain.length > 0 && (
              <div className="rounded-xl bg-[#E8F3FF] dark:bg-[#3182F6]/10 p-3">
                <p className="text-caption font-medium text-[#3182F6] mb-2">연박 체인</p>
                <div className="flex flex-wrap items-center gap-2">
                  {/* Left + button */}
                  <button
                    onClick={() => handleStayGroupDirectionChange('left')}
                    className={`w-7 h-7 flex-shrink-0 rounded-lg border-2 border-dashed flex items-center justify-center transition-colors ${
                      stayGroupDirection === 'left'
                        ? 'border-[#3182F6] text-[#3182F6] bg-[#3182F6]/10'
                        : 'border-[#B0B8C1] text-[#B0B8C1] hover:border-[#3182F6] hover:text-[#3182F6]'
                    }`}
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>

                  <Link2 className="h-3.5 w-3.5 text-[#3182F6]" />

                  {/* Chain items */}
                  {stayGroupChain.map((item, idx) => (
                    <span key={item.id} className="flex items-center gap-2">
                      {idx > 0 && <Link2 className="h-3.5 w-3.5 text-[#3182F6]" />}
                      <span className="rounded-lg bg-white dark:bg-[#1E1E24] px-3 py-1.5 shadow-sm text-center">
                        <span className="block text-caption text-[#8B95A1] tabular-nums">{item.check_in_date.slice(5)}~{item.check_out_date?.slice(5)}</span>
                        <span className="block text-caption font-medium text-[#191F28] dark:text-white">{item.customer_name}</span>
                      </span>
                    </span>
                  ))}

                  <Link2 className="h-3.5 w-3.5 text-[#3182F6]" />

                  {/* Right + button */}
                  <button
                    onClick={() => handleStayGroupDirectionChange('right')}
                    className={`w-7 h-7 flex-shrink-0 rounded-lg border-2 border-dashed flex items-center justify-center transition-colors ${
                      stayGroupDirection === 'right'
                        ? 'border-[#3182F6] text-[#3182F6] bg-[#3182F6]/10'
                        : 'border-[#B0B8C1] text-[#B0B8C1] hover:border-[#3182F6] hover:text-[#3182F6]'
                    }`}
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            )}

            {/* SMS warning */}
            {stayGroupChain.length >= 1 && (
              <div className="rounded-xl bg-[#FFF8E1] dark:bg-[#FF9F00]/10 p-3">
                <p className="text-caption text-[#FF9F00] dark:text-[#FFB84D]">
                  연박을 묶으면 SMS 스케줄(마지막 날 발송, 연박 제외 등)이 변경될 수 있습니다.
                </p>
              </div>
            )}

            {/* Date label */}
            <div className="flex items-center gap-2">
              <span className="text-label font-semibold text-[#191F28] dark:text-white">
                {stayGroupDirection === 'left'
                  ? `${dayjs(stayGroupChain[0]?.check_in_date).subtract(1, 'day').format('YYYY-MM-DD')} 예약자`
                  : `${stayGroupChain[stayGroupChain.length - 1]?.check_out_date || ''} 예약자`
                }
              </span>
            </div>

            {/* Reservation list */}
            {stayGroupLoading ? (
              <div className="flex justify-center py-8">
                <Spinner size="md" />
              </div>
            ) : stayGroupDateReservations
                  .filter((r: any) => !stayGroupChain.some(c => c.id === r.id)).length === 0 ? (
              <div className="py-8 text-center text-label text-[#B0B8C1]">해당 날짜에 예약이 없습니다</div>
            ) : (
              <div className="divide-y divide-[#F2F4F6] dark:divide-gray-800 rounded-xl border border-[#E5E8EB] dark:border-gray-700">
                {stayGroupDateReservations
                  .filter((r: any) => !stayGroupChain.some(c => c.id === r.id))
                  .map((r: any) => (
                  <label
                    key={r.id}
                    className={`flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors ${
                      stayGroupSelectedId === r.id
                        ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/10'
                        : 'hover:bg-[#F2F4F6] dark:hover:bg-[#1E1E24]'
                    }`}
                  >
                    <input
                      type="radio"
                      name="stayGroupSelect"
                      checked={stayGroupSelectedId === r.id}
                      onChange={() => setStayGroupSelectedId(r.id)}
                      className="h-4 w-4 text-[#3182F6] border-[#E5E8EB] focus:ring-[#3182F6]"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-body text-[#191F28] dark:text-white">{r.customer_name}</span>
                        <span className="text-caption tabular-nums text-[#8B95A1]">{r.phone}</span>
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-caption text-[#B0B8C1]">{r.check_in_date} ~ {r.check_out_date}</span>
                        {r.stay_group_id && (
                          <Badge color="warning" size="sm">이미 연박 그룹</Badge>
                        )}
                      </div>
                    </div>
                  </label>
                ))}
              </div>
            )}
          </div>
        </ModalBody>
        <ModalFooter>
          <>
              <Button color="light" onClick={() => setShowStayGroupModal(false)}>취소</Button>
              <Button color="light" disabled={!stayGroupSelectedId} onClick={handleStayGroupAddMore}>
                {stayGroupSelectedId ? '+ 선택 추가' : '예약자를 선택하세요'}
              </Button>
              {stayGroupChain.length >= 2 && (
                <Button color="blue" disabled={stayGroupLinking} onClick={handleStayGroupComplete}>
                  {stayGroupLinking ? <><Spinner size="sm" className="mr-2" />묶는 중...</> : `완료 (${stayGroupChain.length}건 연박)`}
                </Button>
              )}
            </>
        </ModalFooter>
      </Modal>

      {/* Extend Stay Conflict Modal */}
      <Modal
        show={!!extendStayConflict?.open}
        onClose={() => setExtendStayConflict(null)}
        size="md"
      >
        <ModalHeader>방 배정 충돌</ModalHeader>
        <ModalBody>
          <div className="space-y-3">
            <p className="text-body text-[#191F28] dark:text-white">
              <span className="font-semibold">{extendStayConflict?.roomNumber}호</span>에 이미 배정된 게스트가 있습니다.
            </p>
            <div className="rounded-lg bg-[#F2F4F6] dark:bg-[#2C2C34] p-3">
              {extendStayConflict?.existingGuests.map((name, i) => (
                <div key={i} className="text-body text-[#4E5968] dark:text-gray-300">{name}</div>
              ))}
            </div>
          </div>
        </ModalBody>
        <ModalFooter>
          <div className="flex gap-2 w-full">
            <Button
              color="blue"
              className="flex-1"
              onClick={async () => {
                if (!extendStayConflict) return;
                try {
                  await api.post(`/api/reservations/${extendStayConflict.newResId}/extend-stay/assign-room`, {
                    new_reservation_id: extendStayConflict.newResId,
                    room_id: extendStayConflict.roomId,
                    date: selectedDate.add(1, 'day').format('YYYY-MM-DD'),
                    move_existing_to_unassigned: false,
                  });
                  toast.success('같은 방에 배정 완료');
                } catch { toast.error('배정 실패'); }
                setExtendStayConflict(null);
                fetchReservations(selectedDate);
              }}
            >
              같은방에 유지
            </Button>
            <Button
              color="light"
              className="flex-1"
              onClick={async () => {
                if (!extendStayConflict) return;
                try {
                  await api.post(`/api/reservations/${extendStayConflict.newResId}/extend-stay/assign-room`, {
                    new_reservation_id: extendStayConflict.newResId,
                    room_id: extendStayConflict.roomId,
                    date: selectedDate.add(1, 'day').format('YYYY-MM-DD'),
                    move_existing_to_unassigned: true,
                  });
                  toast.success('기존 게스트 미배정 → 새 게스트 배정 완료');
                } catch { toast.error('배정 실패'); }
                setExtendStayConflict(null);
                fetchReservations(selectedDate);
              }}
            >
              미배정으로 이동
            </Button>
            <Button
              color="light"
              className="flex-1"
              onClick={() => {
                toast.info('방 배정 없이 연박추가 완료');
                setExtendStayConflict(null);
                fetchReservations(selectedDate);
              }}
            >
              취소
            </Button>
          </div>
        </ModalFooter>
      </Modal>

      {/* Date Change Modal */}
      <Modal
        show={!!dateChangeModal?.open}
        onClose={() => setDateChangeModal(null)}
        size="md"
      >
        <ModalHeader>예약 날짜 변경 — {dateChangeModal?.customerName}</ModalHeader>
        <ModalBody>
          <div className="flex items-end gap-3">
            <div className="flex-1">
              <Label className="mb-1 block text-label font-medium text-[#4E5968] dark:text-gray-300">체크인</Label>
              <TextInput
                type="date"
                value={dateChangeModal?.checkIn || ''}
                onChange={(e) => setDateChangeModal(prev => prev ? { ...prev, checkIn: e.target.value } : null)}
              />
            </div>
            <span className="pb-2 text-[#8B95A1]">~</span>
            <div className="flex-1">
              <Label className="mb-1 block text-label font-medium text-[#4E5968] dark:text-gray-300">체크아웃</Label>
              <TextInput
                type="date"
                value={dateChangeModal?.checkOut || ''}
                onChange={(e) => setDateChangeModal(prev => prev ? { ...prev, checkOut: e.target.value } : null)}
              />
            </div>
          </div>
        </ModalBody>
        <ModalFooter>
          <div className="flex gap-2 justify-end w-full">
            <Button color="light" onClick={() => setDateChangeModal(null)}>취소</Button>
            <Button color="blue" onClick={async () => {
              if (!dateChangeModal) return;
              const { resId, checkIn, checkOut } = dateChangeModal;
              if (!checkIn) { toast.error('체크인 날짜를 입력하세요'); return; }
              if (!checkOut) { toast.error('체크아웃 날짜를 입력하세요'); return; }
              if (checkOut <= checkIn) { toast.error('체크아웃은 체크인 이후여야 합니다'); return; }
              const hadRoom = findReservation(resId)?.res?.room_id;
              try {
                await reservationsAPI.update(resId, {
                  check_in_date: checkIn,
                  check_out_date: checkOut,
                });
                toast.success('예약 날짜 변경 완료');
                if (hadRoom) {
                  toast.info('날짜 변경으로 기존 객실 배정이 해제될 수 있습니다', { duration: 5000 });
                }
                setDateChangeModal(null);
                fetchReservations(selectedDate);
              } catch (err: any) {
                toast.error(err?.response?.data?.detail || '날짜 변경 실패');
              }
            }}>
              변경
            </Button>
          </div>
        </ModalFooter>
      </Modal>

      {/* Context menu */}
      {contextMenu && contextMenuActions && (
        <GuestContextMenu
          position={{ x: contextMenu.x, y: contextMenu.y }}
          targetCount={contextMenuActions.targetCount}
          currentSection={contextMenuActions.currentSection}
          hasStayGroup={contextMenuActions.hasStayGroup}
          isUnstableCopy={contextMenuActions.isUnstableCopy}
          customColors={customHighlightColors}
          onMoveToPool={contextMenuActions.onMoveToPool}
          onMoveToParty={contextMenuActions.onMoveToParty}
          onDelete={contextMenuActions.onDelete}
          onLinkStayGroup={contextMenuActions.onLinkStayGroup}
          onSetColor={contextMenuActions.onSetColor}
          onCopyToUnstable={hasUnstable && !contextMenuActions.isAlreadyCopiedToUnstable && !contextMenuActions.hasRealUnstableBooking ? contextMenuActions.onCopyToUnstable : undefined}
          onRemoveFromUnstable={hasUnstable && contextMenuActions.isAlreadyCopiedToUnstable && !contextMenuActions.hasRealUnstableBooking ? contextMenuActions.onRemoveFromUnstable : undefined}
          onExtendStay={contextMenuActions.onExtendStay}
          onCancelExtendStay={contextMenuActions.onCancelExtendStay}
          onChangeDates={contextMenuActions.onChangeDates}
          onClose={() => setContextMenu(null)}
        />
      )}
    </div>
  );
};

export default RoomAssignment;
