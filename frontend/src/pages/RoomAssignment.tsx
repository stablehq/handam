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
} from 'flowbite-react';
import {
  Send,
  RefreshCw,
  X,
  UserPlus,
  Trash2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  GripVertical,
  Plus,
} from 'lucide-react';

interface SmsAssignment {
  id: number;
  reservation_id: number;
  template_key: string;
  assigned_at: string;
  sent_at: string | null;
  assigned_by: string;
}

interface Reservation {
  id: number;
  customer_name: string;
  phone: string;
  check_in_date: string;
  check_in_time: string;
  status: string;
  room_number: string | null;
  room_password: string | null;
  room_assigned_by: string | null;
  naver_room_type: string | null;
  gender: string | null;
  male_count: number | null;
  female_count: number | null;
  party_size: number | null;
  party_type: string | null;  // '1'=1차만, '2'=1+2차, '2차만'
  tags: string | null;
  notes: string | null;
  check_out_date: string | null;
  booking_source?: string;
  sms_assignments: SmsAssignment[];
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
  onToggle: (resId: number, templateKey: string) => void;
  onAssign: (resId: number, templateKey: string) => void;
  onRemove: (resId: number, templateKey: string) => void;
}

const SmsCell: React.FC<SmsCellProps> = ({ reservation, templateLabels, onToggle, onAssign, onRemove }) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [showArrows, setShowArrows] = useState(false);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const assignments = [...(reservation.sms_assignments || [])].sort((a, b) => {
    const ai = templateLabels.findIndex(t => t.template_key === a.template_key);
    const bi = templateLabels.findIndex(t => t.template_key === b.template_key);
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });

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
            return (
              <span
                key={a.template_key}
                title={getFullName(a.template_key)}
                className={`inline-flex items-center px-1.5 py-1 rounded text-[11px] leading-tight font-medium whitespace-nowrap cursor-pointer transition-all
                  ${isSent
                    ? 'bg-[#E8F3FF] text-[#3182F6] dark:bg-[#3182F6]/20 dark:text-[#3182F6]'
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
          onClick={(e) => { e.stopPropagation(); setDropdownOpen(!dropdownOpen); }}
          className="inline-flex items-center justify-center w-[18px] h-[18px] rounded border border-dashed border-[#E5E8EB] dark:border-[#2C2C34] text-[#B0B8C1] dark:text-[#8B95A1] hover:border-[#3182F6] hover:text-[#3182F6] dark:hover:border-[#3182F6] dark:hover:text-[#3182F6] transition-colors cursor-pointer"
          title="문자 템플릿 관리"
        >
          <Plus size={10} />
        </button>
        {dropdownOpen && templateLabels.length > 0 && (
          <div className="absolute top-full right-0 mt-1 z-50 min-w-[160px] rounded-lg border border-[#E5E8EB] dark:border-[#2C2C34] bg-white dark:bg-[#1E1E24] shadow-lg py-1">
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

const InlineInput = ({ value, field, resId, className, placeholder, onSave }: {
  value: string;
  field: string;
  resId: number;
  className?: string;
  placeholder?: string;
  onSave: (resId: number, field: string, value: string) => void;
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
  const [prevDayReservations, setPrevDayReservations] = useState<Reservation[]>([]);
  const [nextDayReservations, setNextDayReservations] = useState<Reservation[]>([]);
  const [rooms, setRooms] = useState<any[]>([]);
  const [animDirection, setAnimDirection] = useState<'none' | 'left' | 'right'>('none');
  const [loading, setLoading] = useState(false);
  const [dragOverRoom, setDragOverRoom] = useState<string | null>(null);
  const [dragOverPool, setDragOverPool] = useState(false);
  const [dragOverPartyZone, setDragOverPartyZone] = useState(false);
  const [processing, setProcessing] = useState(false);

  const [modalVisible, setModalVisible] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formValues, setFormValues] = useState<any>({
    guest_type: 'manual',
    customer_name: '',
    phone: '',
    date: '',
    time: '18:00',
    gender: '',
    party_size: 1,
    naver_room_type: '',
    tags: '',
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
    room: string;
    onConfirm: (applySubsequent: boolean) => void;
  } | null>(null);

  const [partyValues, setPartyValues] = useState<Record<number, string>>({});
  const [templateLabels, setTemplateLabels] = useState<{template_key: string; name: string; short_label: string | null}[]>([]);

  const handleFieldSave = async (resId: number, field: string, value: string) => {
    if (field === 'party_type') {
      try {
        await reservationsAPI.update(resId, { party_type: value || null });
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
      } else if (field === 'party_type') {
        await reservationsAPI.update(resId, { party_type: value || null });
      } else {
        await reservationsAPI.update(resId, { [field]: value });
      }
      fetchReservations(selectedDate);
    } catch {
      toast.error('저장 실패');
    }
  };


  const [smsColumnWidth, setSmsColumnWidth] = useState(200);
  const [isResizing, setIsResizing] = useState(false);
  const [resizeStartX, setResizeStartX] = useState(0);
  const [resizeStartWidth, setResizeStartWidth] = useState(200);

  const GUEST_COLS = useMemo(() => {
    return `56px 120px 40px 40px 72px 1fr`;
  }, []);

  const roomInfoMap = useMemo(() => {
    const map: Record<string, string> = {};
    rooms.forEach((room) => {
      map[room.room_number] = room.room_type;
    });
    return map;
  }, [rooms]);

  const activeRoomEntries = useMemo(() => {
    return rooms.filter((room) => room.active).map((room) => ({
      room_number: room.room_number,
      isDormitory: room.dormitory || false,
      bed_capacity: room.bed_capacity || 1,
    }));
  }, [rooms]);

  const prevDayRoomMap = useMemo(() => {
    const map = new Map<string, Reservation[]>();
    prevDayReservations.forEach((r) => {
      if (r.room_number) {
        const existing = map.get(r.room_number) || [];
        existing.push(r);
        map.set(r.room_number, existing);
      }
    });
    return map;
  }, [prevDayReservations]);

  const nextDayRoomMap = useMemo(() => {
    const map = new Map<string, Reservation[]>();
    nextDayReservations.forEach((r) => {
      if (r.room_number) {
        const existing = map.get(r.room_number) || [];
        existing.push(r);
        map.set(r.room_number, existing);
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
      const tomorrow = res.data.tomorrow;
      toast.success(`객실 자동 배정 완료: 오늘 ${today.assigned}건, 내일 ${tomorrow.assigned}건`);
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
    fetchOne(date.subtract(1, 'day'), setPrevDayReservations);
    fetchOne(date.add(1, 'day'), setNextDayReservations);
  }, []);

  // 날짜 이동 방향 추적 (프리페치용)
  const prevDateRef = useRef<Dayjs>(selectedDate);
  const reservationsRef = useRef<Reservation[]>([]);
  const prevDayRef = useRef<Reservation[]>([]);
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

      // 양옆 백그라운드 fetch
      reservationsAPI.getAll({ date: date.subtract(1, 'day').format('YYYY-MM-DD'), limit: 200 })
        .then(res => { const d = filterActive(res.data); setPrevDayReservations(d); prevDayRef.current = d; })
        .catch(() => { setPrevDayReservations([]); prevDayRef.current = []; });
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

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (isResizing) {
        const delta = e.clientX - resizeStartX;
        const newWidth = Math.max(60, Math.min(400, resizeStartWidth + delta));
        setSmsColumnWidth(newWidth);
      }
    };

    const handleMouseUp = () => {
      setIsResizing(false);
      document.body.style.cursor = 'default';
      document.body.style.userSelect = 'auto';
    };

    if (isResizing) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing, resizeStartX, resizeStartWidth]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (campaignDropdownRef.current && !campaignDropdownRef.current.contains(e.target as Node)) {
        setCampaignDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);


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
    const assigned = new Map<string, Reservation[]>();
    const unassignedList: Reservation[] = [];
    const partyOnlyList: Reservation[] = [];

    reservations.forEach((res) => {
      if (res.room_number) {
        // Has a room assigned → goes to that room's row
        const list = assigned.get(res.room_number) || [];
        list.push(res);
        assigned.set(res.room_number, list);
      } else if (sectionOverrides[res.id] === 'party') {
        partyOnlyList.push(res);
      } else if (sectionOverrides[res.id] === 'unassigned') {
        unassignedList.push(res);
      } else if (res.tags?.includes('파티만') || res.naver_room_type?.includes('파티만')) {
        // 태그 또는 상품명에 '파티만' 포함 시 파티만 섹션
        partyOnlyList.push(res);
      } else {
        unassignedList.push(res);
      }
    });

    return {
      assignedRooms: assigned,
      unassigned: unassignedList,
      partyOnly: partyOnlyList,
    };
  }, [reservations, sectionOverrides]);

  const onDragStart = (e: DragEvent, resId: number) => {
    e.dataTransfer.setData('text/plain', String(resId));
    e.dataTransfer.effectAllowed = 'move';

    // Custom small drag ghost — show guest name in a compact pill
    const res = reservations.find((r) => r.id === resId);
    const ghost = document.createElement('div');
    ghost.textContent = res?.customer_name || '이동';
    ghost.style.cssText = 'position:fixed;top:-100px;left:-100px;padding:4px 12px;border-radius:8px;background:#3182F6;color:#fff;font-size:13px;font-weight:600;white-space:nowrap;pointer-events:none;z-index:9999;';
    document.body.appendChild(ghost);
    e.dataTransfer.setDragImage(ghost, ghost.offsetWidth / 2, ghost.offsetHeight / 2);
    requestAnimationFrame(() => document.body.removeChild(ghost));
  };

  const onRoomDragOver = (e: DragEvent, room: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (dragOverRoom !== room) setDragOverRoom(room);
  };
  const onRoomDragLeave = (e: DragEvent) => {
    // Only clear if actually leaving the room container (not entering a child)
    const related = e.relatedTarget as Node | null;
    if (!related || !e.currentTarget.contains(related)) {
      setDragOverRoom(null);
    }
  };

  const doAssignRoom = async (resId: number, room: string, applySubsequent: boolean) => {
    // Optimistic update: move guest to new room + auto-assign room_info SMS tag
    setReservations((prev) =>
      prev.map((r) => {
        if (r.id !== resId) return r;
        const hasRoomInfo = r.sms_assignments?.some((a) => a.template_key === 'room_info');
        const updatedAssignments = hasRoomInfo
          ? r.sms_assignments
          : [...(r.sms_assignments || []), { id: 0, reservation_id: r.id, template_key: 'room_info', assigned_at: new Date().toISOString(), sent_at: null, assigned_by: 'auto' } as SmsAssignment];
        return { ...r, room_number: room, sms_assignments: updatedAssignments };
      })
    );
    setSectionOverrides((prev) => { const next = { ...prev }; delete next[resId]; return next; });

    try {
      await reservationsAPI.assignRoom(resId, {
        room_number: room,
        date: selectedDate.format('YYYY-MM-DD'),
        apply_subsequent: applySubsequent,
      });
      toast.success(`${room} 배정 완료`);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || '객실 배정에 실패했습니다.');
      // Revert on failure
      await fetchReservations(selectedDate);
    }
  };

  const onRoomDrop = async (e: DragEvent, room: string) => {
    e.preventDefault();
    setDragOverRoom(null);
    const resId = Number(e.dataTransfer.getData('text/plain'));
    if (!resId) return;
    const currentList = assignedRooms.get(room) || [];
    if (currentList.some((r) => r.id === resId)) return;

    const res = reservations.find((r) => r.id === resId);
    if (!res) return;

    // Multi-night guest: ask whether to apply to subsequent dates
    if (isMultiNight(res)) {
      setMultiNightConfirm({
        open: true,
        resId,
        resName: res.customer_name,
        room,
        onConfirm: (applySubsequent) => {
          setMultiNightConfirm(null);
          doAssignRoom(resId, room, applySubsequent);
        },
      });
      return;
    }

    // Single-night: assign directly (apply_subsequent doesn't matter)
    await doAssignRoom(resId, room, true);
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

    // Already in unassigned section → nothing to do
    if (!res.room_number && sectionOverrides[resId] === 'unassigned') return;
    if (!res.room_number && !sectionOverrides[resId] && !res.tags?.includes('파티만') && !res.naver_room_type?.includes('파티만')) return;

    if (res.room_number) {
      // Optimistic update: clear room + remove unsent room_info tag
      setReservations((prev) =>
        prev.map((r) => {
          if (r.id !== resId) return r;
          const filtered = r.sms_assignments?.filter((a) => !(a.template_key === 'room_info' && !a.sent_at)) || [];
          return { ...r, room_number: null, sms_assignments: filtered };
        })
      );
      setSectionOverrides((prev) => ({ ...prev, [resId]: 'unassigned' }));

      try {
        await reservationsAPI.assignRoom(resId, { room_number: null, date: selectedDate.format('YYYY-MM-DD') });
        toast.success('미배정으로 이동');
      } catch {
        toast.error('배정 해제에 실패했습니다.');
        await fetchReservations(selectedDate);
      }
    } else {
      // Local section move (party → unassigned)
      setSectionOverrides((prev) => ({ ...prev, [resId]: 'unassigned' }));
      toast.success('미배정으로 이동');
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

    const guest = reservations.find((r) => r.id === resId);
    if (!guest) return;

    // Already in party section → nothing to do
    if (!guest.room_number && sectionOverrides[resId] === 'party') return;
    if (!guest.room_number && !sectionOverrides[resId] && (guest.tags?.includes('파티만') || guest.naver_room_type?.includes('파티만'))) return;

    if (guest.room_number) {
      // Optimistic update: clear room + remove unsent room_info tag
      setReservations((prev) =>
        prev.map((r) => {
          if (r.id !== resId) return r;
          const filtered = r.sms_assignments?.filter((a) => !(a.template_key === 'room_info' && !a.sent_at)) || [];
          return { ...r, room_number: null, sms_assignments: filtered };
        })
      );
      setSectionOverrides((prev) => ({ ...prev, [resId]: 'party' }));

      try {
        await reservationsAPI.assignRoom(resId, { room_number: null, date: selectedDate.format('YYYY-MM-DD') });
        toast.success('파티만으로 이동');
      } catch {
        toast.error('이동 실패');
        await fetchReservations(selectedDate);
      }
    } else {
      // Local section move (unassigned → party)
      setSectionOverrides((prev) => ({ ...prev, [resId]: 'party' }));
      toast.success('파티만으로 이동');
    }
  };

  const handleAddPartyGuest = () => {
    setEditingId(null);
    setFormValues({
      guest_type: 'manual',
      customer_name: '',
      phone: '',
      date: selectedDate.format('YYYY-MM-DD'),
      time: '18:00',
      gender: '',
      party_size: 1,
      naver_room_type: '',
      tags: '',
      notes: '',
      status: 'confirmed',
      booking_source: 'manual',
    });
    setModalVisible(true);
  };

  const handleEditGuest = (id: number) => {
    const guest = reservations.find((r) => r.id === id);
    if (guest) {
      setEditingId(id);
      setFormValues({
        ...guest,
        tags: guest.tags || '',
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
    delete values.male_count;
    delete values.female_count;

    if (!values.time) values.time = '00:00';

    if (!editingId && values.guest_type) {
      if (values.guest_type === 'party_only') {
        if (!values.tags?.includes('파티만')) {
          values.tags = values.tags ? `${values.tags},파티만` : '파티만';
        }
      }
      delete values.guest_type;
    }

    if (!values.room_number && !values.tags?.includes('파티만')) {
      values.tags = values.tags ? `${values.tags},파티만` : '파티만';
    }

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
    }
  };


  const updateReservationSms = (resId: number, updater: (assignments: Reservation['sms_assignments']) => Reservation['sms_assignments']) => {
    setReservations(prev => prev.map(r =>
      r.id === resId ? { ...r, sms_assignments: updater(r.sms_assignments || []) } : r
    ));
  };

  const handleSmsToggle = async (resId: number, templateKey: string) => {
    const res = reservations.find(r => r.id === resId);
    const assignment = res?.sms_assignments?.find(a => a.template_key === templateKey);
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

  const doSmsToggle = async (resId: number, templateKey: string) => {
    const res = reservations.find(r => r.id === resId);
    const assignment = res?.sms_assignments?.find(a => a.template_key === templateKey);
    const wasSent = !!assignment?.sent_at;
    // Optimistic update
    updateReservationSms(resId, assignments =>
      assignments.map(a => a.template_key === templateKey
        ? { ...a, sent_at: wasSent ? null : new Date().toISOString() }
        : a
      )
    );
    try {
      await smsAssignmentsAPI.toggle(resId, templateKey);
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
      { id: 0, reservation_id: resId, template_key: templateKey, assigned_at: new Date().toISOString(), sent_at: null, assigned_by: 'manual' },
    ]);
    try {
      await smsAssignmentsAPI.assign(resId, { template_key: templateKey });
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
    const removed = res?.sms_assignments?.find(a => a.template_key === templateKey);
    // Optimistic update
    updateReservationSms(resId, assignments =>
      assignments.filter(a => a.template_key !== templateKey)
    );
    try {
      await smsAssignmentsAPI.remove(resId, templateKey);
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
    const multiNight = isMultiNight(res);

    return (
      <div key={res.id} className={`group/guest flex items-center h-10 ${showGrip ? '' : 'pl-7'} transition-colors duration-150 ${multiNight ? 'bg-[#FFF0E0] dark:bg-[#FF9500]/15 hover:bg-[#FFE4CC] dark:hover:bg-[#FF9500]/20' : 'hover:bg-[#E8F3FF] dark:hover:bg-[#3182F6]/8'} ${guestAreaCursor()}`}>
        {showGrip && (
          <div
            draggable
            onDragStart={(e) => onDragStart(e, res.id)}
            className={`flex items-center justify-center w-7 px-0.5 flex-shrink-0 cursor-grab active:cursor-grabbing text-[#B0B8C1] dark:text-[#4E5968] transition-all duration-200 ${multiNight ? 'group-hover/guest:text-[#FFB366] dark:group-hover/guest:text-[#FFB366]' : 'group-hover/guest:text-[#3182F6] dark:group-hover/guest:text-[#3182F6]'}`}
          >
            <GripVertical size={14} />
          </div>
        )}
        <div
          className="flex-1 grid items-center gap-2 px-3 py-1.5"
          style={{ gridTemplateColumns: GUEST_COLS }}
        >
          <div className="overflow-hidden">
            <InlineInput value={res.customer_name} field="customer_name" resId={res.id} onSave={handleFieldSave} className="font-medium text-[#191F28] dark:text-white" placeholder="이름" />

          </div>
          <div className="overflow-hidden">
            <InlineInput value={res.phone} field="phone" resId={res.id} onSave={handleFieldSave} className="text-[#8B95A1] dark:text-[#8B95A1] tabular-nums" placeholder="연락처" />
          </div>
          <div className="overflow-hidden text-center">
            <InlineInput value={genderPeople} field="genderPeople" resId={res.id} onSave={handleFieldSave} className="text-[#4E5968] dark:text-white font-medium text-center" placeholder="-" />
          </div>
          <div className="overflow-hidden text-center">
            <InlineInput value={res.party_type || ''} field="party_type" resId={res.id} onSave={handleFieldSave} className="text-[#4E5968] dark:text-white font-medium text-center" placeholder="-" />
          </div>
          <div className="overflow-hidden truncate text-body text-[#8B95A1] dark:text-[#8B95A1] text-center">{res.naver_room_type || <span className="text-[#B0B8C1] dark:text-[#4E5968]">-</span>}</div>
          <div className="flex items-center gap-2 min-w-0">
            <div className="min-w-[60px] flex-1 overflow-hidden">
              <InlineInput value={res.notes || ''} field="notes" resId={res.id} onSave={handleFieldSave} className="text-[#8B95A1] dark:text-[#8B95A1]" placeholder="" />
            </div>
            <div className="min-w-[120px] flex-1 overflow-visible">
              <SmsCell reservation={res} templateLabels={templateLabels} onToggle={handleSmsToggle} onAssign={handleSmsAssign} onRemove={handleSmsRemove} />
            </div>
          </div>
        </div>
      </div>
    );
  };

  const renderRoomRow = (entry: { room_number: string; isDormitory: boolean; bed_capacity: number }, rowIndex: number) => {
    const { room_number, isDormitory, bed_capacity } = entry;
    const guestsRaw = assignedRooms.get(room_number) || [];
    const isDragOver = dragOverRoom === room_number;
    const prevGuestsRaw = prevDayRoomMap.get(room_number) || [];
    const nextGuestsRaw = nextDayRoomMap.get(room_number) || [];

    // 도미토리: 연박자 행 위치를 날짜간 통일
    let guests = guestsRaw;
    let prevGuests = prevGuestsRaw;
    let nextGuests = nextGuestsRaw;
    if (isDormitory) {
      // 원본을 ID순으로 정렬 → 어느 날짜에서 보든 같은 참조 순서
      const byId = (a: Reservation, b: Reservation) => a.id - b.id;
      const prevSorted = [...prevGuestsRaw].sort(byId);
      const guestsSorted = [...guestsRaw].sort(byId);
      const nextSorted = [...nextGuestsRaw].sort(byId);

      // 리스트를 참조 리스트 기준으로 정렬:
      // 연박자(참조에도 있는 사람)는 참조 인덱스에 맞추고, 신규는 빈자리에 채우기
      const alignToRef = (list: Reservation[], refList: Reservation[]): Reservation[] => {
        const refIds = refList.map((g) => g.id);
        const continuing: { guest: Reservation; refIdx: number }[] = [];
        const newG: Reservation[] = [];
        for (const g of list) {
          const refIdx = refIds.indexOf(g.id);
          if (refIdx !== -1) {
            continuing.push({ guest: g, refIdx });
          } else {
            newG.push(g);
          }
        }
        continuing.sort((a, b) => a.refIdx - b.refIdx);

        const result: Reservation[] = [];
        let contIdx = 0;
        let newIdx = 0;
        const maxLen = Math.max(
          continuing.length > 0 ? continuing[continuing.length - 1].refIdx + 1 : 0,
          list.length,
        );
        for (let i = 0; i < maxLen; i++) {
          if (contIdx < continuing.length && continuing[contIdx].refIdx === i) {
            result.push(continuing[contIdx].guest);
            contIdx++;
          } else if (newIdx < newG.length) {
            result.push(newG[newIdx]);
            newIdx++;
          }
        }
        while (newIdx < newG.length) {
          result.push(newG[newIdx]);
          newIdx++;
        }
        return result;
      };

      // ID 정렬된 전일을 기준으로 당일 정렬 → 안정적 행 위치
      guests = alignToRef(guestsSorted, prevSorted);
      prevGuests = alignToRef(prevSorted, guests);
      nextGuests = alignToRef(nextSorted, guests);
    }

    const maxOccupancy = Math.max(guests.length, prevGuests.length, nextGuests.length, 1);
    const visibleRows = isDormitory
      ? Math.min(bed_capacity, maxOccupancy)
      : Math.max(1, guests.length);
    const totalRows = visibleRows;
    const stripeBg = rowIndex % 2 === 0 ? 'bg-white dark:bg-[#1E1E24]' : 'bg-[#F8F9FA] dark:bg-[#17171C]';

    return (
      <div
        key={room_number}
        className={`group flex select-none transition-colors
          ${autoAssignConfirm
            ? (guestsRaw.length > 0 && guestsRaw.every(g => g.room_assigned_by === 'manual')
              ? 'opacity-40'
              : '')
            : ''}
          ${isDragOver
            ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/8 ring-1 ring-inset ring-[#3182F6]/30 dark:ring-[#3182F6]/30'
            : stripeBg
          }`}
        style={{ minHeight: `${totalRows * 40}px` }}
        onDragOver={(e) => onRoomDragOver(e, room_number)}
        onDragLeave={onRoomDragLeave}
        onDrop={(e) => onRoomDrop(e, room_number)}
      >
        {/* Prev day column */}
        <div className={`flex-shrink-0 w-24 border-r-8 border-white dark:border-[#2C2C34] shadow-[inset_-1px_0_0_#E5E8EB,1px_0_0_#E5E8EB] z-[2] border-b border-b-[#E5E8EB] dark:border-b-gray-700 ${stripeBg}`}>
          <div className="divide-y divide-[#F2F4F6] dark:divide-[#2C2C34]">
            {Array.from({ length: totalRows }).map((_, i) => {
              const prevGuest = prevGuests[i];
              const gp = prevGuest ? formatGenderPeople(prevGuest) : '';
              return (
                <div key={`prev-${i}`} className={`flex items-center justify-center h-10 px-1 ${prevGuest && isMultiNight(prevGuest) ? 'bg-[#FFF0E0] dark:bg-[#FF9500]/15' : ''}`}>
                  {prevGuest ? (
                    <div className="flex items-center gap-1.5 truncate">
                      <span className="truncate text-caption text-[#4E5968] dark:text-[#8B95A1]">{prevGuest.customer_name}</span>
                      {gp && <span className="flex-shrink-0 text-caption text-[#8B95A1] dark:text-[#4E5968]">{gp}</span>}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>

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
                    className="flex-1 grid items-center gap-2 px-3 py-1.5"
                    style={{ gridTemplateColumns: GUEST_COLS }}
                  >
                    <div className="overflow-hidden truncate col-span-full text-body text-[#B0B8C1] dark:text-[#4E5968] italic">
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
                className="flex-1 grid items-center gap-2 px-3 py-1.5"
                style={{ gridTemplateColumns: GUEST_COLS }}
              >
                <div className="overflow-hidden truncate col-span-full text-body text-[#3182F6] dark:text-[#3182F6] italic">
                  {isDragOver ? '여기에 놓으세요' : ''}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Next day column */}
        <div className={`flex-shrink-0 w-24 border-l-8 border-white dark:border-[#2C2C34] shadow-[inset_1px_0_0_#E5E8EB,-1px_0_0_#E5E8EB] z-[2] border-b border-b-[#E5E8EB] dark:border-b-gray-700 ${stripeBg}`}>
          <div className="divide-y divide-[#F2F4F6] dark:divide-[#2C2C34]">
            {Array.from({ length: totalRows }).map((_, i) => {
              const nextGuest = nextGuests[i];
              const gp = nextGuest ? formatGenderPeople(nextGuest) : '';
              return (
                <div key={`next-${i}`} className={`flex items-center justify-center h-10 px-1 ${nextGuest && isMultiNight(nextGuest) ? 'bg-[#FFF0E0] dark:bg-[#FF9500]/15' : ''}`}>
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
        const newPrev = reservationsRef.current;
        const newCurrent = nextDayRef.current;
        dataPromise = reservationsAPI.getAll({ date: newDate.add(1, 'day').format('YYYY-MM-DD'), limit: 200 })
          .catch(() => ({ data: [] }))
          .then((res: any) => {
            const nextData = filterActive(res.data);
            reservationsRef.current = newCurrent;
            prevDayRef.current = newPrev;
            nextDayRef.current = nextData;
            setReservations(newCurrent);
            setPrevDayReservations(newPrev);
            setNextDayReservations(nextData);
          });
      } else if (diff === -1 && prevDayRef.current.length > 0) {
        // 이전: 시프트 + 전일만 fetch
        const newNext = reservationsRef.current;
        const newCurrent = prevDayRef.current;
        dataPromise = reservationsAPI.getAll({ date: newDate.subtract(1, 'day').format('YYYY-MM-DD'), limit: 200 })
          .catch(() => ({ data: [] }))
          .then((res: any) => {
            const prevData = filterActive(res.data);
            reservationsRef.current = newCurrent;
            nextDayRef.current = newNext;
            prevDayRef.current = prevData;
            setReservations(newCurrent);
            setNextDayReservations(newNext);
            setPrevDayReservations(prevData);
          });
      } else {
        // 폴백: 당일 먼저
        dataPromise = reservationsAPI.getAll({ date: dateStr, limit: 200 })
          .then((res) => {
            const curr = filterActive(res.data);
            reservationsRef.current = curr;
            setReservations(curr);
            // 양옆 백그라운드
            reservationsAPI.getAll({ date: newDate.subtract(1, 'day').format('YYYY-MM-DD'), limit: 200 })
              .then(r => { const d = filterActive(r.data); setPrevDayReservations(d); prevDayRef.current = d; })
              .catch(() => { setPrevDayReservations([]); prevDayRef.current = []; });
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
    const genderRatio = partyFemale > 0 ? `${(partyMale / partyFemale).toFixed(1)}:1` : partyMale > 0 ? `${partyMale}:0` : '-';

    return {
      roomTotal, roomMale, roomFemale,
      partyTotal, partyMale, partyFemale,
      firstTotal, firstMale, firstFemale,
      secondOnlyTotal, secondOnlyMale, secondOnlyFemale,
      conversionRate, genderRatio,
    };
  }, [reservations]);

  return (
    <div className={`space-y-4 ${processing ? 'opacity-60 pointer-events-none' : ''}`}>

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
              <span className="stat-value tabular-nums text-[#7EB4F8]">{summary.roomMale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
              <span className="h-3 w-px bg-[#E5E8EB] dark:bg-[#2C2C34]" />
              <span className="stat-value tabular-nums text-[#F8838C]">{summary.roomFemale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
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
              <span className="stat-value tabular-nums text-[#7EB4F8]">{summary.firstMale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
              <span className="h-3 w-px bg-[#E5E8EB] dark:bg-[#2C2C34]" />
              <span className="stat-value tabular-nums text-[#F8838C]">{summary.firstFemale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
            </div>
          </div>
          <div className="w-px bg-[#E5E8EB] dark:bg-[#2C2C34] my-3" />
          <div className="w-[130px] flex flex-col items-center justify-center px-3 py-4">
            <span className="stat-label whitespace-nowrap">2차만</span>
            <div className="flex items-center justify-center gap-2.5 mt-1">
              <span className="stat-value tabular-nums text-[#7EB4F8]">{summary.secondOnlyMale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
              <span className="h-3 w-px bg-[#E5E8EB] dark:bg-[#2C2C34]" />
              <span className="stat-value tabular-nums text-[#F8838C]">{summary.secondOnlyFemale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
            </div>
          </div>
          <div className="w-px bg-[#E5E8EB] dark:bg-[#2C2C34] my-3" />
          <div className="w-[130px] flex flex-col items-center justify-center px-3 py-4">
            <span className="stat-label whitespace-nowrap">전체</span>
            <div className="flex items-center justify-center gap-2.5 mt-1">
              <span className="stat-value tabular-nums text-[#7EB4F8]">{summary.partyMale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
              <span className="h-3 w-px bg-[#E5E8EB] dark:bg-[#2C2C34]" />
              <span className="stat-value tabular-nums text-[#F8838C]">{summary.partyFemale}<span className="ml-0.5 text-label font-normal text-[#B0B8C1]">명</span></span>
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


            <div className="flex items-center gap-2 ml-auto">
              <Button color="blue" size="sm" onClick={() => setAutoAssignConfirm(true)} disabled={autoAssigning}>
                {autoAssigning ? <><Spinner size="sm" className="mr-1.5" />배정 중...</> : <><UserPlus className="h-3.5 w-3.5 mr-1.5" />객실 자동 배정</>}
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

      {/* 자동배정 오버레이 */}
      {autoAssignConfirm && (
        <div className="fixed inset-0 z-40 bg-black/20" onClick={() => setAutoAssignConfirm(false)} />
      )}

      {/* Main grid card */}
      <div className={`section-card !overflow-visible ${autoAssignConfirm ? 'relative z-[41]' : ''}`}>
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
            <div className="rounded-xl border border-[#F2F4F6] dark:border-[#2C2C34]">
              {/* Header */}
              <div className="flex items-center h-10 bg-[#F2F4F6] dark:bg-[#17171C] border-b border-[#F2F4F6] dark:border-[#2C2C34]">
                <div className="flex-shrink-0 w-24 px-2 text-center border-r-8 border-white dark:border-[#2C2C34] shadow-[inset_-1px_0_0_#E5E8EB,1px_0_0_#E5E8EB] z-[2] flex items-center justify-center self-stretch">
                  <span className="text-caption font-semibold text-[#8B95A1] dark:text-[#8B95A1]">{selectedDate.subtract(1, 'day').format('M/D')}</span>
                </div>
                <div className="flex-shrink-0 pl-3 pr-2 w-42 border-r border-[#F2F4F6] dark:border-[#2C2C34]">
                  <span className="text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">객실</span>
                </div>
                <div className="w-7 flex-shrink-0" />
                <div
                  className="flex-1 grid items-center gap-2 px-3"
                  style={{ gridTemplateColumns: GUEST_COLS }}
                >
                  <div className="text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">이름</div>
                  <div className="text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">전화번호</div>
                  <div className="text-center text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">성별</div>
                  <div className="text-center text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">파티</div>
                  <div className="text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1] text-center">예약객실</div>
                  <div className="flex items-center gap-2">
                    <div className="min-w-[60px] flex-1 text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">메모</div>
                    <div className="min-w-[60px] flex-1 text-label font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-[#8B95A1]">문자</div>
                  </div>
                </div>
                <div className="flex-shrink-0 w-24 px-2 text-center border-l-8 border-white dark:border-[#2C2C34] shadow-[inset_1px_0_0_#E5E8EB,-1px_0_0_#E5E8EB] z-[2] flex items-center justify-center self-stretch">
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
                    : autoAssignConfirm && unassigned.length > 0
                      ? 'bg-[#E8F3FF] dark:bg-[#3182F6]/10'
                      : unassigned.length > 0 ? 'bg-white dark:bg-[#1E1E24]' : 'bg-[#F2F4F6]/50 dark:bg-[#17171C]/30'
                }`}
                style={{ minHeight: `${Math.max(1, unassigned.length) * 40}px` }}
                onDragOver={onPoolDragOver}
                onDragLeave={onPoolDragLeave}
                onDrop={onPoolDrop}
              >
                {/* Prev day column - empty */}
                <div className="flex-shrink-0 w-24 border-r-8 border-white dark:border-[#2C2C34] shadow-[inset_-1px_0_0_#E5E8EB,1px_0_0_#E5E8EB] z-[2] bg-[#F8F9FA] dark:bg-[#17171C] border-b border-b-[#E5E8EB] dark:border-b-gray-700" />

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
                      <div className="flex-1 grid items-center gap-2 px-3 py-1.5" style={{ gridTemplateColumns: GUEST_COLS }}>
                        <div className="overflow-hidden truncate col-span-full text-body text-[#FF9500] dark:text-[#FF9500] italic">
                          {dragOverPool ? '여기에 놓으면 배정 해제' : ''}
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* Next day column - empty */}
                <div className="flex-shrink-0 w-24 border-l-8 border-white dark:border-[#2C2C34] shadow-[inset_1px_0_0_#E5E8EB,-1px_0_0_#E5E8EB] z-[2] bg-[#F8F9FA] dark:bg-[#17171C] border-b border-b-[#E5E8EB] dark:border-b-gray-700" />
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
                {/* Prev day column - empty */}
                <div className="flex-shrink-0 w-24 border-r-8 border-white dark:border-[#2C2C34] shadow-[inset_-1px_0_0_#E5E8EB,1px_0_0_#E5E8EB] z-[2] bg-[#F8F9FA] dark:bg-[#17171C] border-b border-b-[#E5E8EB] dark:border-b-gray-700" />

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
                      <div className="flex-1 grid items-center gap-2 px-3 py-1.5" style={{ gridTemplateColumns: GUEST_COLS }}>
                        <div className="overflow-hidden truncate col-span-full text-body text-[#7B61FF] dark:text-[#7B61FF] italic">
                          {dragOverPartyZone ? '여기에 놓으면 파티만 게스트로 전환' : ''}
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* Next day column - empty */}
                <div className="flex-shrink-0 w-24 border-l-8 border-white dark:border-[#2C2C34] shadow-[inset_1px_0_0_#E5E8EB,-1px_0_0_#E5E8EB] z-[2] bg-[#F8F9FA] dark:bg-[#17171C] border-b border-b-[#E5E8EB] dark:border-b-gray-700" />
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
                  { value: 'manual', label: '미배정' },
                  { value: 'party_only', label: '파티만' },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => {
                      if (opt.value === 'party_only') {
                        setFormValues({ ...formValues, guest_type: opt.value, tags: '파티만' });
                      } else {
                        setFormValues({ ...formValues, guest_type: opt.value });
                      }
                    }}
                    className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors cursor-pointer
                      ${(formValues.guest_type || 'manual') === opt.value
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
              <TextInput
                id="date"
                type="date"
                value={formValues.date || ''}
                onChange={(e) => setFormValues({ ...formValues, date: e.target.value })}
                sizing="sm"
              />
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
          <Button color="blue" onClick={handleSubmit}>저장</Button>
          <Button color="light" onClick={() => setModalVisible(false)}>취소</Button>
        </ModalFooter>
      </Modal>

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
              <UserPlus className="h-6 w-6 text-[#3182F6]" />
            </div>
            <h3 className="mb-2 text-lg font-semibold text-[#191F28] dark:text-white">연박 객실 이동</h3>
            <p className="mb-5 text-sm text-[#8B95A1] dark:text-[#8B95A1]">
              <span className="font-semibold text-[#191F28] dark:text-white">{multiNightConfirm?.resName}</span> 님을{' '}
              <span className="font-semibold text-[#3182F6]">{multiNightConfirm?.room}</span>(으)로 이동합니다.
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
                    const isSent = r?.sms_assignments?.some(a => a.template_key === sendConfirm?.templateKey && !!a.sent_at);
                    return isSent
                      ? `${sendConfirm?.customerName}님의 ${sendConfirm?.templateName} 발송을 취소하시겠습니까?`
                      : `${sendConfirm?.customerName}님에게 ${sendConfirm?.templateName}을(를) 발송하시겠습니까?`;
                  })()}
            </p>
            <div className="flex justify-center gap-3">
              <Button color="blue" onClick={() => {
                if (sendConfirm?.type === 'campaign') {
                  handleSendCampaign();
                } else if (sendConfirm?.type === 'toggle' && sendConfirm.resId && sendConfirm.templateKey) {
                  setSendConfirm(null);
                  doSmsToggle(sendConfirm.resId, sendConfirm.templateKey);
                }
              }}>
                발송
              </Button>
              <Button color="light" onClick={() => setSendConfirm(null)}>
                취소
              </Button>
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

      {/* 객실 자동 배정 — 플로팅 카드 (배경 스크롤 가능) */}
      {autoAssignConfirm && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 rounded-2xl border border-[#E5E8EB] dark:border-gray-700 bg-white/95 dark:bg-[#1E1E24]/95 backdrop-blur-sm shadow-[0_8px_30px_rgba(0,0,0,0.12)]">
          <div className="flex items-center justify-between gap-6 px-5 py-3">
            <div className="flex items-center gap-3">
              <UserPlus className="h-5 w-5 text-[#3182F6]" />
              <div>
                <p className="text-body font-semibold text-[#191F28] dark:text-white">
                  객실 자동 배정 — {selectedDate.format('YYYY-MM-DD')}
                </p>
                <p className="text-caption text-[#8B95A1]">
                  미배정 예약자를 객실에 자동 배정합니다. 수동 배정은 유지됩니다.
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button color="blue" size="sm" onClick={handleAutoAssign} disabled={autoAssigning}>
                {autoAssigning ? <><Spinner size="sm" className="mr-1.5" />배정 중...</> : '배정 진행'}
              </Button>
              <Button color="light" size="sm" onClick={() => setAutoAssignConfirm(false)}>
                취소
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default RoomAssignment;
