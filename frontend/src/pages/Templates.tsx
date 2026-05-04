import React, { useState, useEffect, useRef } from 'react';
import { toast } from 'sonner';
import {
  Plus,
  Pencil,
  Trash2,
  Play,
  Eye,

  CheckCircle,
  XCircle,
  FileText,
  Clock,
  ChevronDown,
  ChevronRight,
  GripVertical,
} from 'lucide-react';
import {
  DndContext,
  closestCenter,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

import { ToggleSwitch } from '@/components/ui/toggle-switch';
import { Tabs, TabItem } from '@/components/ui/tabs';
import { Table, TableHead, TableBody, TableRow, TableHeadCell, TableCell } from '@/components/ui/table';
import { Modal, ModalHeader, ModalBody, ModalFooter } from '@/components/ui/modal';
import { TextInput } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import { useTenantStore } from '@/stores/tenant-store';
import { Spinner } from '@/components/ui/spinner';
import { Button } from '@/components/ui/button';

import { templatesAPI, templateSchedulesAPI, buildingsAPI, reservationsAPI } from '@/services/api';
import { normalizeUtcString } from '../lib/utils';

// ---------------------------------------------------------------------------
// Interfaces
// ---------------------------------------------------------------------------

interface Template {
  id: number;
  template_key: string;
  name: string;
  short_label: string | null;
  lms_title: string | null;
  content: string;
  variables: string | null;
  category: string | null;
  active: boolean;
  created_at: string;
  updated_at: string;
  schedule_count: number;
  participant_buffer: number;
  male_buffer: number;
  female_buffer: number;
  gender_ratio_buffers: string | null;
  round_unit: number;
  round_mode: string;
}

interface TemplateSchedule {
  id: number;
  template_id: number;
  template_name: string;
  template_key: string;
  schedule_name: string;
  schedule_type: string;
  hour: number | null;
  minute: number | null;
  day_of_week: string | null;
  interval_minutes: number | null;
  active_start_hour: number | null;
  active_end_hour: number | null;
  timezone: string;
  filters: string | null;
  target_mode: string | null;
  date_target: string | null;
  stay_filter: string | null;
  exclude_sent: boolean;
  active: boolean;
  created_at: string;
  updated_at: string;
  last_run: string | null;
  next_run: string | null;
  schedule_category?: 'standard' | 'event' | 'custom_schedule';
  custom_type?: string | null;
  hours_since_booking?: number | null;
  gender_filter?: 'male' | 'female' | null;
  max_checkin_days?: number | null;
  expires_after_days?: number | null;
  expires_at?: string | null;
  send_condition_date?: 'today' | 'tomorrow' | null;
  send_condition_ratio?: number | null;
  send_condition_operator?: 'gte' | 'lte' | null;
}

interface AssignmentFilter {
  type: 'assignment';
  value: 'room' | 'party' | 'unstable' | 'unassigned';
  buildings?: number[];
  include_unassigned?: boolean;
  stay_filter?: 'exclude' | null;
}

interface ColumnMatchFilter {
  type: 'column_match';
  value: string;
}

type ScheduleFilter = AssignmentFilter | ColumnMatchFilter | { type: string; value: string };

interface AssignmentState {
  room: boolean;
  room_buildings: number[];
  room_include_unassigned: boolean;
  room_stay_exclude: boolean;
  party: boolean;
  unstable: boolean;
}

function buildAssignmentFilters(state: AssignmentState): AssignmentFilter[] {
  const out: AssignmentFilter[] = [];
  if (state.room) {
    const f: AssignmentFilter = { type: 'assignment', value: 'room' };
    if (state.room_buildings.length) f.buildings = state.room_buildings;
    if (state.room_include_unassigned) f.include_unassigned = true;
    if (state.room_stay_exclude) f.stay_filter = 'exclude';
    out.push(f);
  }
  if (state.party) out.push({ type: 'assignment', value: 'party' });
  if (state.unstable) out.push({ type: 'assignment', value: 'unstable' });
  return out;
}

function parseAssignmentState(filters: ScheduleFilter[]): AssignmentState {
  const state: AssignmentState = {
    room: false, room_buildings: [], room_include_unassigned: false,
    room_stay_exclude: false,
    party: false, unstable: false,
  };
  for (const f of filters) {
    if (f.type !== 'assignment') continue;
    const af = f as AssignmentFilter;
    if (af.value === 'room') {
      state.room = true;
      state.room_buildings = af.buildings ?? [];
      state.room_include_unassigned = !!af.include_unassigned;
      state.room_stay_exclude = af.stay_filter === 'exclude';
    } else if (af.value === 'party') state.party = true;
    else if (af.value === 'unstable') state.unstable = true;
  }
  return state;
}

interface Building {
  id: number;
  name: string;
}

const COLUMN_MATCH_OPTIONS: { value: string; label: string }[] = [
  { value: 'party_type', label: '파티' },
  { value: 'gender', label: '성별' },
  { value: 'naver_room_type', label: '예약객실' },
  { value: 'notes', label: '메모' },
];

const COLUMN_LABEL_MAP: Record<string, string> = Object.fromEntries(
  COLUMN_MATCH_OPTIONS.map(o => [o.value, o.label])
);

function parseColumnMatchValue(value: string): { column: string; operator: string; text: string } | null {
  const idx1 = value.indexOf(':');
  if (idx1 === -1) return null;
  const idx2 = value.indexOf(':', idx1 + 1);
  if (idx2 === -1) return null;
  return {
    column: value.substring(0, idx1),
    operator: value.substring(idx1 + 1, idx2),
    text: value.substring(idx2 + 1),
  };
}

// ---------------------------------------------------------------------------
// Helper – variable extraction
// ---------------------------------------------------------------------------

const extractAndValidateVariables = (
  content: string,
  availableVars: any
): { valid: string[]; invalid: string[] } => {
  if (!content || !availableVars) return { valid: [], invalid: [] };
  const pattern = /\{\{(\w+)\}\}/g;
  const found = new Set<string>();
  for (const match of content.matchAll(pattern)) {
    if (match[1]) found.add(match[1]);
  }
  const valid: string[] = [], invalid: string[] = [];
  found.forEach(v => { (availableVars.variables?.[v] ? valid : invalid).push(v); });
  return { valid: valid.sort(), invalid: invalid.sort() };
};

// ---------------------------------------------------------------------------
// Tiny helpers
// ---------------------------------------------------------------------------

const DAY_MAP: Record<string, string> = {
  mon: '월', tue: '화', wed: '수', thu: '목',
  fri: '금', sat: '토', sun: '일',
};

function formatScheduleTime(s: TemplateSchedule): string {
  const mm = String(s.minute ?? 0).padStart(2, '0');
  if (s.schedule_type === 'daily') {
    return `${s.hour}시 ${mm}분`;
  }
  if (s.schedule_type === 'weekly') {
    const days = s.day_of_week?.split(',').map(d => DAY_MAP[d.trim()] ?? d).join(', ');
    return `${days} ${s.hour}시 ${mm}분`;
  }
  if (s.schedule_type === 'hourly') {
    const base = `매시 ${mm}분`;
    if (s.active_start_hour != null && s.active_end_hour != null) {
      return `${base} (${s.active_start_hour}시~${s.active_end_hour}시)`;
    }
    return base;
  }
  if (s.schedule_type === 'interval') {
    const base = `${s.interval_minutes}분마다`;
    if (s.active_start_hour != null && s.active_end_hour != null) {
      return `${base} (${s.active_start_hour}시~${s.active_end_hour}시)`;
    }
    return base;
  }
  return '-';
}

function formatRelativeTime(iso: string | null): string {
  if (!iso) return '-';
  const date = new Date(normalizeUtcString(iso));
  const diff = date.getTime() - Date.now();
  const minutes = Math.floor(diff / 60000);
  if (minutes < -5) return '대기 중';
  if (minutes < 0) return '발송 중…';
  if (minutes < 60) return `${minutes}분 후`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}시간 후`;
  return date.toLocaleString('ko-KR');
}

function getScheduleTypeLabel(type: string): string {
  const map: Record<string, string> = {
    daily: '매일', weekly: '매주', hourly: '매시간', interval: '간격',
  };
  return map[type] ?? type;
}

function getFirstSendMinutes(s: TemplateSchedule): number {
  const minute = s.minute ?? 0;
  if (s.schedule_type === 'daily' || s.schedule_type === 'weekly') {
    return (s.hour ?? 0) * 60 + minute;
  }
  if (s.schedule_type === 'hourly') {
    return (s.active_start_hour ?? 0) * 60 + minute;
  }
  if (s.schedule_type === 'interval') {
    return (s.active_start_hour ?? 0) * 60;
  }
  return Number.MAX_SAFE_INTEGER;
}


function parseFilters(raw: unknown): ScheduleFilter[] {
  if (Array.isArray(raw)) return raw;
  if (typeof raw === 'string') {
    try { return JSON.parse(raw); } catch { return []; }
  }
  return [];
}

function getScheduleDateLabel(record: TemplateSchedule): string {
  switch (record.date_target) {
    case 'yesterday': return '어제';
    case 'today': return '오늘';
    case 'tomorrow': return '내일';
    default: return record.date_target || '';
  }
}


function getEventTargetSummary(record: TemplateSchedule): React.ReactNode {
  const parts: string[] = [];
  if (record.hours_since_booking) parts.push(`${record.hours_since_booking}시간 내 예약`);
  if (record.gender_filter === 'male') parts.push('남성');
  else if (record.gender_filter === 'female') parts.push('여성');
  if (record.max_checkin_days) parts.push(`${record.max_checkin_days}일 내 체크인`);
  return <span className="text-caption text-[#4E5968] dark:text-gray-400">{parts.length > 0 ? parts.join(', ') : '이벤트 대상'}</span>;
}

function getTargetSummary(record: TemplateSchedule, buildingList?: Building[]): React.ReactNode {
  if (record.schedule_category === 'event') return getEventTargetSummary(record);
  const filters = parseFilters(record.filters);
  const dateLabel = getScheduleDateLabel(record);

  const assignmentFilters = filters.filter(f => f.type === 'assignment') as AssignmentFilter[];
  const columnMatchFilters = filters.filter(f => f.type === 'column_match');

  const assignmentTexts = assignmentFilters.map(f => {
    if (f.value === 'room') {
      const parts = ['객실배정'];
      if (f.buildings?.length && buildingList) {
        const names = f.buildings.map(id => buildingList.find(b => b.id === id)?.name ?? `#${id}`);
        parts.push(`(${names.join('·')})`);
      }
      return parts.join(' ');
    }
    if (f.value === 'party') return '파티만';
    if (f.value === 'unassigned') return '미배정';
    if (f.value === 'unstable') return '언스테이블';
    return f.value;
  });

  if (assignmentTexts.length === 0 && columnMatchFilters.length === 0) {
    return <span className="text-caption text-[#8B95A1]">{dateLabel} 전체 예약자</span>;
  }

  const parts: string[] = [];
  if (assignmentTexts.length > 0) parts.push(assignmentTexts.join('·'));
  if (columnMatchFilters.length > 0) {
    const cmTexts = columnMatchFilters.map(f => {
      const parsed = parseColumnMatchValue(f.value);
      if (!parsed) return '';
      const colLabel = COLUMN_LABEL_MAP[parsed.column] || parsed.column;
      if (parsed.operator === 'is_empty') return `${colLabel} 비어있음`;
      if (parsed.operator === 'is_not_empty') return `${colLabel} 값 있음`;
      const opLabel = parsed.operator === 'not_contains' ? '미포함' : '포함';
      return `${colLabel} '${parsed.text}' ${opLabel}`;
    }).filter(Boolean);
    if (cmTexts.length > 0) parts.push(cmTexts.join(', '));
  }

  return <span className="text-caption text-[#4E5968] dark:text-gray-400">{parts.join(' · ')}의 {dateLabel} 예약자</span>;
}


// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface SortableTemplateRowProps {
  id: number;
  children: (handleProps: {
    listeners: ReturnType<typeof useSortable>['listeners'];
    attributes: ReturnType<typeof useSortable>['attributes'];
    isDragging: boolean;
  }) => React.ReactNode;
}

function SortableTemplateRow({ id, children }: SortableTemplateRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
    zIndex: isDragging ? 10 : undefined,
    position: isDragging ? 'relative' : undefined,
  };
  return (
    <TableRow ref={setNodeRef} style={style}>
      {children({ listeners, attributes, isDragging })}
    </TableRow>
  );
}

interface ConfirmDeleteProps {
  open: boolean;
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}

