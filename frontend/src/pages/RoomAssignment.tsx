import { useState, useEffect, useCallback, DragEvent, useMemo, useRef } from 'react';
import api, { reservationsAPI, roomsAPI, templatesAPI, templateSchedulesAPI, smsAssignmentsAPI } from '../services/api';
import { useNavigate } from 'react-router-dom';
import dayjs, { Dayjs } from 'dayjs';
import { toast } from 'sonner';
import {
  Badge,
  Button,
  Card,
  Modal,
  ModalHeader,
  ModalBody,
  ModalFooter,
  TextInput,
  Label,
  Spinner,
  Tooltip,
} from 'flowbite-react';
import {
  Send,
  RefreshCw,
  X,
  BedDouble,
  Trash2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  GripVertical,
  Plus,
  UserRoundPlus,
} from 'lucide-react';

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
  section: string;  // 'room', 'unassigned', 'party'
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
}

function isMultiNight(res: Reservation): boolean {
  if (!res.check_out_date || !res.check_in_date) return false;
  const start = dayjs(res.check_in_date);
  const end = dayjs(res.check_out_date);
  return end.diff(start, 'day') > 1;
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
  const [dropdownAbove, setDropdownAbove] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

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
              setDropdownAbove(window.innerHeight - rect.bottom < 200);
            }
            setDropdownOpen(!dropdownOpen);
          }}
          className="inline-flex items-center justify-center w-[18px] h-[18px] rounded border border-dashed border-[#E5E8EB] dark:border-[#2C2C34] text-[#B0B8C1] dark:text-[#8B95A1] hover:border-[#3182F6] hover:text-[#3182F6] dark:hover:border-[#3182F6] dark:hover:text-[#3182F6] transition-colors cursor-pointer"
          title="문자 템플릿 관리"
        >
          <Plus size={10} />
        </button>
        {dropdownOpen && templateLabels.length > 0 && (
          <div className={`absolute right-0 z-50 min-w-[160px] rounded-lg border border-[#E5E8EB] dark:border-[#2C2C34] bg-white dark:bg-[#1E1E24] shadow-lg py-1 ${dropdownAbove ? 'bottom-full mb-1' : 'top-full mt-1'}`}>
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

const InlineInput = ({ value, field, resId, className, placeholder, onSave, autoFocus }: {
  value: string;
  field: string;
  resId: number;
  className?: string;
  placeholder?: string;
  onSave: (resId: number, field: string, value: string) => void;
  autoFocus?: boolean;
}) => {
  const [localValue, setLocalValue] = useState(value);
  useEffect(() => setLocalValue(value), [value]);
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
  const navigate = useNavigate();
  const [selectedDate, setSelectedDate] = useState<Dayjs>(dayjs());
  const [reservations, setReservations] = useState<Reservation[]>([]);
  // Track which section unassigned reservations belong to: 'party' or 'unassigned'
  const [sectionOverrides, setSectionOverrides] = useState<Record<number, 'party' | 'unassigned'>>({});
  const [nextDayReservations, setNextDayReservations] = useState<Reservation[]>([]);
  const [rooms, setRooms] = useState<any[]>([]);
  const [animDirection, setAnimDirection] = useState<'none' | 'left' | 'right'>('none');
  const [loading, setLoading] = useState(false);
  const [dragOverRoom, setDragOverRoom] = useState<number | null>(null);
  const [dragOverPool, setDragOverPool] = useState(false);
  const [dragOverPartyZone, setDragOverPartyZone] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [dragOverTrash, setDragOverTrash] = useState(false);
  const [recentlyMovedId, setRecentlyMovedId] = useState<number | null>(null);
  const [processing, setProcessing] = useState(false);
  const [quickAddedId, setQuickAddedId] = useState<number | null>(null);

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

  const [partyValues, setPartyValues] = useState<Record<number, string>>({});
  const [templateLabels, setTemplateLabels] = useState<{template_key: string; name: string; short_label: string | null}[]>([]);

  const handleFieldSave = async (resId: number, field: string, value: string) => {
    if (field === 'party_type') {
      try {
        await reservationsAPI.updateDailyInfo(resId, { date: selectedDate.format('YYYY-MM-DD'), party_type: value || null });
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
  const [resizeCol, setResizeCol] = useState<string | null>(null);
  const [resizeGuideX, setResizeGuideX] = useState<number | null>(null);
  const resizeStartXRef = useRef(0);
  const resizeStartWidthRef = useRef(0);
  const tableContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    localStorage.setItem('roomAssignment_colWidths', JSON.stringify(colWidths));
  }, [colWidths]);

  const GUEST_COLS = useMemo(() => {
    return `${colWidths.name}px ${colWidths.phone}px ${colWidths.party}px ${colWidths.gender}px ${colWidths.roomType}px ${colWidths.notes}px minmax(${colWidths.sms}px, 1fr)`;
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

  const fetchRooms = useCallback(async () => {
    try {
      const res = await roomsAPI.getAll();
      setRooms(res.data);
    } catch {
      toast.error('객실 목록을 불러오지 못했습니다.');
    }
  }, []);

  const fetchPreviews = useCallback(async (date: Dayjs) => {
    const fetchOne = async (d: Dayjs, setter: (data: Reservation[]) => void) => {
      try {
        const res = await reservationsAPI.getAll({ date: d.format('YYYY-MM-DD'), limit: 200 });
        setter(res.data.filter((r: Reservation) => r.status !== 'cancelled'));
      } catch {
        setter([]);
      }
    };
    fetchOne(date.add(1, 'day'), setNextDayReservations);
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

      // autoAssign은 백그라운드로 분리 (UI 블로킹 안 함)
      templateSchedulesAPI.autoAssign(dateStr).catch(() => {});

      // 당일 먼저 로딩
      const current = await reservationsAPI.getAll({ date: dateStr, limit: 200 });
      const curr = filterActive(current.data);
      setReservations(curr);
      reservationsRef.current = curr;
      prevDateRef.current = date;
      setLoading(false);

      // 다음날 백그라운드 fetch
      reservationsAPI.getAll({ date: date.add(1, 'day').format('YYYY-MM-DD'), limit: 200 })
        .then(res => { const d = filterActive(res.data); setNextDayReservations(d); nextDayRef.current = d; })
        .catch(() => { setNextDayReservations([]); nextDayRef.current = []; });
    } catch {
      toast.error('예약 목록을 불러오지 못했습니다.');
      setLoading(false);
    }
  }, [filterActive]);

  useEffect(() => {
    fetchRooms();
  }, [fetchRooms]);

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


  const { assignedRooms, unassigned, partyOnly } = useMemo(() => {
    const assigned = new Map<number, Reservation[]>();
    const unassignedList: Reservation[] = [];
    const partyOnlyList: Reservation[] = [];

    reservations.forEach((res) => {
      if (res.room_id) {
        // Has a room assigned → goes to that room's row
        const list = assigned.get(res.room_id) || [];
        list.push(res);
        assigned.set(res.room_id, list);
      } else if (sectionOverrides[res.id] === 'party' || (sectionOverrides[res.id] === undefined && res.section === 'party')) {
        partyOnlyList.push(res);
      } else {
        unassignedList.push(res);
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
    };
  }, [reservations, sectionOverrides]);

  const onDragStart = (e: DragEvent, resId: number) => {
    e.dataTransfer.setData('text/plain', String(resId));
    e.dataTransfer.effectAllowed = 'move';
    setDragActive(true);

    // Custom small drag ghost — show guest name in a compact pill
    const res = reservations.find((r) => r.id === resId);
    const ghost = document.createElement('div');
    ghost.textContent = res?.customer_name || '이동';
    ghost.style.cssText = 'position:fixed;top:-100px;left:-100px;padding:4px 12px;border-radius:8px;background:#3182F6;color:#fff;font-size:13px;font-weight:600;white-space:nowrap;pointer-events:none;z-index:9999;';
    document.body.appendChild(ghost);
    e.dataTransfer.setDragImage(ghost, ghost.offsetWidth / 2, ghost.offsetHeight / 2);
    requestAnimationFrame(() => document.body.removeChild(ghost));
  };

  const onDragEnd = () => {
    setDragActive(false);
    setDragOverTrash(false);
  };

  const onRoomDragOver = (e: DragEvent, roomId: number) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (dragOverRoom !== roomId) setDragOverRoom(roomId);
  };
  const onRoomDragLeave = (e: DragEvent) => {
    // Only clear if actually leaving the room container (not entering a child)
    const related = e.relatedTarget as Node | null;
    if (!related || !e.currentTarget.contains(related)) {
      setDragOverRoom(null);
    }
  };

  const doAssignRoom = async (resId: number, roomId: number, roomNumber: string, applySubsequent: boolean, applyGroup: boolean = false) => {
    // Optimistic update: move guest to new room + auto-assign room_info SMS tag
    setReservations((prev) =>
      prev.map((r) => {
        if (r.id !== resId) return r;
        const hasRoomInfo = r.sms_assignments?.some((a) => a.template_key === 'room_info');
        const updatedAssignments = hasRoomInfo
          ? r.sms_assignments
          : [...(r.sms_assignments || []), { id: 0, reservation_id: r.id, template_key: 'room_info', assigned_at: new Date().toISOString(), sent_at: null, assigned_by: 'auto', date: selectedDate.format('YYYY-MM-DD') } as SmsAssignment];
        return { ...r, room_id: roomId, room_number: roomNumber, sms_assignments: updatedAssignments };
      })
    );
    setSectionOverrides((prev) => { const next = { ...prev }; delete next[resId]; return next; });

    try {
      const { data: result } = await reservationsAPI.assignRoom(resId, {
        room_id: roomId,
        date: selectedDate.format('YYYY-MM-DD'),
        apply_subsequent: applySubsequent,
        apply_group: applyGroup,
      });
      toast.success(`${roomNumber} 배정 완료`);
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

  const onRoomDrop = async (e: DragEvent, roomId: number, roomNumber: string) => {
    e.preventDefault();
    setDragOverRoom(null);
    const resId = Number(e.dataTransfer.getData('text/plain'));
    if (!resId) return;
    const currentList = assignedRooms.get(roomId) || [];
    if (currentList.some((r) => r.id === resId)) return;

    const res = reservations.find((r) => r.id === resId);
    if (!res) return;

    // Multi-night or consecutive-stay guest: ask whether to apply to all dates
    if (isMultiNight(res) || !!res.stay_group_id) {
      setMultiNightConfirm({
        open: true,
        resId,
        resName: res.customer_name,
        roomId,
        roomNumber,
        onConfirm: (applySubsequent) => {
          setMultiNightConfirm(null);
          doAssignRoom(resId, roomId, roomNumber, applySubsequent, !!res.stay_group_id && applySubsequent);
        },
      });
      return;
    }

    // Single-night: assign directly (apply_subsequent doesn't matter)
    await doAssignRoom(resId, roomId, roomNumber, true);
  };

  const onPoolDragOver = (e: DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (!dragOverPool) setDragOverPool(true);
  };
  const onPoolDragLeave = (e: DragEvent) => {
    const related = e.relatedTarget as Node | null;
    if (!related || !e.currentTarget.contains(related)) {
      setDragOverPool(false);
    }
  };

  const onPoolDrop = async (e: DragEvent) => {
    e.preventDefault();
    setDragOverPool(false);
    const resId = Number(e.dataTransfer.getData('text/plain'));
    if (!resId) return;
    const res = reservations.find((r) => r.id === resId);
    if (!res) return;
    setRecentlyMovedId(resId);

    // Already in unassigned section → nothing to do
    const effectiveSectionPool = sectionOverrides[resId] ?? res.section;
    if (!res.room_id && effectiveSectionPool === 'unassigned') return;

    if (res.room_id) {
      // Optimistic update: clear room + remove unsent room_info tag
      setReservations((prev) =>
        prev.map((r) => {
          if (r.id !== resId) return r;
          const filtered = r.sms_assignments?.filter((a) => !(a.template_key === 'room_info' && !a.sent_at)) || [];
          return { ...r, room_id: null, room_number: null, sms_assignments: filtered };
        })
      );
      setSectionOverrides((prev) => ({ ...prev, [resId]: 'unassigned' }));

      try {
        await reservationsAPI.assignRoom(resId, { room_id: null, date: selectedDate.format('YYYY-MM-DD'), apply_subsequent: true });
        // unassign_room sets section by naver_room_type; override to 'unassigned' explicitly
        await reservationsAPI.update(resId, { section: 'unassigned' });
        toast.success('미배정으로 이동');
        fetchReservations(selectedDate);
      } catch {
        toast.error('배정 해제에 실패했습니다.');
        await fetchReservations(selectedDate);
      }
    } else {
      // Section move (party → unassigned): update DB
      setSectionOverrides((prev) => ({ ...prev, [resId]: 'unassigned' }));
      toast.success('미배정으로 이동');
      try {
        await reservationsAPI.update(resId, { section: 'unassigned' });
        fetchReservations(selectedDate);
      } catch {
        // Revert optimistic update on failure
        setSectionOverrides((prev) => {
          const next = { ...prev };
          delete next[resId];
          return next;
        });
        toast.error('이동 실패');
      }
    }
  };

  const onPartyZoneDragOver = (e: DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (!dragOverPartyZone) setDragOverPartyZone(true);
  };

  const onPartyZoneDragLeave = (e: DragEvent) => {
    const related = e.relatedTarget as Node | null;
    if (!related || !e.currentTarget.contains(related)) {
      setDragOverPartyZone(false);
    }
  };

  const onPartyZoneDrop = async (e: DragEvent) => {
    e.preventDefault();
    setDragOverPartyZone(false);
    const resId = Number(e.dataTransfer.getData('text/plain'));
    if (!resId) return;
    setRecentlyMovedId(resId);

    const guest = reservations.find((r) => r.id === resId);
    if (!guest) return;

    // Already in party section → nothing to do
    const effectiveSectionParty = sectionOverrides[resId] ?? guest.section;
    if (!guest.room_id && effectiveSectionParty === 'party') return;

    if (guest.room_id) {
      // Optimistic update: clear room + remove unsent room_info tag
      setReservations((prev) =>
        prev.map((r) => {
          if (r.id !== resId) return r;
          const filtered = r.sms_assignments?.filter((a) => !(a.template_key === 'room_info' && !a.sent_at)) || [];
          return { ...r, room_id: null, room_number: null, sms_assignments: filtered };
        })
      );
      setSectionOverrides((prev) => ({ ...prev, [resId]: 'party' }));

      try {
        await reservationsAPI.assignRoom(resId, { room_id: null, date: selectedDate.format('YYYY-MM-DD'), apply_subsequent: true });
        // unassign_room sets section by naver_room_type; override to 'party' explicitly
        await reservationsAPI.update(resId, { section: 'party' });
        toast.success('파티만으로 이동');
        fetchReservations(selectedDate);
      } catch {
        toast.error('이동 실패');
        await fetchReservations(selectedDate);
      }
    } else {
      // Section move (unassigned → party): update DB
      setSectionOverrides((prev) => ({ ...prev, [resId]: 'party' }));
      toast.success('파티만으로 이동');
      try {
        await reservationsAPI.update(resId, { section: 'party' });
        fetchReservations(selectedDate);
      } catch {
        // Revert optimistic update on failure
        setSectionOverrides((prev) => {
          const next = { ...prev };
          delete next[resId];
          return next;
        });
        toast.error('이동 실패');
      }
    }
  };

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

  // Row drag state — returns Tailwind cursor class
  const guestAreaCursor = (): string => {
    return 'cursor-default';
  };

  const renderGuestRow = (res: Reservation, showGrip: boolean) => {
    const genderPeople = formatGenderPeople(res);
    const longStay = !!res.is_long_stay;

    return (
      <div key={res.id} className={`group/guest flex items-center h-10 ${showGrip ? '' : 'pl-7'} transition-colors duration-150 ${longStay ? 'bg-[#FFF0E0] dark:bg-[#FF9500]/15 hover:bg-[#FFE4CC] dark:hover:bg-[#FF9500]/20' : 'hover:bg-[#E8F3FF] dark:hover:bg-[#3182F6]/8'} ${guestAreaCursor()}`}>
        {showGrip && (
          <div
            draggable
            onDragStart={(e) => onDragStart(e, res.id)}
            onDragEnd={onDragEnd}
            className={`flex items-center justify-center w-7 px-0.5 flex-shrink-0 cursor-grab active:cursor-grabbing text-[#B0B8C1] dark:text-[#4E5968] transition-all duration-200 ${longStay ? 'group-hover/guest:text-[#FFB366] dark:group-hover/guest:text-[#FFB366]' : 'group-hover/guest:text-[#3182F6] dark:group-hover/guest:text-[#3182F6]'}`}
          >
            <GripVertical size={14} />
          </div>
        )}
        <div
          className="flex-1 grid items-center py-1.5"
          style={{ gridTemplateColumns: GUEST_COLS }}
        >
          <div className="overflow-hidden px-1.5">
            <InlineInput value={res.customer_name} field="customer_name" resId={res.id} onSave={handleFieldSave} className="font-medium text-[#191F28] dark:text-white" placeholder="이름" autoFocus={res.id === quickAddedId} />
          </div>
          <div className="overflow-hidden px-1.5">
            <InlineInput value={res.phone} field="phone" resId={res.id} onSave={handleFieldSave} className="text-[#8B95A1] dark:text-[#8B95A1] tabular-nums" placeholder="연락처" />
          </div>
          <div className="overflow-hidden text-center px-1.5">
            <InlineInput value={res.party_type || ''} field="party_type" resId={res.id} onSave={handleFieldSave} className="text-[#4E5968] dark:text-white font-medium text-center" placeholder="-" />
          </div>
          <div className="overflow-hidden text-center px-1.5">
            <InlineInput value={genderPeople} field="genderPeople" resId={res.id} onSave={handleFieldSave} className="text-[#4E5968] dark:text-white font-medium text-center" placeholder="-" />
          </div>
          <div className="overflow-hidden truncate text-body text-[#8B95A1] dark:text-[#8B95A1] text-center px-1.5">{res.naver_room_type || <span className="text-[#B0B8C1] dark:text-[#4E5968]">-</span>}</div>
          <div className="overflow-hidden px-1.5">
            <InlineInput value={res.notes || ''} field="notes" resId={res.id} onSave={handleFieldSave} className="text-[#8B95A1] dark:text-[#8B95A1]" placeholder="" />
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
    const guestsRaw = assignedRooms.get(room_id) || [];
    const isDragOver = dragOverRoom === room_id;
    const nextGuestsRaw = nextDayRoomMap.get(room_id) || [];

    // 도미토리: 연박자를 윗행에 고정, 날짜간 행 위치 통일
    let guests = guestsRaw;
    let nextGuests = nextGuestsRaw;
    if (isDormitory) {
      // 연박자(2박+ 예약 또는 연속 예약 그룹)를 윗행에, 1박만 아래로
      const todayIds = new Set(guestsRaw.map(g => g.id));
      const nextIds = new Set(nextGuestsRaw.map(g => g.id));
      const isStayingGuest = (g: Reservation) => !!g.is_long_stay;

      // 오늘: 연박자 먼저 → ID순, 그 다음 1박만 → ID순
      const todayContinuing = [...guestsRaw].filter(g => isStayingGuest(g)).sort((a, b) => a.id - b.id);
      const todayOnly = [...guestsRaw].filter(g => !isStayingGuest(g)).sort((a, b) => a.id - b.id);
      const guestsSorted = [...todayContinuing, ...todayOnly];

      // 내일: 연박자는 오늘과 같은 행 순서 유지, 신규는 아래에
      const continuingIds = todayContinuing.map(g => g.id);
      const nextIsStaying = (g: Reservation) => !!g.is_long_stay;
      const nextContinuing = continuingIds.map(id => nextGuestsRaw.find(g => g.id === id)).filter(Boolean) as Reservation[];
      const nextOnlyContinuing = [...nextGuestsRaw].filter(g => nextIsStaying(g) && !continuingIds.includes(g.id)).sort((a, b) => a.id - b.id);
      const nextNew = [...nextGuestsRaw].filter(g => !nextIsStaying(g)).sort((a, b) => a.id - b.id);
      const nextSorted = [...nextContinuing, ...nextOnlyContinuing, ...nextNew];
      guests = guestsSorted;
      nextGuests = nextSorted;
    }

    const maxOccupancy = Math.max(guests.length, nextGuests.length, 1);
    const visibleRows = isDormitory
      ? Math.min(bed_capacity, maxOccupancy)
      : Math.max(1, guests.length);
    const totalRows = visibleRows;
    const stripeBg = rowIndex % 2 === 0 ? 'bg-white dark:bg-[#1E1E24]' : 'bg-[#F8F9FA] dark:bg-[#17171C]';

    return (
      <div
        key={room_id}
        className={`group flex select-none transition-colors
          ${isDragOver
            ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/8 ring-1 ring-inset ring-[#3182F6]/30 dark:ring-[#3182F6]/30'
            : stripeBg
          }`}
        style={{ minHeight: `${totalRows * 40}px` }}
        onDragOver={(e) => onRoomDragOver(e, room_id)}
        onDragLeave={onRoomDragLeave}
        onDrop={(e) => onRoomDrop(e, room_id, room_number)}
      >
        {/* Room label - vertically centered, spans all rows */}
        <div className="flex items-center gap-1.5 flex-shrink-0 w-42 pl-3 pr-2 py-2 border-r border-b border-[#E5E8EB] dark:border-[#2C2C34] bg-white dark:bg-[#1E1E24]">
          <span className="font-semibold text-[#191F28] dark:text-white text-body">{room_number}</span>
          {roomInfoMap[room_number] && (
            <span className="text-caption text-[#B0B8C1] dark:text-[#8B95A1] truncate">{roomInfoMap[room_number]}</span>
          )}
        </div>

        {/* Guest rows */}
        <div className="flex-1 divide-y divide-[#F2F4F6] dark:divide-[#2C2C34] border-b border-[#E5E8EB] dark:border-[#2C2C34]">
          {isDormitory ? (
            // Dormitory: show beds as rows, filled or empty
            Array.from({ length: totalRows }).map((_, i) => {
              const guest = guests[i];
              if (guest) {
                return renderGuestRow(guest, true);
              }
              return (
                <div key={`empty-${i}`} className={`flex items-center h-10 ${guestAreaCursor()}`}>
                  <div
                    className="flex-1 grid items-center py-1.5"
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
            <div className={`flex items-center h-10 ${guestAreaCursor()}`}>
              <div
                className="flex-1 grid items-center py-1.5"
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
        <div className={`flex-shrink-0 border-l-8 border-white dark:border-[#2C2C34] shadow-[inset_1px_0_0_#E5E8EB,-1px_0_0_#E5E8EB] z-[2] border-b border-b-[#E5E8EB] dark:border-b-gray-700 ${stripeBg}`} style={{ width: colWidths.nextDay }}>
          <div className="divide-y divide-[#F2F4F6] dark:divide-[#2C2C34]">
            {Array.from({ length: totalRows }).map((_, i) => {
              const nextGuest = nextGuests[i];
              const gp = nextGuest ? formatGenderPeople(nextGuest) : '';
              return (
                <div key={`next-${i}`} className={`flex items-center justify-center h-10 px-1 ${nextGuest?.is_long_stay ? 'bg-[#FFF0E0] dark:bg-[#FF9500]/15' : ''}`}>
                  {nextGuest ? (
                    <div className="flex items-center gap-1.5 truncate">
                      <span className="truncate text-caption text-[#4E5968] dark:text-[#8B95A1]">{nextGuest.customer_name}</span>
                      {gp && <span className="flex-shrink-0 text-caption text-[#8B95A1] dark:text-[#4E5968]">{gp}</span>}
                    </div>
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
          .catch(() => ({ data: [] }))
          .then((res: any) => {
            const nextData = filterActive(res.data);
            reservationsRef.current = newCurrent;
            nextDayRef.current = nextData;
            setReservations(newCurrent);
            setNextDayReservations(nextData);
          });
      } else {
        // 폴백: 당일 먼저
        dataPromise = reservationsAPI.getAll({ date: dateStr, limit: 200 })
          .then((res) => {
            const curr = filterActive(res.data);
            reservationsRef.current = curr;
            setReservations(curr);
            // 다음날 백그라운드
            reservationsAPI.getAll({ date: newDate.add(1, 'day').format('YYYY-MM-DD'), limit: 200 })
              .then(r => { const d = filterActive(r.data); setNextDayReservations(d); nextDayRef.current = d; })
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

  // suppress unused navigate warning — keep for future routing
  void navigate;
  // suppress unused handleEditGuest warning — used via modal open
  void handleEditGuest;

  // Summary stats
  const summary = useMemo(() => {
    // Room guest totals
    let roomTotal = 0, roomMale = 0, roomFemale = 0;
    for (const r of reservations) {
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

    return {
      roomTotal, roomMale, roomFemale,
      partyTotal, partyMale, partyFemale,
      firstTotal, firstMale, firstFemale,
      secondOnlyTotal, secondOnlyMale, secondOnlyFemale,
      conversionRate, genderRatio,
    };
  }, [reservations]);

  return (
    <div className={`space-y-4 pb-14 ${processing ? 'opacity-60 pointer-events-none' : ''}`}>

      {/* Page header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="page-title">객실 배정</h1>
          <p className="page-subtitle">날짜별 객실을 배정하고 SMS를 발송하세요</p>
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
                <Spinner size="xs" className="mr-1.5" />
              ) : (
                <Send className="h-3.5 w-3.5 mr-1.5" />
              )}
              발송 ({targets.length}건)
            </Button>


          </div>

          {targets.length > 0 && (
            <div className="mt-3 rounded-lg border border-[#E5E8EB] dark:border-[#2C2C34] bg-[#F8F9FA] dark:bg-[#17171C] p-3">
              <div className="flex justify-between items-center mb-2">
                <Badge color="blue" size="sm">발송 대상 {targets.length}건</Badge>
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
      <div className="section-card !overflow-visible">
        {/* Date navigation header */}
        <div className="section-header justify-center">
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
              <div className="flex items-center h-10 bg-[#F2F4F6] dark:bg-[#17171C] border-b border-[#F2F4F6] dark:border-[#2C2C34]">
                <div className="flex-shrink-0 pl-3 pr-2 w-42 border-r border-[#F2F4F6] dark:border-[#2C2C34]">
                  <span className="text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">객실</span>
                </div>
                <div className="w-7 flex-shrink-0" />
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
                <div className="relative flex-shrink-0 px-2 text-center border-l-8 border-white dark:border-[#2C2C34] shadow-[inset_1px_0_0_#E5E8EB,-1px_0_0_#E5E8EB] z-[2] flex items-center justify-center self-stretch" style={{ width: colWidths.nextDay }}>
                  <div onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); resizeStartXRef.current = e.clientX; resizeStartWidthRef.current = colWidths.nextDay; setResizeCol('nextDay'); }} className="absolute left-0 top-0 bottom-0 w-2 cursor-col-resize z-10 before:content-[''] before:absolute before:left-0 before:top-1 before:bottom-1 before:w-px before:bg-[#D1D5DB] dark:before:bg-[#4E5968] hover:before:bg-[#3182F6] active:before:bg-[#3182F6]" />
                  <span className="text-caption font-semibold text-[#8B95A1] dark:text-[#8B95A1]">{selectedDate.add(1, 'day').format('M/D')}</span>
                </div>
              </div>

              {/* Room Rows (stale-while-revalidate: 이전 데이터 유지, 새 데이터 조용히 교체) */}
              <div className={loading ? 'pointer-events-none' : ''}>
                {activeRoomEntries.map((entry, idx) => renderRoomRow(entry, idx))}
              </div>

              {/* Unassigned Pool */}
              <div
                className={`group flex select-none transition-colors ${
                  dragOverPool
                    ? 'bg-[#FF9500]/50 dark:bg-[#FF9500]/8'
                    : unassigned.length > 0 ? 'bg-white dark:bg-[#1E1E24]' : 'bg-[#F2F4F6]/50 dark:bg-[#17171C]/30'
                }`}
                style={{ minHeight: `${Math.max(1, unassigned.length) * 40}px` }}
                onDragOver={onPoolDragOver}
                onDragLeave={onPoolDragLeave}
                onDrop={onPoolDrop}
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
                    <div className={`flex items-center h-10 ${guestAreaCursor()}`}>
                      <div className="flex-1 grid items-center py-1.5" style={{ gridTemplateColumns: GUEST_COLS }}>
                        <div className="overflow-hidden truncate col-span-full text-body text-[#FF9500] dark:text-[#FF9500] italic px-1.5">
                          {dragOverPool ? '여기에 놓으면 배정 해제' : ''}
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* Next day column - empty */}
                <div className="flex-shrink-0 border-l-8 border-white dark:border-[#2C2C34] shadow-[inset_1px_0_0_#E5E8EB,-1px_0_0_#E5E8EB] z-[2] bg-[#F8F9FA] dark:bg-[#17171C] border-b border-b-[#E5E8EB] dark:border-b-gray-700" style={{ width: colWidths.nextDay }} />
              </div>

              {/* Party-Only */}
              <div
                className={`group flex select-none transition-colors ${
                  dragOverPartyZone
                    ? 'bg-[#7B61FF]/5 dark:bg-[#7B61FF]/8'
                    : partyOnly.length > 0 ? 'bg-white dark:bg-[#1E1E24]' : 'bg-[#F2F4F6]/50 dark:bg-[#17171C]/30'
                }`}
                style={{ minHeight: `${Math.max(1, partyOnly.length) * 40}px` }}
                onDragOver={onPartyZoneDragOver}
                onDragLeave={onPartyZoneDragLeave}
                onDrop={onPartyZoneDrop}
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
                    <div className={`flex items-center h-10 ${guestAreaCursor()}`}>
                      <div className="flex-1 grid items-center py-1.5" style={{ gridTemplateColumns: GUEST_COLS }}>
                        <div className="overflow-hidden truncate col-span-full text-body text-[#7B61FF] dark:text-[#7B61FF] italic px-1.5">
                          {dragOverPartyZone ? '여기에 놓으면 파티만 게스트로 전환' : ''}
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* Next day column - empty */}
                <div className="flex-shrink-0 border-l-8 border-white dark:border-[#2C2C34] shadow-[inset_1px_0_0_#E5E8EB,-1px_0_0_#E5E8EB] z-[2] bg-[#F8F9FA] dark:bg-[#17171C] border-b border-b-[#E5E8EB] dark:border-b-gray-700" style={{ width: colWidths.nextDay }} />
              </div>
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
          <Button color="blue" onClick={handleSubmit} disabled={savingReservation}>
            {savingReservation ? '저장 중...' : '저장'}
          </Button>
          <Button color="light" onClick={() => setModalVisible(false)}>취소</Button>
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
          <Tooltip content={dragOverTrash ? '놓으면 삭제됩니다' : '게스트를 드래그하여 삭제'} placement="top">
            <div className="inline-block">
              <div
                onDragOver={(e: React.DragEvent) => {
                  e.preventDefault();
                  e.dataTransfer.dropEffect = 'move';
                  if (!dragOverTrash) setDragOverTrash(true);
                }}
                onDragLeave={(e: React.DragEvent) => {
                  const related = e.relatedTarget as Node | null;
                  if (!related || !e.currentTarget.contains(related)) {
                    setDragOverTrash(false);
                  }
                }}
                onDrop={(e: React.DragEvent) => {
                  e.preventDefault();
                  setDragOverTrash(false);
                  setDragActive(false);
                  const resId = Number(e.dataTransfer.getData('text/plain'));
                  if (resId) handleDeleteGuest(resId);
                }}
                className={`flex items-center justify-center rounded-full transition-all duration-300 ${
                  dragOverTrash
                    ? 'h-12 w-12 bg-[#F04452] text-white scale-110 shadow-lg shadow-[#F04452]/40 ring-4 ring-[#F04452]/20'
                    : dragActive
                      ? 'h-12 w-12 bg-[#FFEBEE] dark:bg-[#F04452]/15 text-[#F04452] border-2 border-[#F04452] animate-bounce'
                      : 'h-10 w-10 bg-white dark:bg-[#2C2C34] border border-[#E5E8EB] dark:border-gray-700 text-[#8B95A1] dark:text-gray-400'
                }`}
              >
                <Trash2 className={`transition-all duration-300 ${dragActive ? 'h-5 w-5' : 'h-[18px] w-[18px]'}`} />
              </div>
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
        <ModalFooter className="justify-end">
          <Button color="light" onClick={() => setAutoAssignConfirm(false)}>
            취소
          </Button>
          <Button color="blue" onClick={handleAutoAssign} disabled={autoAssigning}>
            {autoAssigning ? <><Spinner size="sm" className="mr-2" />배정 중...</> : '배정 진행'}
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
};

export default RoomAssignment;