function ConfirmDeleteDialog({ open, message, onConfirm, onCancel }: ConfirmDeleteProps) {
  return (
    <Modal show={open} onClose={onCancel} size="md" popup>
      <ModalHeader />
      <ModalBody>
        <div className="text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#FFEBEE] dark:bg-[#F04452]/10">
            <Trash2 className="h-6 w-6 text-[#F04452] dark:text-red-400" />
          </div>
          <h3 className="mb-2 text-heading font-semibold text-[#191F28] dark:text-white">정말 삭제하시겠습니까?</h3>
          <p className="mb-5 text-body text-gray-500">{message}</p>
          <div className="flex justify-center gap-3">
            <Button color="failure" onClick={onConfirm}>삭제</Button>
            <Button color="light" onClick={onCancel}>취소</Button>
          </div>
        </div>
      </ModalBody>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const Templates: React.FC = () => {
  const { tenants, currentTenantId } = useTenantStore();
  const hasUnstable = tenants.find(t => String(t.id) === currentTenantId)?.has_unstable ?? false;

  const [activeTab, setActiveTab] = useState('templates');

  // --- templates state ---
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [templateDialogOpen, setTemplateDialogOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<Template | null>(null);
  const [availableVariables, setAvailableVariables] = useState<any>(null);
  const [detectedVars, setDetectedVars] = useState<{ valid: string[]; invalid: string[] }>({ valid: [], invalid: [] });
  const [savingTemplate, setSavingTemplate] = useState(false);

  // template form
  const [sampleExamples, setSampleExamples] = useState<Record<string, string>>({});
  const [tKey, setTKey] = useState('');
  const [tName, setTName] = useState('');
  const [tShortLabel, setTShortLabel] = useState('');
  const [tLmsTitle, setTLmsTitle] = useState('');
  const [tContent, setTContent] = useState('');
  const [tVariables, setTVariables] = useState('');
  const [tActive, setTActive] = useState(true);
  const [tKeyError, setTKeyError] = useState('');
  const [tParticipantBuffer, setTParticipantBuffer] = useState<number>(0);
  const [tMaleBuffer, setTMaleBuffer] = useState(0);
  const [tFemaleBuffer, setTFemaleBuffer] = useState(0);
  const [tGenderRatioEnabled, setTGenderRatioEnabled] = useState(false);
  const [tGenderRatioBuffers, setTGenderRatioBuffers] = useState<{
    male_high: { m: number; f: number };
    female_high: { m: number; f: number };
  }>({ male_high: { m: 0, f: 0 }, female_high: { m: 0, f: 0 } });
  const [tRoundUnit, setTRoundUnit] = useState(10);
  const [tRoundMode, setTRoundMode] = useState<'ceil' | 'round' | 'floor'>('ceil');
  const [participantSettingsOpen, setParticipantSettingsOpen] = useState(false);
  const [varsOpen, setVarsOpen] = useState(false);

  // delete template
  const [deleteTemplateTarget, setDeleteTemplateTarget] = useState<Template | null>(null);

  // --- schedules state ---
  const [schedules, setSchedules] = useState<TemplateSchedule[]>([]);
  const [loadingSchedules, setLoadingSchedules] = useState(false);
  const [scheduleDialogOpen, setScheduleDialogOpen] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState<TemplateSchedule | null>(null);
  const [savingSchedule, setSavingSchedule] = useState(false);

  // schedule form
  const [sName, setSName] = useState('');
  const [sTemplateId, setSTemplateId] = useState<string>('');
  const [sType, setSType] = useState('daily');
  const [sHour, setSHour] = useState<string>('9');
  const [sMinute, setSMinute] = useState<string>('0');
  const [sDayOfWeek, setSDayOfWeek] = useState<string[]>([]);
  const [sIntervalMinutes, setSIntervalMinutes] = useState('10');
  const [sActiveStartHour, setSActiveStartHour] = useState<string>('');
  const [sActiveEndHour, setSActiveEndHour] = useState<string>('');

  const [sFilters, setSFilters] = useState<ScheduleFilter[]>([]);
  const [sTargetMode, setSTargetMode] = useState<'first_night' | 'last_night' | ''>('');
  const [sDateTarget, setSDateTarget] = useState<string>('today');
  const [sStayFilter, setSStayFilter] = useState<string>('');
  const sExcludeSent = true; // 항상 발송 완료 대상 제외
  const [assignmentState, setAssignmentState] = useState<AssignmentState>({
    room: false, room_buildings: [], room_include_unassigned: false,
    room_stay_exclude: false,
    party: false, unstable: false,
  });
  const [cmRows, setCmRows] = useState<{ column: string; operator: '' | 'contains' | 'not_contains' | 'is_empty' | 'is_not_empty'; text: string }[]>([{ column: 'party_type', operator: '', text: '' }]);
  const [sActive, setSActive] = useState(true);

  // event schedule state
  const [sCategory, setSCategory] = useState<'standard' | 'event' | 'custom_schedule'>('standard');
  const [sCustomType, setSCustomType] = useState('');
  const [customTypeOptions, setCustomTypeOptions] = useState<Array<{ value: string; label: string }>>([]);
  const [sHoursSinceBooking, setSHoursSinceBooking] = useState('');
  const [sGenderFilter, setSGenderFilter] = useState<'' | 'male' | 'female'>('');
  const [sMaxCheckinDays, setSMaxCheckinDays] = useState('');
  const [sExpiresAfterDays, setSExpiresAfterDays] = useState('');

  // send condition state
  const [sSendConditionEnabled, setSSendConditionEnabled] = useState(false);
  const [sSendConditionDate, setSSendConditionDate] = useState<'today' | 'tomorrow'>('tomorrow');
  const [sSendConditionRatio, setSSendConditionRatio] = useState('');
  const [sSendConditionOperator, setSSendConditionOperator] = useState<'gte' | 'lte'>('gte');

  // (filter picker state removed — replaced by toggle button UI)

  // buildings for filter
  const [buildings, setBuildings] = useState<Building[]>([]);

  // delete schedule
  const [deleteScheduleTarget, setDeleteScheduleTarget] = useState<TemplateSchedule | null>(null);

  // preview
  const [previewTargets, setPreviewTargets] = useState<any[]>([]);
  const [previewDialogOpen, setPreviewDialogOpen] = useState(false);

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  const fetchTemplates = async () => {
    setLoadingTemplates(true);
    try {
      const res = await templatesAPI.getAll();
      setTemplates(res.data);
    } catch {
      toast.error('템플릿 목록을 불러오지 못했습니다');
    } finally {
      setLoadingTemplates(false);
    }
  };

  const fetchSchedules = async () => {
    setLoadingSchedules(true);
    try {
      const res = await templateSchedulesAPI.getAll();
      setSchedules(res.data);
    } catch {
      toast.error('스케줄 목록을 불러오지 못했습니다');
    } finally {
      setLoadingSchedules(false);
    }
  };

  const fetchAvailableVariables = async () => {
    try {
      const res = await templatesAPI.getAvailableVariables();
      setAvailableVariables(res.data);
    } catch {
      /* non-critical */
    }
  };

  const fetchBuildings = async () => {
    try {
      const res = await buildingsAPI.getAll();
      setBuildings(res.data);
    } catch { /* non-critical */ }
  };

  useEffect(() => {
    fetchTemplates();
    fetchSchedules();
    fetchAvailableVariables();
    fetchBuildings();
    templateSchedulesAPI.getCustomTypes().then(res => setCustomTypeOptions(res.data)).catch(() => {});
  }, []);

  // ---------------------------------------------------------------------------
  // Template CRUD
  // ---------------------------------------------------------------------------

  const loadSampleExamples = () => {
    reservationsAPI.getAll({ limit: 20, status: 'confirmed' }).then(res => {
      const reservations = res.data.items ?? res.data;
      if (!reservations || reservations.length === 0) return;
      const pick = reservations[Math.floor(Math.random() * reservations.length)];
      const rn = pick.room_number || '';
      setSampleExamples({
        customer_name: pick.customer_name || '',
        phone: pick.phone || '',
        building: rn.length >= 2 ? rn[0] : '',
        room_num: rn.length >= 2 ? rn.slice(1) : rn,
        naver_room_type: pick.naver_room_type || '',
        room_password: pick.room_password || '',
        participant_count: String(pick.party_size || 1),
        male_count: String(pick.male_count || 0),
        female_count: String(pick.female_count || 0),
      });
    }).catch(() => {});
  };

  const PARTICIPANT_VARS = ['participant_count', 'male_count', 'female_count',
    'tomorrow_male_count', 'tomorrow_female_count', 'tomorrow_total_count',
    'yesterday_male_count', 'yesterday_female_count', 'yesterday_total_count'];

  const openCreateTemplate = () => {
    setEditingTemplate(null);
    setTKey(''); setTName(''); setTShortLabel(''); setTLmsTitle(''); setTContent('');
    setTVariables(''); setTActive(true); setTKeyError('');
    setTParticipantBuffer(0);
    setTMaleBuffer(0);
    setTFemaleBuffer(0);
    setTGenderRatioEnabled(false);
    setTGenderRatioBuffers({ male_high: { m: 0, f: 0 }, female_high: { m: 0, f: 0 } });
    setTRoundUnit(10);
    setTRoundMode('ceil');
    setParticipantSettingsOpen(false);
    setDetectedVars({ valid: [], invalid: [] });
    loadSampleExamples();
    setTemplateDialogOpen(true);
  };

  const openEditTemplate = (t: Template) => {
    setEditingTemplate(t);
    setTKey(t.template_key); setTName(t.name); setTShortLabel(t.short_label ?? '');
    setTLmsTitle(t.lms_title ?? '');
    setTContent(t.content); setTVariables(t.variables ?? '');
    setTActive(t.active); setTKeyError('');
    setTParticipantBuffer(t.participant_buffer || 0);
    setTMaleBuffer(t.male_buffer || 0);
    setTFemaleBuffer(t.female_buffer || 0);
    setTRoundUnit(t.round_unit || 0);
    setTRoundMode((t.round_mode as 'ceil' | 'round' | 'floor') || 'ceil');
    if (t.gender_ratio_buffers) {
      try {
        setTGenderRatioBuffers(JSON.parse(t.gender_ratio_buffers));
        setTGenderRatioEnabled(true);
      } catch { setTGenderRatioEnabled(false); }
    } else {
      setTGenderRatioEnabled(false);
    }
    setParticipantSettingsOpen(false);
    setDetectedVars(extractAndValidateVariables(t.content, availableVariables));
    loadSampleExamples();
    setTemplateDialogOpen(true);
  };

  const handleContentChange = (val: string) => {
    setTContent(val);
    const detected = extractAndValidateVariables(val, availableVariables);
    setDetectedVars(detected);
    setTVariables(detected.valid.join(','));
    const hasParticipantVars = PARTICIPANT_VARS.some(v => val.includes(`{{${v}}}`));
    if (hasParticipantVars) {
      setParticipantSettingsOpen(true);
    }
  };

  const handleSaveTemplate = async () => {
    if (!tKey.trim()) { setTKeyError('템플릿 키를 입력하세요'); return; }
    if (!/^[a-z_][a-z0-9_]*$/.test(tKey)) { setTKeyError('영문 소문자로 시작, 이후 영문 소문자/숫자/언더스코어(_)만 사용 가능합니다'); return; }
    if (!tName.trim()) { toast.error('템플릿 이름을 입력하세요'); return; }
    if (!tContent.trim()) { toast.error('메시지 내용을 입력하세요'); return; }

    // LMS 제목 EUC-KR 30바이트 제한 (한글 2바이트, ASCII 1바이트)
    const titleTrimmed = tLmsTitle.trim();
    if (titleTrimmed) {
      const titleBytes = [...titleTrimmed].reduce((s, ch) => s + (ch.charCodeAt(0) > 127 ? 2 : 1), 0);
      if (titleBytes > 30) {
        toast.error(`LMS 제목은 최대 30바이트입니다 (현재 ${titleBytes}바이트)`);
        return;
      }
    }

    setSavingTemplate(true);
    try {
      const data = {
        template_key: tKey, name: tName, content: tContent,
        short_label: tShortLabel || null,
        lms_title: tLmsTitle.trim() || null,
        variables: tVariables || undefined,
        active: tActive,
        participant_buffer: tParticipantBuffer,
        male_buffer: tMaleBuffer,
        female_buffer: tFemaleBuffer,
        gender_ratio_buffers: tGenderRatioEnabled ? JSON.stringify(tGenderRatioBuffers) : null,
        round_unit: tRoundUnit,
        round_mode: tRoundMode,
      };
      if (editingTemplate) {
        await templatesAPI.update(editingTemplate.id, data);
        toast.success('템플릿이 수정되었습니다');
      } else {
        await templatesAPI.create(data);
        toast.success('템플릿이 생성되었습니다');
      }
      setTemplateDialogOpen(false);
      fetchTemplates();
    } catch (err: any) {
      toast.error(err.response?.data?.detail ?? '템플릿 저장 실패');
    } finally {
      setSavingTemplate(false);
    }
  };

  const handleDeleteTemplate = async (t: Template) => {
    try {
      await templatesAPI.delete(t.id);
      toast.success('템플릿이 삭제되었습니다');
      fetchTemplates();
    } catch (err: any) {
      toast.error(err.response?.data?.detail ?? '템플릿 삭제 실패');
    } finally {
      setDeleteTemplateTarget(null);
    }
  };

  // 진행 중 reorder API 가 있으면 새 드래그 차단 — 응답 도착 순서 꼬임 방지.
  // useRef 사용: 리렌더 없이 동기적으로 read/write.
  const reorderingRef = useRef(false);

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    if (reorderingRef.current) {
      toast.info('이전 변경이 처리 중입니다. 잠시 후 다시 시도해주세요.', { id: 'template-reorder-busy' });
      return;
    }

    const oldIndex = templates.findIndex(t => t.id === active.id);
    const newIndex = templates.findIndex(t => t.id === over.id);
    if (oldIndex < 0 || newIndex < 0) return;

    const reordered = arrayMove(templates, oldIndex, newIndex);
    setTemplates(reordered); // 즉시 반영 (옵티미스틱)

    reorderingRef.current = true;
    templatesAPI
      .reorder(reordered.map(t => t.id))
      .catch((err: any) => {
        toast.error(err.response?.data?.detail ?? '순서 저장 실패');
        fetchTemplates(); // 롤백
      })
      .finally(() => {
        reorderingRef.current = false;
      });
  };

  const dndSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  // ---------------------------------------------------------------------------
  // Schedule CRUD
  // ---------------------------------------------------------------------------

  const resetScheduleForm = () => {
    setSName(''); setSTemplateId(''); setSType('daily');
    setSHour('9'); setSMinute('0'); setSDayOfWeek([]);
    setSIntervalMinutes('10'); setSActiveStartHour(''); setSActiveEndHour('');
    setSFilters([]);
    setSTargetMode('');
    setSDateTarget('today');
    setSStayFilter('');
    setCmRows([{ column: 'party_type', operator: '', text: '' }]);
    setSActive(true);
    setSCategory('standard');
    setSCustomType('');
    setSHoursSinceBooking('');
    setSGenderFilter('');
    setSMaxCheckinDays('');
    setSExpiresAfterDays('');
    setSSendConditionEnabled(false);
    setSSendConditionDate('tomorrow');
    setSSendConditionRatio('');
    setSSendConditionOperator('gte');
    setAssignmentState({
      room: false, room_buildings: [], room_include_unassigned: false,
      room_stay_exclude: false,
      party: false, unstable: false,
    });
  };

  const openCreateSchedule = () => {
    setEditingSchedule(null);
    resetScheduleForm();
    setScheduleDialogOpen(true);
  };

  const openEditSchedule = (s: TemplateSchedule) => {
    setEditingSchedule(s);
    setSName(s.schedule_name);
    setSTemplateId(String(s.template_id));
    setSType(s.schedule_type);
    setSHour(String(s.hour ?? 9));
    setSMinute(String(s.minute ?? 0));
    setSDayOfWeek(s.day_of_week ? s.day_of_week.split(',').map(d => d.trim()) : []);
    setSIntervalMinutes(String(s.interval_minutes ?? 10));
    setSActiveStartHour(s.active_start_hour != null ? String(s.active_start_hour) : '');
    setSActiveEndHour(s.active_end_hour != null ? String(s.active_end_hour) : '');
    const parsedFilters = parseFilters(s.filters);
    setSFilters(parsedFilters);
    setCmRows(parsedFilters.filter(f => f.type === 'column_match').map(f => {
      const parsed = parseColumnMatchValue(f.value);
      return parsed ? { column: parsed.column, operator: parsed.operator as any, text: parsed.text } : { column: 'party_type', operator: 'contains' as const, text: '' };
    }));
    setAssignmentState(parseAssignmentState(parsedFilters));
    const legacyMap: Record<string, string> = { once: 'first_night', daily: '', last_day: 'last_night' };
    setSTargetMode((legacyMap[s.target_mode ?? ''] ?? s.target_mode ?? '') as 'first_night' | 'last_night' | '');
    setSDateTarget(s.date_target || 'today');
    setSStayFilter(s.stay_filter || '');
    // sExcludeSent는 항상 true 고정
    setSActive(s.active);
    setSCategory(s.schedule_category || 'standard');
    setSCustomType(s.custom_type || '');
    setSHoursSinceBooking(s.hours_since_booking?.toString() || '');
    setSGenderFilter(s.gender_filter || '');
    setSMaxCheckinDays(s.max_checkin_days?.toString() || '');
    setSExpiresAfterDays(s.expires_after_days?.toString() || '');
    setSSendConditionEnabled(!!(s.send_condition_date && s.send_condition_ratio != null));
    setSSendConditionDate(s.send_condition_date || 'tomorrow');
    setSSendConditionRatio(s.send_condition_ratio?.toString() || '');
    setSSendConditionOperator(s.send_condition_operator || 'gte');
    setScheduleDialogOpen(true);
  };

  const buildSchedulePayload = () => {
    const hasActiveHours = (sType === 'hourly' || sType === 'interval')
      && sActiveStartHour !== '' && sActiveEndHour !== '';

    // Build v2 filters: assignment filters from assignmentState + column_match filters
    const assignmentFilters = sCategory === 'standard' ? buildAssignmentFilters(assignmentState) : [];
    const columnMatchFilters = sFilters.filter(f => f.type === 'column_match');
    const allFilters: ScheduleFilter[] = [...assignmentFilters, ...columnMatchFilters];

    return {
      schedule_name: sName,
      template_id: Number(sTemplateId),
      schedule_type: sType,
      hour: sType === 'daily' || sType === 'weekly' ? Number(sHour) : undefined,
      minute: sType === 'daily' || sType === 'weekly' || sType === 'hourly' ? Number(sMinute) : undefined,
      day_of_week: sType === 'weekly' ? sDayOfWeek.join(',') : undefined,
      interval_minutes: sType === 'interval' ? Number(sIntervalMinutes) : undefined,
      active_start_hour: hasActiveHours ? Number(sActiveStartHour) : null,
      active_end_hour: hasActiveHours ? Number(sActiveEndHour) : null,
      timezone: 'Asia/Seoul',
      filters: allFilters.length > 0 ? allFilters : undefined,
      date_target: sCategory === 'event' ? null : (sDateTarget || null),
      // event 카테고리는 schedule.stay_filter 컬럼을 단독 사용 (객실 배정 무관).
      // 그 외 standard/custom 은 v2 — stay options live inside room assignment filter.
      stay_filter: sCategory === 'event' ? (sStayFilter === 'exclude' ? 'exclude' : null) : null,
      target_mode: sCategory === 'event' ? null : (sTargetMode || null),
      exclude_sent: sExcludeSent,
      active: sActive,
      schedule_category: sCategory,
      custom_type: sCategory === 'custom_schedule' ? (sCustomType || null) : null,
      hours_since_booking: sCategory === 'event' ? (parseInt(sHoursSinceBooking) || null) : null,
      gender_filter: sCategory === 'event' ? (sGenderFilter || null) : null,
      max_checkin_days: sCategory === 'event' ? (parseInt(sMaxCheckinDays) || null) : null,
      expires_after_days: sCategory === 'event' ? (parseInt(sExpiresAfterDays) || null) : null,
      send_condition_date: (sCategory === 'standard' && sSendConditionEnabled) ? sSendConditionDate : null,
      send_condition_ratio: (sCategory === 'standard' && sSendConditionEnabled) ? (parseFloat(sSendConditionRatio) || null) : null,
      send_condition_operator: (sCategory === 'standard' && sSendConditionEnabled) ? sSendConditionOperator : null,
    };
  };

  const handleSaveSchedule = async () => {
    if (!sName.trim()) { toast.error('스케줄 이름을 입력하세요'); return; }
    if (!sTemplateId) { toast.error('템플릿을 선택하세요'); return; }
    if (sType === 'weekly' && sDayOfWeek.length === 0) { toast.error('요일을 선택하세요'); return; }
    if (sCategory === 'event' && !sHoursSinceBooking) { toast.error('예약 시점(시간)을 입력하세요'); return; }

    setSavingSchedule(true);
    try {
      const payload = buildSchedulePayload();
      if (editingSchedule) {
        await templateSchedulesAPI.update(editingSchedule.id, payload);
        toast.success('스케줄이 수정되었습니다');
      } else {
        await templateSchedulesAPI.create(payload);
        toast.success('스케줄이 생성되었습니다');
      }
      setScheduleDialogOpen(false);
      fetchSchedules();
    } catch (err: any) {
      toast.error(err.response?.data?.detail ?? '스케줄 저장 실패');
    } finally {
      setSavingSchedule(false);
    }
  };

  const handleDeleteSchedule = async (s: TemplateSchedule) => {
    try {
      await templateSchedulesAPI.delete(s.id);
      toast.success('스케줄이 삭제되었습니다');
      fetchSchedules();
    } catch (err: any) {
      toast.error(err.response?.data?.detail ?? '스케줄 삭제 실패');
    } finally {
      setDeleteScheduleTarget(null);
    }
  };

  const handleRunSchedule = async (id: number) => {
    const tid = toast.loading('실행 중...');
    try {
      const res = await templateSchedulesAPI.run(id);
      toast.success(`실행 완료: ${res.data.sent_count}명 발송, ${res.data.failed_count}명 실패`, { id: tid, duration: 5000 });
      fetchSchedules();
    } catch {
      toast.error('실행 실패', { id: tid });
    }
  };

  const handlePreviewTargets = async (id: number) => {
    try {
      const res = await templateSchedulesAPI.preview(id);
      setPreviewTargets(res.data);
      setPreviewDialogOpen(true);
    } catch {
      toast.error('대상 미리보기 실패');
    }
  };


  // ---------------------------------------------------------------------------
  // Day-of-week toggle helper
  // ---------------------------------------------------------------------------
  const toggleDay = (day: string) => {
    setSDayOfWeek(prev =>
      prev.includes(day) ? prev.filter(d => d !== day) : [...prev, day]
    );
  };

  // ---------------------------------------------------------------------------
  // Schedule filter toggle helpers
  // ---------------------------------------------------------------------------
  // Sync cmRows → sFilters (column_match entries)
  const syncCmRowsToFilters = (rows: typeof cmRows) => {
    const validFilters = rows
      .filter(r => {
        if (!r.operator) return false;
        if (r.operator === 'is_empty' || r.operator === 'is_not_empty') return true;
        return r.text.trim() !== '';
      })
      .map(r => ({
        type: 'column_match',
        value: `${r.column}:${r.operator}:${r.operator === 'is_empty' || r.operator === 'is_not_empty' ? '' : r.text.trim()}`,
      }));
    setSFilters(prev => [...prev.filter(f => f.type !== 'column_match'), ...validFilters]);
  };

  const updateCmRow = (index: number, updates: Partial<typeof cmRows[0]>) => {
    setCmRows(prev => {
      const next = prev.map((r, i) => i === index ? { ...r, ...updates } : r);
      syncCmRowsToFilters(next);
      return next;
    });
  };

  const addCmRow = () => {
    setCmRows(prev => [...prev, { column: 'party_type', operator: '', text: '' }]);
  };

  const removeCmRow = (index: number) => {
    setCmRows(prev => {
      const next = prev.filter((_, i) => i !== index);
      syncCmRowsToFilters(next);
      return next;
    });
  };


  // ---------------------------------------------------------------------------
  // Render – Tab 1: Templates
  // ---------------------------------------------------------------------------

  const renderTemplatesTab = () => (
    <div className="space-y-4">
      {/* Info banner + action */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-2xl border border-[#E8F3FF] bg-[#E8F3FF] px-4 py-3 dark:border-blue-800 dark:bg-blue-900/20">
        <span className="text-label text-[#3182F6] dark:text-blue-300">
          메시지 템플릿을 만들어두면 스케줄에서 자동으로 발송할 수 있습니다.{' '}
          <code className="rounded bg-[#F2F4F6] px-1 py-0.5 font-mono text-[#3182F6] dark:bg-blue-800/40">{'{{변수명}}'}</code>{' '}
          형식으로 변수를 사용하세요.
        </span>
        <Button color="blue" size="sm" onClick={openCreateTemplate} className="shrink-0 whitespace-nowrap">
          <Plus className="mr-1.5 h-3.5 w-3.5" />
          새 템플릿
        </Button>
      </div>

      {/* Table card */}
      <div className="section-card">
        {loadingTemplates ? (
          <div className="flex items-center justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : templates.length === 0 ? (
          <div className="empty-state">
            <FileText className="h-10 w-10" />
            <p className="text-body font-medium">템플릿이 없습니다</p>
            <p className="text-label">새 템플릿을 만들어 보세요</p>
          </div>
        ) : (
            <DndContext sensors={dndSensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
            <Table hoverable striped>
              <TableHead>
                <TableRow>
                  <TableHeadCell className="w-8 whitespace-nowrap" />
                  <TableHeadCell className="w-1 whitespace-nowrap">템플릿 이름</TableHeadCell>
                  <TableHeadCell className="w-1 whitespace-nowrap">축약명</TableHeadCell>
                  <TableHeadCell className="w-1 whitespace-nowrap">템플릿 키</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">사용 변수</TableHeadCell>
                  <TableHeadCell className="w-16 whitespace-nowrap text-center">상태</TableHeadCell>
                  <TableHeadCell className="w-16 whitespace-nowrap text-center">스케줄</TableHeadCell>
                  <TableHeadCell className="w-20 whitespace-nowrap text-center">작업</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                <SortableContext items={templates.map(t => t.id)} strategy={verticalListSortingStrategy}>
                {templates.map((t) => (
                  <SortableTemplateRow key={t.id} id={t.id}>
                    {({ listeners, attributes }) => (<>
                    <TableCell>
                      <button
                        type="button"
                        {...attributes}
                        {...listeners}
                        className="cursor-grab touch-none rounded p-1 text-[#B0B8C1] hover:bg-[#F2F4F6] hover:text-[#4E5968] dark:hover:bg-[#2C2C34] dark:hover:text-gray-300"
                        title="드래그해서 순서 변경"
                        aria-label="드래그 핸들"
                      >
                        <GripVertical className="h-4 w-4" />
                      </button>
                    </TableCell>
                    <TableCell>
                      <span className="font-medium text-gray-900 dark:text-white">{t.name}</span>
                    </TableCell>
                    <TableCell>
                      {t.short_label ? (
                        <span className="inline-flex items-center rounded-md bg-[#E8F3FF] px-1.5 py-0.5 text-caption font-medium text-[#3182F6] dark:bg-blue-900/20 dark:text-blue-400">
                          {t.short_label}
                        </span>
                      ) : (
                        <span className="text-caption text-gray-400 dark:text-gray-500">-</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <code className="rounded bg-[#F2F4F6] px-1.5 py-0.5 font-mono text-caption text-[#3182F6] dark:bg-gray-700 dark:text-blue-400">
                        {t.template_key}
                      </code>
                    </TableCell>
                    <TableCell>
                      {t.variables ? (() => {
                        let vars: string[] = [];
                        try {
                          const parsed = JSON.parse(t.variables);
                          vars = Array.isArray(parsed) ? parsed : [];
                        } catch {
                          vars = t.variables.replace(/[\[\]"]/g, '').split(',').map(s => s.trim()).filter(Boolean);
                        }
                        return vars.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {vars.map(v => (
                              <span key={v} className="inline-flex items-center rounded-md bg-[#F2F4F6] px-1.5 py-0.5 text-tiny font-medium text-[#4E5968] ring-1 ring-inset ring-[#E5E8EB] dark:bg-gray-800 dark:text-gray-300 dark:ring-gray-700">
                                {v}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-caption text-gray-400 dark:text-gray-500">없음</span>
                        );
                      })() : (
                        <span className="text-caption text-gray-400 dark:text-gray-500">없음</span>
                      )}
                    </TableCell>
                    <TableCell className="text-center">
                      <span className={`text-body font-medium ${t.active ? 'text-[#00C9A7]' : 'text-[#F04452]'}`}>
                        {t.active ? '활성' : '비활성'}
                      </span>
                    </TableCell>
                    <TableCell className="text-center">
                      {t.schedule_count > 0 ? (
                        <Badge color="info" size="sm">{t.schedule_count}개</Badge>
                      ) : (
                        <span className="text-caption text-gray-400 dark:text-gray-500">0</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-center gap-1">
                        <Button size="xs" color="light" onClick={() => openEditTemplate(t)} title="수정">
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button size="xs" color="failure" onClick={() => setDeleteTemplateTarget(t)} title="삭제">
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                    </>)}
                  </SortableTemplateRow>
                ))}
                </SortableContext>
              </TableBody>
            </Table>
            </DndContext>
        )}
      </div>
    </div>
  );

  // ---------------------------------------------------------------------------
  // Render – Tab 2: Schedules
  // ---------------------------------------------------------------------------

  const renderSchedulesTab = () => (
    <div className="space-y-4">
      {/* Info banner + actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-2xl border border-[#E8F3FF] bg-[#E8F3FF] px-4 py-3 dark:border-blue-800 dark:bg-blue-900/20">
        <span className="text-label text-[#3182F6] dark:text-blue-300">
          템플릿을 자동으로 발송할 시간을 설정합니다. 매일, 매주, 매시간, 또는 N분마다 발송할 수 있습니다.
        </span>
        <div className="flex items-center gap-2 shrink-0">
          {/* 동기화 버튼: 비상용 API만 유지, UI 숨김 (서버 시작 시 자동 로드 + CRUD 시 개별 반영됨) */}
          <Button color="blue" size="sm" className="whitespace-nowrap" onClick={openCreateSchedule}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            새 스케줄
          </Button>
        </div>
      </div>

      {/* Table card */}
      <div className="section-card">
        {loadingSchedules ? (
          <div className="flex items-center justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : schedules.length === 0 ? (
          <div className="empty-state">
            <Clock className="h-10 w-10" />
            <p className="text-body font-medium">스케줄이 없습니다</p>
            <p className="text-label">새 발송 스케줄을 만들어 보세요</p>
          </div>
        ) : (
            <Table hoverable striped>
              <TableHead>
                <TableRow>
                  <TableHeadCell className="whitespace-nowrap">스케줄 이름</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">사용 템플릿</TableHeadCell>
                  <TableHeadCell className="w-20 whitespace-nowrap">주기</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">발송 시간</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">발송 대상</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">다음 실행</TableHeadCell>
                  <TableHeadCell className="w-16 whitespace-nowrap text-center">상태</TableHeadCell>
                  <TableHeadCell className="w-28 whitespace-nowrap">작업</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {[...schedules].sort((a, b) => getFirstSendMinutes(a) - getFirstSendMinutes(b)).map(s => {
                  const nextRun = formatRelativeTime(s.next_run);
                  const isNextRunSoon = s.next_run && (() => {
                    const diff = new Date(normalizeUtcString(s.next_run!)).getTime() - Date.now();
                    return diff > 0 && diff < 3600000;
                  })();
                  return (
                    <TableRow key={s.id}>
                      <TableCell>
                        <div className="flex items-center gap-1.5">
                          <span className="font-medium text-gray-900 dark:text-white">{s.schedule_name}</span>
                          {s.schedule_category === 'event' && <Badge color="purple" size="sm">이벤트</Badge>}
                          {s.schedule_category === 'custom_schedule' && <Badge color="info" size="sm">커스텀</Badge>}
                          {s.schedule_category === 'event' && s.expires_at && (() => {
                            const expiresAt = new Date(normalizeUtcString(s.expires_at));
                            const now = new Date();
                            if (!s.active && expiresAt < now) {
                              return <Badge color="gray" size="sm">만료됨</Badge>;
                            }
                            return <span className="text-caption text-[#8B95A1] dark:text-gray-500">{expiresAt.getMonth() + 1}/{expiresAt.getDate()} 만료</span>;
                          })()}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-0.5">
                          <span className="text-body text-[#4E5968] dark:text-gray-300">{s.template_name}</span>
                          <code className="text-caption text-[#8B95A1] dark:text-gray-500">{s.template_key}</code>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge color={
                          s.schedule_type === 'daily' ? 'info'
                            : s.schedule_type === 'weekly' ? 'purple'
                            : s.schedule_type === 'hourly' ? 'success'
                            : s.schedule_type === 'interval' ? 'warning'
                            : 'gray'
                        } size="sm">{getScheduleTypeLabel(s.schedule_type)}</Badge>
                      </TableCell>
                      <TableCell>
                        <span className="text-body text-[#4E5968] dark:text-gray-300">{formatScheduleTime(s)}</span>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-1">
                          {getTargetSummary(s, buildings)}
                          {s.stay_filter === 'exclude' && <Badge color="warning" size="sm">연박제외</Badge>}
                          {(s.target_mode === 'last_night' || s.target_mode === 'last_day') && <Badge color="info" size="sm">마지막날만</Badge>}
                          {(s.target_mode === 'first_night' || s.target_mode === 'once') && <Badge color="purple" size="sm">첫날만</Badge>}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge color={isNextRunSoon ? 'warning' : 'gray'} size="sm">{nextRun}</Badge>
                      </TableCell>
                      <TableCell className="text-center">
                        <span className={`text-body font-medium ${s.active ? 'text-[#00C9A7]' : 'text-[#F04452]'}`}>
                          {s.active ? '활성' : '비활성'}
                        </span>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1">
                          <Button size="xs" color="light" onClick={() => openEditSchedule(s)} title="수정">
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button size="xs" color="light" onClick={() => handleRunSchedule(s.id)} title="즉시 실행">
                            <Play className="h-3.5 w-3.5" />
                          </Button>
                          <Button size="xs" color="light" onClick={() => handlePreviewTargets(s.id)} title="대상 미리보기">
                            <Eye className="h-3.5 w-3.5" />
                          </Button>
                          <Button size="xs" color="failure" onClick={() => setDeleteScheduleTarget(s)} title="삭제">
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
        )}
      </div>
    </div>
  );

  // ---------------------------------------------------------------------------
  // Render – Template dialog
  // ---------------------------------------------------------------------------

  const renderTemplateDialog = () => (
    <Modal show={templateDialogOpen} onClose={() => setTemplateDialogOpen(false)} size="5xl">
      <ModalHeader className="border-b border-[#F2F4F6] dark:border-gray-800 [&>h3]:flex-1">
        <div className="flex items-center justify-between w-full pr-4">
          <span>{editingTemplate ? '템플릿 수정' : '새 템플릿 만들기'}</span>
          {editingTemplate && (
            <div className="flex items-center gap-2">
              <span className={`text-caption font-medium ${tActive ? 'text-[#00C9A7]' : 'text-[#F04452]'}`}>
                {tActive ? '활성' : '비활성'}
              </span>
              <ToggleSwitch id="t-active-header" checked={tActive} onChange={setTActive} label="" />
            </div>
          )}
        </div>
      </ModalHeader>

      <ModalBody className="!p-0">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 p-6 h-[75dvh]">
          {/* Left column: settings */}
          <div className="space-y-5 overflow-y-auto pr-2">
            {/* Key */}
            <div>
              <Label htmlFor="t-key">
                템플릿 키 <span className="text-[#F04452] dark:text-red-400">*</span>
              </Label>
              <TextInput
                id="t-key"
                placeholder="영문 소문자와 _ (예: welcome_msg)"
                value={tKey}
                onChange={e => { setTKey(e.target.value); setTKeyError(''); }}
                disabled={!!editingTemplate}
                color={tKeyError ? 'failure' : undefined}
                className="mt-1"
              />
              {tKeyError && (
                <p className="text-caption text-[#F04452] dark:text-red-400 mt-1">{tKeyError}</p>
              )}
            </div>

            {/* Name */}
            <div>
              <Label htmlFor="t-name">
                템플릿 이름 <span className="text-[#F04452] dark:text-red-400">*</span>
              </Label>
              <TextInput
                id="t-name"
                placeholder="관리자용 이름 (예: 환영 메시지)"
                value={tName}
                onChange={e => setTName(e.target.value)}
                className="mt-1"
              />
            </div>

            {/* Short label */}
            <div>
              <Label htmlFor="t-short-label">축약명</Label>
              <TextInput
                id="t-short-label"
                placeholder="배정 페이지 칩 표시용 (예: 객안)"
                value={tShortLabel}
                onChange={e => setTShortLabel(e.target.value)}
                maxLength={10}
                className="mt-1"
              />
            </div>


            {/* 인원 표시 설정 */}
            <div className="space-y-3">
              <button
                type="button"
                onClick={() => setParticipantSettingsOpen(!participantSettingsOpen)}
                className="flex items-center gap-2 text-label font-medium text-[#4E5968] dark:text-gray-300"
              >
                {participantSettingsOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                인원 표시 설정
              </button>
              {participantSettingsOpen && (
                <div className="space-y-4 rounded-xl border border-[#E5E8EB] dark:border-gray-700 p-4">
                  {/* 총 인원 추가 (기존 participant_buffer) + 반올림 모드 */}
                  <div>
                    <label className="text-caption text-[#8B95A1] dark:text-gray-500 mb-1 block">총 인원 추가</label>
                    <div className="flex items-center gap-2">
                      <span className="text-label text-[#4E5968] dark:text-gray-300">총 인원 +</span>
                      <TextInput
                        type="number"
                        min={0}
                        value={tParticipantBuffer || ''}
                        placeholder="0"
                        onChange={(e) => setTParticipantBuffer(Number(e.target.value) || 0)}
                        className="w-14 [&_input]:!py-1"
                        sizing="sm"
                      />
                      <span className="text-label text-[#8B95A1]">명</span>
                      <span className="text-label text-[#B0B8C1] dark:text-gray-600">|</span>
                      <span className="text-label text-[#8B95A1]">10명 단위</span>
                      <select
                        value={tRoundMode}
                        onChange={(e) => setTRoundMode(e.target.value as 'ceil' | 'round' | 'floor')}
                        className="rounded-lg border border-[#E5E8EB] bg-white px-2.5 py-1.5 text-body text-gray-900 dark:border-gray-600 dark:bg-[#1E1E24] dark:text-white"
                      >
                        <option value="ceil">올림</option>
                        <option value="round">반올림</option>
                        <option value="floor">내림</option>
                      </select>
                    </div>
                    {(() => {
                      const example = 71;
                      const added = example + tParticipantBuffer;
                      const modeLabel = tRoundMode === 'ceil' ? '올림' : tRoundMode === 'round' ? '반올림' : '내림';
                      const rounded = tRoundMode === 'ceil'
                        ? Math.ceil(added / 10) * 10
                        : tRoundMode === 'round'
                          ? Math.round(added / 10) * 10
                          : Math.floor(added / 10) * 10;
                      return (
                        <p className="mt-1.5 text-tiny text-[#8B95A1] dark:text-gray-500">
                          예시) 총 인원이 {example}명이면 {example} + {tParticipantBuffer} + {modeLabel} 적용해서 <span className="font-semibold text-[#3182F6]">{rounded}명</span>으로 문자가 발송됩니다.
                        </p>
                      );
                    })()}
                  </div>

                  {/* 성별 인원 추가 */}
                  <div className={tGenderRatioEnabled ? 'opacity-40 pointer-events-none' : ''}>
                    <label className="text-caption text-[#8B95A1] dark:text-gray-500 mb-1 flex items-center gap-1.5">
                      성별 인원 추가
                      {tGenderRatioEnabled && <span className="text-tiny text-[#B0B8C1]">(조건부 추가 사용 중)</span>}
                    </label>
                    <div className="flex items-center gap-3">
                      <div className="flex items-center gap-1">
                        <span className="text-label text-[#4E5968] dark:text-gray-300">남자 +</span>
                        <TextInput
                          type="number"
                          min={0}
                          value={tMaleBuffer}
                          onChange={(e) => setTMaleBuffer(Number(e.target.value) || 0)}
                          className="w-14 [&_input]:!py-1"
                          sizing="sm"
                          disabled={tGenderRatioEnabled}
                        />
                      </div>
                      <div className="flex items-center gap-1">
                        <span className="text-label text-[#4E5968] dark:text-gray-300">여자 +</span>
                        <TextInput
                          type="number"
                          min={0}
                          value={tFemaleBuffer}
                          onChange={(e) => setTFemaleBuffer(Number(e.target.value) || 0)}
                          className="w-14 [&_input]:!py-1"
                          sizing="sm"
                          disabled={tGenderRatioEnabled}
                        />
                      </div>
                    </div>
                  </div>

                  {/* 성별 인원 조건부 추가 */}
                  <div>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={tGenderRatioEnabled}
                        onChange={(e) => setTGenderRatioEnabled(e.target.checked)}
                        className="rounded border-gray-300 text-blue-600"
                      />
                      <span className="text-label text-[#4E5968] dark:text-gray-300">성별 인원 조건부 추가</span>
                    </label>
                    {tGenderRatioEnabled && (
                      <div className="mt-2 space-y-1.5">
                        <div className="flex items-center gap-2">
                          <span className="text-caption text-[#8B95A1] w-[5.5rem] pl-[3px]">여자 &ge; 남자일 때</span>
                          <span className="text-label text-[#4E5968] dark:text-gray-300">남자 +</span>
                          <TextInput
                            type="number" min={0} className="w-14 [&_input]:!py-1" sizing="sm"
                            value={tGenderRatioBuffers.female_high.m}
                            onChange={(e) => setTGenderRatioBuffers(prev => ({
                              ...prev, female_high: { ...prev.female_high, m: Number(e.target.value) || 0 }
                            }))}
                          />
                          <span className="text-label text-[#4E5968] dark:text-gray-300">여자 +</span>
                          <TextInput
                            type="number" min={0} className="w-14 [&_input]:!py-1" sizing="sm"
                            value={tGenderRatioBuffers.female_high.f}
                            onChange={(e) => setTGenderRatioBuffers(prev => ({
                              ...prev, female_high: { ...prev.female_high, f: Number(e.target.value) || 0 }
                            }))}
                          />
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-caption text-[#8B95A1] w-[5.5rem] pl-[3px]">남자 &gt; 여자일 때</span>
                          <span className="text-label text-[#4E5968] dark:text-gray-300">남자 +</span>
                          <TextInput
                            type="number" min={0} className="w-14 [&_input]:!py-1" sizing="sm"
                            value={tGenderRatioBuffers.male_high.m}
                            onChange={(e) => setTGenderRatioBuffers(prev => ({
                              ...prev, male_high: { ...prev.male_high, m: Number(e.target.value) || 0 }
                            }))}
                          />
                          <span className="text-label text-[#4E5968] dark:text-gray-300">여자 +</span>
                          <TextInput
                            type="number" min={0} className="w-14 [&_input]:!py-1" sizing="sm"
                            value={tGenderRatioBuffers.male_high.f}
                            onChange={(e) => setTGenderRatioBuffers(prev => ({
                              ...prev, male_high: { ...prev.male_high, f: Number(e.target.value) || 0 }
                            }))}
                          />
                        </div>
                      </div>
                    )}
                  </div>


                  {/* 우선순위 안내 */}
                  <p className="text-tiny text-[#B0B8C1] dark:text-gray-600">
                    ⓘ 성별: 조건부 추가 &gt; 인원 추가 (둘 중 하나만 적용) / 총 인원 추가는 항상 적용
                  </p>
                </div>
              )}
            </div>

            {/* 사용 가능한 변수 — 접이식 칩 */}
            {availableVariables && (
              <div className="space-y-2">
                <button
                  type="button"
                  onClick={() => setVarsOpen(!varsOpen)}
                  className="flex items-center gap-2 text-label font-medium text-[#4E5968] dark:text-gray-300"
                >
                  {varsOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                  사용 가능한 변수
                </button>
                {varsOpen && (
                  <div className="flex flex-wrap gap-1">
                    {Object.entries(availableVariables.variables ?? {}).map(([varName, v]: [string, any]) => (
                      <span
                        key={varName}
                        title={`${v.description} (예: ${sampleExamples[varName] || v.example})`}
                        className="inline-flex items-center gap-1 rounded-md border border-[#E5E8EB] dark:border-gray-700 px-1.5 py-0.5 text-caption font-medium text-[#3182F6] dark:text-blue-400"
                      >
                        <code className="font-mono">{varName}</code>
                        <span className="text-[#B0B8C1] dark:text-gray-600">{v.description}</span>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}

          </div>

          {/* Right column: content */}
          <div className="flex flex-col gap-4 min-h-0">
            {/* LMS title (optional) */}
            <div className="space-y-2">
              <Label htmlFor="t-lms-title">
                LMS 제목 <span className="text-caption font-normal text-[#8B95A1]">(선택, LMS만 적용)</span>
              </Label>
              <input
                id="t-lms-title"
                type="text"
                placeholder="비워두면 본문 첫 줄을 자동 추출"
                value={tLmsTitle}
                onChange={e => setTLmsTitle(e.target.value)}
                maxLength={30}
                className="w-full rounded-lg border border-[#E5E8EB] bg-white px-3 py-2 text-body text-[#191F28] placeholder:text-[#B0B8C1] focus:border-[#3182F6] focus:outline-none focus:ring-1 focus:ring-[#3182F6] dark:border-gray-600 dark:bg-[#1E1E24] dark:text-gray-100 dark:placeholder:text-gray-600"
              />
              {(() => {
                const byteLen = [...tLmsTitle].reduce((sum, ch) => sum + (ch.charCodeAt(0) > 127 ? 2 : 1), 0);
                return (
                  <p className={`text-caption tabular-nums ${byteLen > 30 ? 'text-[#F04452]' : 'text-[#8B95A1]'}`}>
                    {byteLen}<span className="mx-0.5">/</span>30 bytes (한글 약 14자)
                  </p>
                );
              })()}
            </div>

            {/* Content */}
            <div className="flex flex-col flex-1 space-y-2 min-h-0">
              <Label htmlFor="t-content">
                메시지 내용 <span className="text-[#F04452] dark:text-red-400">*</span>
              </Label>

              <Textarea
                id="t-content"
                placeholder={`예시:\n안녕하세요 {{customer_name}}님!\n금일 객실은 {{building}}동 {{room_num}}호입니다.\n비밀번호: {{room_password}}`}
                value={tContent}
                onChange={e => handleContentChange(e.target.value)}
                className="font-mono text-body flex-1 min-h-0 [&_textarea]:!h-full"
              />
              {(() => {
                // EUC-KR 바이트 계산 (Aligo SMS 기준: 한글 2바이트, ASCII 1바이트)
                const byteLen = [...tContent].reduce((sum, ch) => sum + (ch.charCodeAt(0) > 127 ? 2 : 1), 0);
                return (
                  <p className={`text-caption tabular-nums ${byteLen > 2000 ? 'text-[#F04452]' : 'text-[#8B95A1]'}`}>
                    {byteLen.toLocaleString()}<span className="mx-0.5">/</span>2,000 bytes
                  </p>
                );
              })()}
            </div>

            {/* Detected variables */}
            {(detectedVars.valid.length > 0 || detectedVars.invalid.length > 0) && (
              <div className="rounded-2xl border border-[#F2F4F6] bg-[#F2F4F6] p-4 dark:border-gray-800 dark:bg-[#1E1E24]">
                <p className="mb-3 text-overline font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-gray-400">감지된 변수</p>
                <div className="space-y-3">
                  {detectedVars.valid.length > 0 && (
                    <div className="space-y-1.5">
                      <p className="flex items-center gap-1 text-caption font-medium text-[#00C9A7] dark:text-green-400">
                        <CheckCircle className="h-3 w-3" /> 유효한 변수
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {detectedVars.valid.map(v => (
                          <span
                            key={v}
                            className="inline-flex items-center gap-1 rounded-xl bg-[#E8FAF5] px-2 py-0.5 text-caption text-[#00C9A7] dark:bg-green-900/20 dark:text-green-400"
                          >
                            <CheckCircle className="h-3 w-3" />
                            <code className="font-mono">{`{{${v}}}`}</code>
                            {availableVariables?.variables?.[v] && (
                              <span className="text-[#00C9A7] dark:text-emerald-400"> — {availableVariables.variables[v].description}</span>
                            )}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {detectedVars.invalid.length > 0 && (
                    <div className="space-y-1.5">
                      <p className="flex items-center gap-1 text-caption font-medium text-[#F04452] dark:text-red-400">
                        <XCircle className="h-3 w-3" /> 유효하지 않은 변수
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {detectedVars.invalid.map(v => (
                          <span
                            key={v}
                            className="inline-flex items-center gap-1 rounded-xl bg-[#FFEBEE] px-2 py-0.5 text-caption text-[#F04452] dark:bg-red-900/20 dark:text-red-400"
                          >
                            <XCircle className="h-3 w-3" />
                            <code className="font-mono">{`{{${v}}}`}</code>
                            <span className="text-[#F04452] dark:text-red-400"> — 정의되지 않음</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

          </div>
        </div>
      </ModalBody>

      <ModalFooter>
        <Button color="light" onClick={() => setTemplateDialogOpen(false)}>취소</Button>
        <Button color="blue" onClick={handleSaveTemplate} disabled={savingTemplate}>
          {savingTemplate ? <><Spinner size="sm" className="mr-2" />저장 중...</> : '저장'}
        </Button>
      </ModalFooter>
    </Modal>
  );

  // ---------------------------------------------------------------------------
  // Render – Schedule dialog
  // ---------------------------------------------------------------------------

  const renderScheduleDialog = () => (
    <Modal show={scheduleDialogOpen} onClose={() => setScheduleDialogOpen(false)} size="3xl">
      <ModalHeader className="border-b border-[#F2F4F6] dark:border-gray-800 [&>h3]:flex-1">
        <div className="flex items-center justify-between w-full pr-4">
          <span>{editingSchedule ? '스케줄 수정' : '새 발송 스케줄 만들기'}</span>
          {editingSchedule && (
            <div className="flex items-center gap-2">
              <span className={`text-caption font-medium ${sActive ? 'text-[#00C9A7]' : 'text-[#F04452]'}`}>
                {sActive ? '활성' : '비활성'}
              </span>
              <ToggleSwitch id="s-active-header" checked={sActive} onChange={setSActive} label="" />
            </div>
          )}
        </div>
      </ModalHeader>

      <ModalBody>
        <div className="space-y-5">
          {/* Schedule name */}
          <div className="space-y-2">
            <Label>스케줄 이름 <span className="text-[#F04452] dark:text-red-400">*</span></Label>
            <TextInput
              placeholder="예: 파티 안내 자동 발송"
              value={sName}
              onChange={e => setSName(e.target.value)}
            />
            <p className="text-caption text-gray-400 dark:text-gray-500">관리하기 쉽게 알아보기 쉬운 이름을 지어주세요</p>
          </div>

          {/* Template */}
          <div className="space-y-2">
            <Label>발송할 템플릿 <span className="text-[#F04452] dark:text-red-400">*</span></Label>
            <Select value={sTemplateId} onChange={e => setSTemplateId(e.target.value)}>
              <option value="">템플릿 선택</option>
              {templates.map(t => (
                <option key={t.id} value={String(t.id)}>
                  {t.name} ({t.template_key})
                </option>
              ))}
            </Select>
          </div>

          {/* Schedule category toggle */}
          <div className="space-y-1.5">
            <div className="text-caption font-medium text-[#8B95A1] dark:text-gray-400">스케줄 유형</div>
            <div className="inline-flex rounded-lg overflow-hidden border border-[#E5E8EB] dark:border-gray-600">
              {[
                { value: 'standard' as const, label: '표준' },
                { value: 'event' as const, label: '이벤트' },
                { value: 'custom_schedule' as const, label: '커스텀' },
              ].map(opt => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => {
                    setSCategory(opt.value);
                    if (opt.value === 'event') {
                      setSDateTarget('today');
                      setSTargetMode('');
                      setSStayFilter('');
                      setSCustomType('');
                    } else if (opt.value === 'custom_schedule') {
                      setSHoursSinceBooking('');
                      setSGenderFilter('');
                      setSMaxCheckinDays('');
                      setSExpiresAfterDays('');
                      if (!sCustomType && customTypeOptions.length > 0) setSCustomType(customTypeOptions[0].value);
                    } else {
                      setSHoursSinceBooking('');
                      setSGenderFilter('');
                      setSMaxCheckinDays('');
                      setSExpiresAfterDays('');
                      setSCustomType('');
                    }
                  }}
                  className={`px-4 py-2.5 text-body font-medium transition-colors cursor-pointer border-r border-[#E5E8EB] dark:border-gray-600 last:border-r-0
                    ${sCategory === opt.value
                      ? 'bg-[#3182F6] text-white'
                      : 'bg-white text-[#B0B8C1] hover:bg-[#F2F4F6] dark:bg-[#1E1E24] dark:text-gray-500 dark:hover:bg-[#2C2C34]'
                    }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Custom schedule: 로직 타입 선택 */}
          {sCategory === 'custom_schedule' && (
            <div className="space-y-1.5">
              <div className="text-caption font-medium text-[#8B95A1] dark:text-gray-400">커스텀 로직</div>
              <Select value={sCustomType} onChange={e => setSCustomType(e.target.value)} sizing="sm">
                {customTypeOptions.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </Select>
              <p className="text-tiny text-[#B0B8C1] dark:text-gray-500">대상 선정 로직은 코드에서 관리됩니다. 발송 시간과 템플릿 내용만 수정 가능합니다.</p>
            </div>
          )}

          <div className="border-t border-[#E5E8EB] dark:border-gray-700" />

          {/* Schedule type + time in one row */}
          <div className="space-y-3">
            <Label>발송 주기 <span className="text-[#F04452] dark:text-red-400">*</span></Label>
            <div className="flex items-center gap-3 flex-wrap">
              <Select value={sType} onChange={e => setSType(e.target.value)} className="w-28">
                <option value="daily">매일</option>
                <option value="weekly">매주</option>
                <option value="hourly">매시간</option>
                <option value="interval">간격</option>
              </Select>

              {(sType === 'daily' || sType === 'weekly') && (
                <>
                  <Select value={sHour} onChange={e => setSHour(e.target.value)} className="w-24">
                    {Array.from({ length: 24 }, (_, i) => (
                      <option key={i} value={String(i)}>{String(i).padStart(2, '0')}시</option>
                    ))}
                  </Select>
                  <Select value={sMinute} onChange={e => setSMinute(e.target.value)} className="w-24">
                    {Array.from({ length: 60 }, (_, i) => (
                      <option key={i} value={String(i)}>{String(i).padStart(2, '0')}분</option>
                    ))}
                  </Select>
                </>
              )}

              {sType === 'hourly' && (
                <Select value={sMinute} onChange={e => setSMinute(e.target.value)} className="w-24">
                  {Array.from({ length: 60 }, (_, i) => (
                    <option key={i} value={String(i)}>{String(i).padStart(2, '0')}분</option>
                  ))}
                </Select>
              )}

              {sType === 'interval' && (
                <div className="flex items-center gap-2">
                  <TextInput
                    type="number"
                    min={1}
                    max={1440}
                    placeholder="10"
                    value={sIntervalMinutes}
                    onChange={e => setSIntervalMinutes(e.target.value)}
                    className="w-20"
                  />
                  <span className="text-body text-[#8B95A1] dark:text-gray-400">분마다</span>
                </div>
              )}
            </div>

            {sType === 'weekly' && (
              <div className="flex flex-wrap gap-2">
                {Object.entries(DAY_MAP).map(([k, v]) => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => toggleDay(k)}
                    className={`rounded-xl border px-3 py-1.5 text-body font-medium transition-colors ${
                      sDayOfWeek.includes(k)
                        ? 'border-[#3182F6] bg-[#3182F6] text-white'
                        : 'border-[#F2F4F6] bg-white text-[#4E5968] hover:bg-[#F2F4F6] dark:border-gray-600 dark:bg-gray-700 dark:text-gray-300'
                    }`}
                  >
                    {v}
                  </button>
                ))}
              </div>
            )}

            {/* Active hours — hourly/interval 타입에서만 표시 */}
            {(sType === 'hourly' || sType === 'interval') && (
              <div className="space-y-1.5">
                <div className="text-caption font-medium text-[#8B95A1] dark:text-gray-400">
                  활성화 시간 <span className="font-normal text-[#B0B8C1] dark:text-gray-600">(비워두면 하루 종일 실행)</span>
                </div>
                <div className="flex items-center gap-2">
                  <Select
                    value={sActiveStartHour}
                    onChange={e => setSActiveStartHour(e.target.value)}
                    className="w-24"
                  >
                    <option value="">시작 시</option>
                    {Array.from({ length: 24 }, (_, i) => (
                      <option key={i} value={String(i)}>{String(i).padStart(2, '0')}시</option>
                    ))}
                  </Select>
                  <span className="text-body text-[#8B95A1] dark:text-gray-400">~</span>
                  <Select
                    value={sActiveEndHour}
                    onChange={e => setSActiveEndHour(e.target.value)}
                    className="w-24"
                  >
                    <option value="">종료 시</option>
                    {Array.from({ length: 24 }, (_, i) => (
                      <option key={i} value={String(i)}>{String(i).padStart(2, '0')}시</option>
                    ))}
                  </Select>
                  {sActiveStartHour !== '' && sActiveEndHour !== '' && (
                    <span className="text-caption text-[#3182F6] dark:text-blue-400">
                      {sActiveStartHour}시 ~ {sActiveEndHour}시에만 실행
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* 발송 조건 — 표준 모드에서만 */}
          {sCategory === 'standard' && (
          <>
          <div className="border-t border-[#E5E8EB] dark:border-gray-700" />
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Label className="!mb-0">발송 조건</Label>
              <span className="text-caption text-[#B0B8C1] dark:text-gray-500">(선택)</span>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setSSendConditionEnabled(!sSendConditionEnabled)}
                className="cursor-pointer flex-shrink-0"
              >
                <div className={`w-4 h-4 rounded border-2 flex items-center justify-center
                  ${sSendConditionEnabled ? 'border-[#3182F6] bg-[#3182F6]' : 'border-[#B0B8C1] dark:border-gray-500'}`}>
                  {sSendConditionEnabled && <span className="text-white text-[10px]">✓</span>}
                </div>
              </button>
              <div className={`flex flex-wrap items-center gap-2 ${!sSendConditionEnabled ? 'opacity-40 pointer-events-none' : ''}`}>
                <select
                  value={sSendConditionDate}
                  onChange={e => setSSendConditionDate(e.target.value as 'today' | 'tomorrow')}
                  className="h-[34px] w-16 rounded-lg border border-[#E5E8EB] dark:border-gray-600 bg-white dark:bg-[#1E1E24] text-body px-1.5"
                >
                  <option value="today">오늘</option>
                  <option value="tomorrow">내일</option>
                </select>
                <span className="text-body text-[#4E5968] dark:text-gray-300">남녀 성비가</span>
                <TextInput
                  type="number"
                  min={0}
                  step={0.1}
                  placeholder="2"
                  value={sSendConditionRatio}
                  onChange={e => setSSendConditionRatio(e.target.value)}
                  sizing="sm"
                  className="w-16"
                />
                <span className="text-body text-[#4E5968] dark:text-gray-300">: 1</span>
                <select
                  value={sSendConditionOperator}
                  onChange={e => setSSendConditionOperator(e.target.value as 'gte' | 'lte')}
                  className="h-[34px] w-16 rounded-lg border border-[#E5E8EB] dark:border-gray-600 bg-white dark:bg-[#1E1E24] text-body px-1.5"
                >
                  <option value="gte">이상</option>
                  <option value="lte">이하</option>
                </select>
                <span className="text-body text-[#4E5968] dark:text-gray-300">이면 발송</span>
              </div>
            </div>
          </div>
          </>
          )}

          {/* Multi-filter target — 표준 모드에서만 표시 */}
          {sCategory === 'standard' && (
          <>
          <div className="border-t border-[#E5E8EB] dark:border-gray-700" />

          <div className="space-y-3">
            <Label>발송 대상 필터</Label>

            {/* Row 1: 대상 (v2 date_target) */}
            {sCategory === 'standard' && (
            <div className="space-y-1.5">
              <div className="text-caption font-medium text-[#8B95A1] dark:text-gray-400">대상</div>
              <div className="inline-flex rounded-lg overflow-hidden border border-[#E5E8EB] dark:border-gray-600">
                {[
                  { value: 'yesterday', label: '어제' },
                  { value: 'today', label: '오늘' },
                  { value: 'tomorrow', label: '내일' },
                ].map(opt => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setSDateTarget(opt.value)}
                    className={`px-3 py-2.5 text-body font-medium transition-colors cursor-pointer border-r border-[#E5E8EB] dark:border-gray-600 last:border-r-0
                      ${sDateTarget === opt.value
                        ? 'bg-[#3182F6] text-white'
                        : 'bg-white text-[#B0B8C1] hover:bg-[#F2F4F6] dark:bg-[#1E1E24] dark:text-gray-500 dark:hover:bg-[#2C2C34]'
                      }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
            )}

            {/* Row 2: Assignment status (segmented button) */}
            <div className="space-y-2">
              <div className="text-caption font-medium text-[#8B95A1] dark:text-gray-400">예약 유형</div>

              {/* Segmented button group — 다중 선택 */}
              <div className="inline-flex rounded-lg overflow-hidden border border-[#E5E8EB] dark:border-gray-600">
                {[
                  {
                    value: 'room',
                    label: '객실 예약',
                    active: assignmentState.room,
                    toggle: () => {
                      const next = !assignmentState.room;
                      setAssignmentState(prev => ({
                        ...prev,
                        room: next,
                        ...(next ? {} : { room_buildings: [], room_include_unassigned: false, room_stay_exclude: false }),
                      }));
                      if (!next) setSTargetMode('');
                    },
                  },
                  {
                    value: 'party',
                    label: '파티만',
                    active: assignmentState.party,
                    toggle: () => setAssignmentState(prev => ({ ...prev, party: !prev.party })),
                  },
                  ...(hasUnstable ? [{
                    value: 'unstable',
                    label: '언스테이블',
                    active: assignmentState.unstable,
                    toggle: () => setAssignmentState(prev => ({ ...prev, unstable: !prev.unstable })),
                  }] : []),
                ].map(btn => (
                  <button
                    key={btn.value}
                    type="button"
                    onClick={btn.toggle}
                    className={`px-3 py-2.5 text-body font-medium transition-colors cursor-pointer border-r border-[#E5E8EB] dark:border-gray-600 last:border-r-0
                      ${btn.active
                        ? 'bg-[#3182F6] text-white'
                        : 'bg-white text-[#B0B8C1] hover:bg-[#F2F4F6] dark:bg-[#1E1E24] dark:text-gray-500 dark:hover:bg-[#2C2C34]'
                      }`}
                  >
                    {btn.label}
                  </button>
                ))}
              </div>

              {/* 객실 배정 활성 시 하단 옵션 박스 */}
              {assignmentState.room && (
                <div className="space-y-3 rounded-xl border border-[#E5E8EB] dark:border-gray-700 p-3 mt-2">
                  {/* 건물 */}
                  {buildings.length > 0 && (
                    <div className="space-y-1.5">
                      <div className="text-caption text-[#8B95A1] dark:text-gray-500">건물</div>
                      <div className="flex flex-wrap gap-1.5">
                        {(() => {
                          const allSelected = assignmentState.room_buildings.length === 0;
                          return (
                            <button
                              type="button"
                              onClick={() => setAssignmentState(prev => ({ ...prev, room_buildings: [] }))}
                              className={`rounded-lg border px-3 py-1.5 text-body font-medium transition-colors cursor-pointer
                                ${allSelected
                                  ? 'border-[#3182F6] bg-[#3182F6] text-white'
                                  : 'border-[#E5E8EB] bg-white text-[#4E5968] hover:bg-[#F2F4F6] dark:border-gray-600 dark:bg-[#1E1E24] dark:text-gray-300 dark:hover:bg-[#2C2C34]'
                                }`}
                            >
                              전체
                            </button>
                          );
                        })()}
                        {[...buildings].reverse().map(b => {
                          const isSelected = assignmentState.room_buildings.includes(b.id);
                          return (
                            <button
                              key={b.id}
                              type="button"
                              onClick={() => setAssignmentState(prev => ({
                                ...prev,
                                room_buildings: isSelected
                                  ? prev.room_buildings.filter(id => id !== b.id)
                                  : [...prev.room_buildings, b.id],
                              }))}
                              className={`rounded-lg border px-3 py-1.5 text-body font-medium transition-colors cursor-pointer
                                ${isSelected
                                  ? 'border-[#3182F6] bg-[#3182F6] text-white'
                                  : 'border-[#E5E8EB] bg-white text-[#4E5968] hover:bg-[#F2F4F6] dark:border-gray-600 dark:bg-[#1E1E24] dark:text-gray-300 dark:hover:bg-[#2C2C34]'
                                }`}
                            >
                              {b.name}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* 발송 주기 */}
                  <div className="space-y-1.5">
                    <div className="text-caption text-[#8B95A1] dark:text-gray-500">발송 주기</div>
                    <div className="flex flex-wrap gap-1.5">
                      {[
                        { value: '' as const, label: '매일' },
                        { value: 'first_night' as const, label: '첫 투숙일' },
                        { value: 'last_night' as const, label: '마지막 투숙일' },
                      ].map(opt => (
                        <label
                          key={opt.value}
                          className={`rounded-lg border px-3 py-1.5 text-body font-medium cursor-pointer transition-colors
                            ${sTargetMode === opt.value
                              ? 'border-[#3182F6] bg-[#3182F6] text-white'
                              : 'border-[#E5E8EB] bg-white text-[#4E5968] hover:bg-[#F2F4F6] dark:border-gray-600 dark:bg-[#1E1E24] dark:text-gray-300 dark:hover:bg-[#2C2C34]'
                            }`}
                        >
                          <input
                            type="radio"
                            name="target_mode"
                            value={opt.value}
                            checked={sTargetMode === opt.value}
                            onChange={() => setSTargetMode(opt.value)}
                            className="sr-only"
                          />
                          {opt.label}
                        </label>
                      ))}
                    </div>
                  </div>

                  {/* 추가 옵션 */}
                  <div className="space-y-1.5">
                    <div className="text-caption text-[#8B95A1] dark:text-gray-500">추가 옵션</div>
                    <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={assignmentState.room_include_unassigned}
                          onChange={e => setAssignmentState(prev => ({ ...prev, room_include_unassigned: e.target.checked }))}
                          className="rounded border-gray-300 text-blue-600"
                        />
                        <span className="text-body text-[#4E5968] dark:text-gray-300">미배정 상태도 포함</span>
                      </label>
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={assignmentState.room_stay_exclude}
                          onChange={e => setAssignmentState(prev => ({ ...prev, room_stay_exclude: e.target.checked }))}
                          className="rounded border-gray-300 text-blue-600"
                        />
                        <span className="text-body text-[#4E5968] dark:text-gray-300">연박자 제외</span>
                      </label>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Row 3: Column match */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <div className="text-caption font-medium text-[#8B95A1] dark:text-gray-400">컬럼 조건</div>
                <button
                  type="button"
                  onClick={addCmRow}
                  className="text-caption font-medium text-[#3182F6] hover:text-[#1B64DA] cursor-pointer dark:text-blue-400"
                >
                  + 컬럼 조건 추가
                </button>
              </div>
              {cmRows.map((row, i) => (
                <div key={i} className="flex items-center gap-2">
                  <select
                    value={row.column}
                    onChange={e => updateCmRow(i, { column: e.target.value })}
                    className="rounded-lg border border-[#E5E8EB] bg-white px-3 py-2 text-body text-gray-900 dark:border-gray-600 dark:bg-[#1E1E24] dark:text-white"
                  >
                    {COLUMN_MATCH_OPTIONS.map(o => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                  <input
                    type="text"
                    value={row.text}
                    onChange={e => updateCmRow(i, { text: e.target.value })}
                    placeholder="검색 텍스트"
                    disabled={!row.operator || row.operator === 'is_empty' || row.operator === 'is_not_empty'}
                    className={`w-28 rounded-lg border border-[#E5E8EB] bg-white px-3 py-2 text-body text-gray-900 placeholder-[#B0B8C1] dark:border-gray-600 dark:bg-[#1E1E24] dark:text-white dark:placeholder-gray-500 ${
                      (!row.operator || row.operator === 'is_empty' || row.operator === 'is_not_empty') ? 'opacity-40 pointer-events-none' : ''
                    }`}
                  />
                  <div className="inline-flex rounded-lg overflow-hidden border border-[#E5E8EB] dark:border-gray-600">
                    {([
                      { value: 'contains' as const, label: '포함' },
                      { value: 'not_contains' as const, label: '미포함' },
                      { value: 'is_empty' as const, label: '비어있음' },
                      { value: 'is_not_empty' as const, label: '값 있음' },
                    ]).map(opt => (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => updateCmRow(i, { operator: opt.value })}
                        className={`px-3 py-2 text-body font-medium transition-colors cursor-pointer border-r border-[#E5E8EB] dark:border-gray-600 last:border-r-0
                          ${row.operator === opt.value
                            ? 'bg-[#3182F6] text-white'
                            : 'bg-white text-[#B0B8C1] hover:bg-[#F2F4F6] dark:bg-[#1E1E24] dark:text-gray-500 dark:hover:bg-[#2C2C34]'
                          }`}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                  {i > 0 && (
                    <button
                      type="button"
                      onClick={() => removeCmRow(i)}
                      className="text-[#B0B8C1] hover:text-[#F04452] cursor-pointer dark:text-gray-500 dark:hover:text-red-400"
                    >
                      ×
                    </button>
                  )}
                </div>
              ))}
            </div>

          </div>
          </>
          )}

          {/* 이벤트 조건 — 이벤트 모드에서만 표시 */}
          {sCategory === 'event' && (
          <>
          <div className="border-t border-[#E5E8EB] dark:border-gray-700" />
          <div className="space-y-3">
            <Label>이벤트 조건</Label>

            {/* 예약 시점 */}
            <div className="space-y-1.5">
              <div className="text-caption font-medium text-[#8B95A1] dark:text-gray-400">
                예약 시점 <span className="text-[#F04452] dark:text-red-400">*</span>
              </div>
              <div className="flex items-center gap-2">
                <TextInput
                  type="number"
                  min={1}
                  placeholder="24"
                  value={sHoursSinceBooking}
                  onChange={e => setSHoursSinceBooking(e.target.value)}
                  sizing="sm"
                  className="w-20"
                />
                <span className="text-body text-[#4E5968] dark:text-gray-300">시간 이내에 예약한 사람</span>
              </div>
            </div>

            {/* 성별 */}
            <div className="space-y-1.5">
              <div className="text-caption font-medium text-[#8B95A1] dark:text-gray-400">성별</div>
              <div className="inline-flex rounded-lg overflow-hidden border border-[#E5E8EB] dark:border-gray-600">
                {[
                  { value: '' as const, label: '전체' },
                  { value: 'male' as const, label: '남성' },
                  { value: 'female' as const, label: '여성' },
                ].map(opt => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setSGenderFilter(opt.value)}
                    className={`px-4 py-2.5 text-body font-medium transition-colors cursor-pointer border-r border-[#E5E8EB] dark:border-gray-600 last:border-r-0
                      ${sGenderFilter === opt.value
                        ? 'bg-[#3182F6] text-white'
                        : 'bg-white text-[#B0B8C1] hover:bg-[#F2F4F6] dark:bg-[#1E1E24] dark:text-gray-500 dark:hover:bg-[#2C2C34]'
                      }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* 체크인 기한 */}
            <div className="space-y-1.5">
              <div className="text-caption font-medium text-[#8B95A1] dark:text-gray-400">체크인 기한</div>
              <div className="flex items-center gap-2">
                <TextInput
                  type="number"
                  min={1}
                  placeholder="7"
                  value={sMaxCheckinDays}
                  onChange={e => setSMaxCheckinDays(e.target.value)}
                  sizing="sm"
                  className="w-20"
                />
                <span className="text-body text-[#4E5968] dark:text-gray-300">일 이내 체크인</span>
              </div>
              <p className="text-caption text-gray-400 dark:text-gray-500">비워두면 체크인 기한 제한 없이 발송합니다</p>
            </div>
          </div>

          {/* 운영 기간 */}
          <div className="border-t border-[#E5E8EB] dark:border-gray-700" />
          <div className="space-y-3">
            <Label>운영 기간</Label>
            <div className="space-y-1.5">
              <div className="text-caption font-medium text-[#8B95A1] dark:text-gray-400">만료</div>
              <div className="flex items-center gap-2">
                <TextInput
                  type="number"
                  min={1}
                  placeholder="7"
                  value={sExpiresAfterDays}
                  onChange={e => setSExpiresAfterDays(e.target.value)}
                  sizing="sm"
                  className="w-20"
                />
                <span className="text-body text-[#4E5968] dark:text-gray-300">일 후 자동 종료</span>
              </div>
              <p className="text-caption text-gray-400 dark:text-gray-500">비워두면 만료 없이 계속 실행됩니다</p>
            </div>
          </div>

          {/* 연박자 설정 — 이벤트 모드 (포함/제외만) */}
          <div className="border-t border-[#E5E8EB] dark:border-gray-700" />
          <div className="space-y-3">
            <Label>연박자 설정</Label>
            <div className="flex gap-2">
              {[
                { value: '', label: '포함', desc: '연박자에게도 발송합니다' },
                { value: 'exclude', label: '제외', desc: '연박자에게는 발송하지 않습니다' },
              ].map(opt => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setSStayFilter(opt.value)}
                  className={`flex items-center gap-3 px-4 py-3 rounded-xl border text-left transition-colors cursor-pointer flex-1
                    ${sStayFilter === opt.value
                      ? 'border-[#3182F6] bg-[#E8F3FF] dark:bg-[#3182F6]/15 dark:border-[#3182F6]'
                      : 'border-[#E5E8EB] bg-white hover:bg-[#F8F9FA] dark:border-gray-700 dark:bg-[#1E1E24] dark:hover:bg-[#2C2C34]'
                    }`}
                >
                  <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center flex-shrink-0
                    ${sStayFilter === opt.value ? 'border-[#3182F6]' : 'border-[#B0B8C1] dark:border-gray-500'}`}>
                    {sStayFilter === opt.value && <div className="w-2 h-2 rounded-full bg-[#3182F6]" />}
                  </div>
                  <div>
                    <p className={`text-body font-medium ${sStayFilter === opt.value ? 'text-[#3182F6]' : 'text-[#191F28] dark:text-white'}`}>{opt.label}</p>
                    <p className="text-caption text-[#8B95A1] dark:text-gray-500">{opt.desc}</p>
                  </div>
                </button>
              ))}
            </div>
          </div>
          </>
          )}

          <div className="border-t border-[#E5E8EB] dark:border-gray-700" />

        </div>
      </ModalBody>

      <ModalFooter className="border-t border-[#F2F4F6] dark:border-gray-800">
        <div className="flex flex-wrap items-center justify-between gap-3 w-full">
          {(() => {
            if (sCategory === 'event') {
              const eventParts: string[] = [];
              if (sHoursSinceBooking) eventParts.push(`${sHoursSinceBooking}시간 내 예약`);
              if (sGenderFilter === 'male') eventParts.push('남성');
              else if (sGenderFilter === 'female') eventParts.push('여성');
              if (sMaxCheckinDays) eventParts.push(`${sMaxCheckinDays}일 내 체크인`);
              if (sExpiresAfterDays) eventParts.push(`${sExpiresAfterDays}일 후 만료`);
              const eventChipColor = 'bg-[#F3E8FF] text-[#8B5CF6] dark:bg-[#8B5CF6]/15 dark:text-purple-300';
              return (
                <div className="flex items-center gap-1.5 flex-wrap text-caption flex-1 min-w-0">
                  <span className={`inline-flex rounded-md px-1.5 py-0.5 font-medium ${eventChipColor}`}>이벤트</span>
                  {eventParts.length > 0 && (
                    <>
                      <span className="text-[#B0B8C1] dark:text-gray-600">·</span>
                      <span className="text-[#4E5968] dark:text-gray-300">{eventParts.join(', ')}</span>
                    </>
                  )}
                  <span className="text-[#8B95A1] dark:text-gray-500">대상에게 발송</span>
                </div>
              );
            }

            const dateValue = (() => {
              switch (sDateTarget) {
                case 'yesterday': return '어제';
                case 'tomorrow': return '내일';
                default: return '오늘';
              }
            })();

            const columnMatchFilters = sFilters.filter(f => f.type === 'column_match');

            // Build assignment value label from assignmentState
            const assignmentParts: string[] = [];
            if (assignmentState.room) {
              const roomParts = ['객실배정'];
              if (assignmentState.room_buildings.length) {
                const names = assignmentState.room_buildings.map(id => buildings.find(b => b.id === id)?.name ?? `#${id}`);
                roomParts.push(`(${names.join(', ')})`);
              }
              if (assignmentState.room_include_unassigned) roomParts.push('+미배정');
              assignmentParts.push(roomParts.join(' '));
            }
            if (assignmentState.party) assignmentParts.push('파티만');
            if (assignmentState.unstable) assignmentParts.push('언스테이블');
            const assignmentValue = assignmentParts.join(', ');

            const cmValue = columnMatchFilters.map(f => {
              const parsed = parseColumnMatchValue(f.value);
              if (!parsed) return '';
              const colLabel = COLUMN_LABEL_MAP[parsed.column] || parsed.column;
              if (parsed.operator === 'is_empty') return `${colLabel} 비어있음`;
              if (parsed.operator === 'is_not_empty') return `${colLabel} 값 있음`;
              const opLabel = parsed.operator === 'not_contains' ? '미포함' : '포함';
              return `${colLabel} '${parsed.text}' ${opLabel}`;
            }).filter(Boolean).join(', ');

            const chips: { value: string; color: string }[] = [
              { value: dateValue, color: 'bg-[#E8F3FF] text-[#3182F6] dark:bg-[#3182F6]/15 dark:text-blue-300' },
            ];
            if (assignmentValue) chips.push({ value: assignmentValue, color: 'bg-[#E8FAF5] text-[#00C9A7] dark:bg-[#00C9A7]/15 dark:text-green-300' });
            if (cmValue) chips.push({ value: cmValue, color: 'bg-[#FFF4E8] text-[#FF9F00] dark:bg-[#FF9F00]/15 dark:text-yellow-300' });

            const stayChipColor = 'bg-[#F2F4F6] text-[#4E5968] dark:bg-gray-700 dark:text-gray-300';
            const showStayExclude = assignmentState.room && assignmentState.room_stay_exclude;

            return (
              <div className="flex items-center gap-1.5 flex-wrap text-caption flex-1 min-w-0">
                {chips.map((c, i) => (
                  <span key={i} className="flex items-center gap-1.5">
                    {i > 0 && <span className="text-[#B0B8C1] dark:text-gray-600">+</span>}
                    <span className={`inline-flex rounded-md px-1.5 py-0.5 font-medium ${c.color}`}>{c.value}</span>
                  </span>
                ))}
                <span className="text-[#8B95A1] dark:text-gray-500">예약자에게 발송</span>
                <span className="mx-1 h-3 w-px bg-[#8B95A1] dark:bg-gray-400 inline-block" />
                {showStayExclude ? (
                  <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                    <span className="text-[#8B95A1] dark:text-gray-500">연박자</span>
                    <span className="inline-flex rounded-md px-1.5 py-0.5 font-medium bg-[#FFEBEE] text-[#F04452] dark:bg-[#F04452]/15 dark:text-red-300">제외</span>
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                    <span className="text-[#8B95A1] dark:text-gray-500">연박일 경우,</span>
                    <span className={`inline-flex rounded-md px-1.5 py-0.5 font-medium ${stayChipColor}`}>
                      {sTargetMode === 'first_night' ? '첫 투숙일에만' : sTargetMode === 'last_night' ? '마지막 투숙일에만' : '매일'}
                    </span>
                    <span className="text-[#8B95A1] dark:text-gray-500">발송</span>
                  </span>
                )}
              </div>
            );
          })()}
          <div className="flex items-center gap-2 flex-shrink-0">
            <Button color="light" size="sm" onClick={() => setScheduleDialogOpen(false)}>취소</Button>
            <Button color="blue" size="sm" onClick={handleSaveSchedule} disabled={savingSchedule}>
              {savingSchedule ? <><Spinner size="sm" className="mr-2" />저장 중...</> : '저장'}
            </Button>
          </div>
        </div>
      </ModalFooter>
    </Modal>
  );

  // ---------------------------------------------------------------------------
  // Render – Preview targets dialog
  // ---------------------------------------------------------------------------

  const renderPreviewDialog = () => (
    <Modal show={previewDialogOpen} onClose={() => setPreviewDialogOpen(false)} size="2xl">
      <ModalHeader className="border-b border-[#F2F4F6] dark:border-gray-800">발송 대상 미리보기</ModalHeader>
      <ModalBody>
        <div className="space-y-4">
          <div className="rounded-2xl border border-[#E8F3FF] bg-[#E8F3FF] px-4 py-3 text-label text-[#3182F6] dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-300">
            아래 사람들에게 메시지가 발송됩니다. 중복 발송 방지가 켜져 있으면 이미 발송된 사람은 제외됩니다.
          </div>
          {previewTargets.length === 0 ? (
            <div className="empty-state py-10">
              <Eye className="h-8 w-8" />
              <p className="text-body">대상이 없습니다</p>
            </div>
          ) : (
            <div className="section-card">
                <Table hoverable striped>
                  <TableHead>
                    <TableRow>
                      <TableHeadCell className="w-12 whitespace-nowrap">ID</TableHeadCell>
                      <TableHeadCell className="whitespace-nowrap">이름</TableHeadCell>
                      <TableHeadCell className="whitespace-nowrap">전화번호</TableHeadCell>
                      <TableHeadCell className="whitespace-nowrap">객실</TableHeadCell>
                    </TableRow>
                  </TableHead>
                  <TableBody className="divide-y">
                    {previewTargets.map((p: any) => (
                      <TableRow key={p.id}>
                        <TableCell>
                          <span className="tabular-nums text-gray-400 dark:text-gray-500">{p.id}</span>
                        </TableCell>
                        <TableCell>
                          <span className="font-medium text-gray-900 dark:text-white">{p.customer_name}</span>
                        </TableCell>
                        <TableCell>
                          <code className="rounded bg-[#F2F4F6] px-1.5 py-0.5 font-mono text-caption text-[#3182F6] dark:bg-gray-700 dark:text-blue-400">
                            {p.phone}
                          </code>
                        </TableCell>
                        <TableCell>
                          <span className="text-body text-[#4E5968] dark:text-gray-300">{p.room_number ?? '-'}</span>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
            </div>
          )}
          <p className="text-body text-gray-500 dark:text-gray-400">
            총 <strong className="font-semibold text-[#191F28] dark:text-white">{previewTargets.length}명</strong>에게 발송됩니다
          </p>
        </div>
      </ModalBody>
      <ModalFooter>
        <Button color="light" onClick={() => setPreviewDialogOpen(false)}>닫기</Button>
      </ModalFooter>
    </Modal>
  );

  // ---------------------------------------------------------------------------
  // Root render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2.5">
          <div className="stat-icon bg-[#E8F3FF] text-[#3182F6] dark:bg-[#3182F6]/15 dark:text-[#3182F6]">
            <FileText size={20} />
          </div>
          <div>
            <h1 className="page-title">템플릿 관리</h1>
            <p className="page-subtitle">메시지 템플릿을 만들고 자동 발송 스케줄을 설정합니다.</p>
          </div>
        </div>
      </div>

      {/* Tab card */}
      <div className="section-card">
        <Tabs
          variant="underline"
          onActiveTabChange={idx => {
            const tabs = ['templates', 'schedules'];
            setActiveTab(tabs[idx] ?? 'templates');
          }}
        >
          <TabItem
            active={activeTab === 'templates'}
            title={
              <span className="flex items-center gap-1.5">
                <FileText className="h-3.5 w-3.5" />
                템플릿 관리
              </span>
            }
          >
            <div className="px-4 sm:px-6 pt-4 pb-6">
              {renderTemplatesTab()}
            </div>
          </TabItem>
          <TabItem
            active={activeTab === 'schedules'}
            title={
              <span className="flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5" />
                발송 스케줄
              </span>
            }
          >
            <div className="px-4 sm:px-6 pt-4 pb-6">
              {renderSchedulesTab()}
            </div>
          </TabItem>
        </Tabs>
      </div>

      {renderTemplateDialog()}
      {renderScheduleDialog()}
      {renderPreviewDialog()}

      <ConfirmDeleteDialog
        open={!!deleteTemplateTarget}
        message={
          deleteTemplateTarget?.schedule_count
            ? `이 템플릿에 ${deleteTemplateTarget.schedule_count}개의 스케줄이 연결되어 있습니다. 정말 삭제하시겠습니까?`
            : '정말로 이 템플릿을 삭제하시겠습니까?'
        }
        onConfirm={() => deleteTemplateTarget && handleDeleteTemplate(deleteTemplateTarget)}
        onCancel={() => setDeleteTemplateTarget(null)}
      />
      <ConfirmDeleteDialog
        open={!!deleteScheduleTarget}
        message="스케줄을 삭제하면 자동 발송이 중단됩니다. 정말 삭제하시겠습니까?"
        onConfirm={() => deleteScheduleTarget && handleDeleteSchedule(deleteScheduleTarget)}
        onCancel={() => setDeleteScheduleTarget(null)}
      />
    </div>
  );
};

export default Templates;
