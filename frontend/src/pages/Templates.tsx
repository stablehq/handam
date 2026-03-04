import React, { useState, useEffect } from 'react';
import { toast } from 'sonner';
import {
  Plus,
  Pencil,
  Trash2,
  Play,
  Eye,
  RefreshCw,
  CheckCircle,
  XCircle,
  ChevronDown,
  ChevronUp,
  FileText,
  Clock,
  BarChart3,
} from 'lucide-react';

import {
  Card,
  Tabs,
  TabItem,
  Modal,
  ModalHeader,
  ModalBody,
  ModalFooter,
  Button,
  TextInput,
  Textarea,
  Label,
  ToggleSwitch,
  Checkbox,
  Select,
  Radio,
  Table,
  TableHead,
  TableHeadCell,
  TableBody,
  TableRow,
  TableCell,
  Badge,
  Spinner,
  Alert,
} from 'flowbite-react';

import { templatesAPI, templateSchedulesAPI, campaignsAPI } from '@/services/api';

// ---------------------------------------------------------------------------
// Interfaces
// ---------------------------------------------------------------------------

interface Template {
  id: number;
  key: string;
  name: string;
  content: string;
  variables: string | null;
  category: string | null;
  active: boolean;
  created_at: string;
  updated_at: string;
  schedule_count: number;
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
  timezone: string;
  target_type: string;
  target_value: string | null;
  date_filter: string | null;
  sms_type: string;
  exclude_sent: boolean;
  active: boolean;
  created_at: string;
  updated_at: string;
  last_run: string | null;
  next_run: string | null;
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
  if (s.schedule_type === 'daily') {
    return `매일 ${s.hour}시 ${String(s.minute ?? 0).padStart(2, '0')}분`;
  }
  if (s.schedule_type === 'weekly') {
    const days = s.day_of_week?.split(',').map(d => DAY_MAP[d.trim()] ?? d).join(', ');
    return `${days}요일 ${s.hour}시 ${String(s.minute ?? 0).padStart(2, '0')}분`;
  }
  if (s.schedule_type === 'hourly') {
    return `매시간 ${String(s.minute ?? 0).padStart(2, '0')}분`;
  }
  if (s.schedule_type === 'interval') {
    return `${s.interval_minutes}분마다`;
  }
  return '-';
}

function formatRelativeTime(iso: string | null): string {
  if (!iso) return '-';
  const date = new Date(iso);
  const diff = date.getTime() - Date.now();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 0) return date.toLocaleString('ko-KR');
  if (minutes < 60) return `${minutes}분 후`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}시간 후`;
  return date.toLocaleString('ko-KR');
}

function getCampaignTypeLabel(type: string): string {
  if (type === 'room_guide') return '객실안내';
  if (type === 'party_guide') return '파티안내';
  if (type === 'tag_based') return '태그발송';
  if (type.startsWith('template_schedule_') && type.includes('파티')) return '자동발송(파티)';
  if (type.startsWith('template_schedule_') && type.includes('객실')) return '자동발송(객실)';
  if (type.startsWith('template_schedule_')) return '자동발송';
  return type;
}

function getScheduleTypeLabel(type: string): string {
  const map: Record<string, string> = {
    daily: '매일', weekly: '매주', hourly: '매시간', interval: '간격',
  };
  return map[type] ?? type;
}

function getTargetLabel(record: TemplateSchedule): string {
  const map: Record<string, string> = {
    all: '전체',
    room_assigned: '객실배정자',
    party_only: '파티만',
  };
  if (record.target_type === 'tag') return `태그: ${record.target_value}`;
  return map[record.target_type] ?? record.target_type;
}

const CATEGORY_LABELS: Record<string, string> = {
  room_guide: '객실안내',
  party_guide: '파티안내',
  confirmation: '예약확인',
  reminder: '리마인더',
  other: '기타',
};

const CATEGORY_ICON: Record<string, string> = {
  reservation: '예약 정보',
  room: '객실 정보',
  party: '파티 정보',
  datetime: '날짜/시간',
  other: '기타',
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface ConfirmDeleteProps {
  open: boolean;
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}

function ConfirmDeleteDialog({ open, message, onConfirm, onCancel }: ConfirmDeleteProps) {
  return (
    <Modal show={open} onClose={onCancel} size="sm">
      <ModalHeader className="border-b border-[#F2F4F6] dark:border-gray-800">삭제 확인</ModalHeader>
      <ModalBody>
        <div className="text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-[#FFEBEE] dark:bg-red-900/20">
            <Trash2 className="h-6 w-6 text-[#F04452] dark:text-red-400" />
          </div>
          <h3 className="mb-2 text-body font-semibold text-[#191F28] dark:text-white">정말 삭제하시겠습니까?</h3>
          <p className="mb-5 text-label text-[#8B95A1] dark:text-gray-400">{message}</p>
        </div>
      </ModalBody>
      <ModalFooter className="flex justify-center gap-3 border-t border-[#F2F4F6] dark:border-gray-800">
        <Button color="failure" size="sm" onClick={onConfirm}>삭제</Button>
        <Button color="light" size="sm" onClick={onCancel}>취소</Button>
      </ModalFooter>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const Templates: React.FC = () => {
  const [activeTab, setActiveTab] = useState('templates');

  // --- templates state ---
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [templateDialogOpen, setTemplateDialogOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<Template | null>(null);
  const [availableVariables, setAvailableVariables] = useState<any>(null);
  const [detectedVars, setDetectedVars] = useState<{ valid: string[]; invalid: string[] }>({ valid: [], invalid: [] });
  const [showVarRef, setShowVarRef] = useState(false);
  const [savingTemplate, setSavingTemplate] = useState(false);

  // template form
  const [tKey, setTKey] = useState('');
  const [tName, setTName] = useState('');
  const [tCategory, setTCategory] = useState('');
  const [tContent, setTContent] = useState('');
  const [tVariables, setTVariables] = useState('');
  const [tActive, setTActive] = useState(true);
  const [tKeyError, setTKeyError] = useState('');

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
  const [sTargetType, setSTargetType] = useState('all');
  const [sTargetValue, setSTargetValue] = useState('');
  const [sDateFilter, setSDateFilter] = useState('');
  const [sSmsType, setSSmsType] = useState('room');
  const [sExcludeSent, setSExcludeSent] = useState(true);
  const [sActive, setSActive] = useState(true);

  // delete schedule
  const [deleteScheduleTarget, setDeleteScheduleTarget] = useState<TemplateSchedule | null>(null);

  // preview
  const [previewTargets, setPreviewTargets] = useState<any[]>([]);
  const [previewDialogOpen, setPreviewDialogOpen] = useState(false);

  // --- campaigns state ---
  const [campaigns, setCampaigns] = useState<any[]>([]);
  const [loadingCampaigns, setLoadingCampaigns] = useState(false);

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

  const fetchCampaigns = async () => {
    setLoadingCampaigns(true);
    try {
      const res = await campaignsAPI.getHistory();
      setCampaigns(res.data);
    } catch {
      toast.error('발송 이력을 불러오지 못했습니다');
    } finally {
      setLoadingCampaigns(false);
    }
  };

  useEffect(() => {
    fetchTemplates();
    fetchSchedules();
    fetchAvailableVariables();
  }, []);

  useEffect(() => {
    if (activeTab === 'campaigns') fetchCampaigns();
  }, [activeTab]);

  // ---------------------------------------------------------------------------
  // Template CRUD
  // ---------------------------------------------------------------------------

  const openCreateTemplate = () => {
    setEditingTemplate(null);
    setTKey(''); setTName(''); setTCategory(''); setTContent('');
    setTVariables(''); setTActive(true); setTKeyError('');
    setDetectedVars({ valid: [], invalid: [] });
    setShowVarRef(false);
    setTemplateDialogOpen(true);
  };

  const openEditTemplate = (t: Template) => {
    setEditingTemplate(t);
    setTKey(t.key); setTName(t.name); setTCategory(t.category ?? '');
    setTContent(t.content); setTVariables(t.variables ?? '');
    setTActive(t.active); setTKeyError('');
    setDetectedVars(extractAndValidateVariables(t.content, availableVariables));
    setShowVarRef(false);
    setTemplateDialogOpen(true);
  };

  const handleContentChange = (val: string) => {
    setTContent(val);
    const detected = extractAndValidateVariables(val, availableVariables);
    setDetectedVars(detected);
    setTVariables(detected.valid.join(','));
  };

  const handleSaveTemplate = async () => {
    if (!tKey.trim()) { setTKeyError('템플릿 키를 입력하세요'); return; }
    if (!/^[a-z_]+$/.test(tKey)) { setTKeyError('영문 소문자와 언더스코어(_)만 사용 가능합니다'); return; }
    if (!tName.trim()) { toast.error('템플릿 이름을 입력하세요'); return; }
    if (!tContent.trim()) { toast.error('메시지 내용을 입력하세요'); return; }

    setSavingTemplate(true);
    try {
      const data = {
        key: tKey, name: tName, content: tContent,
        variables: tVariables || undefined,
        category: tCategory || undefined,
        active: tActive,
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

  // ---------------------------------------------------------------------------
  // Schedule CRUD
  // ---------------------------------------------------------------------------

  const resetScheduleForm = () => {
    setSName(''); setSTemplateId(''); setSType('daily');
    setSHour('9'); setSMinute('0'); setSDayOfWeek([]);
    setSIntervalMinutes('10'); setSTargetType('all');
    setSTargetValue(''); setSDateFilter('');
    setSSmsType('room'); setSExcludeSent(true); setSActive(true);
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
    setSTargetType(s.target_type);
    setSTargetValue(s.target_value ?? '');
    setSDateFilter(s.date_filter ?? '');
    setSSmsType(s.sms_type);
    setSExcludeSent(s.exclude_sent);
    setSActive(s.active);
    setScheduleDialogOpen(true);
  };

  const buildSchedulePayload = () => ({
    schedule_name: sName,
    template_id: Number(sTemplateId),
    schedule_type: sType,
    hour: sType === 'daily' || sType === 'weekly' ? Number(sHour) : undefined,
    minute: sType === 'daily' || sType === 'weekly' || sType === 'hourly' ? Number(sMinute) : undefined,
    day_of_week: sType === 'weekly' ? sDayOfWeek.join(',') : undefined,
    interval_minutes: sType === 'interval' ? Number(sIntervalMinutes) : undefined,
    timezone: 'Asia/Seoul',
    target_type: sTargetType,
    target_value: sTargetType === 'tag' ? sTargetValue : undefined,
    date_filter: sDateFilter || undefined,
    sms_type: sSmsType,
    exclude_sent: sExcludeSent,
    active: sActive,
  });

  const handleSaveSchedule = async () => {
    if (!sName.trim()) { toast.error('스케줄 이름을 입력하세요'); return; }
    if (!sTemplateId) { toast.error('템플릿을 선택하세요'); return; }
    if (sType === 'weekly' && sDayOfWeek.length === 0) { toast.error('요일을 선택하세요'); return; }
    if (sTargetType === 'tag' && !sTargetValue.trim()) { toast.error('태그 이름을 입력하세요'); return; }

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

  const handleSyncSchedules = async () => {
    const tid = toast.loading('동기화 중...');
    try {
      const res = await templateSchedulesAPI.sync();
      toast.success(res.data.message, { id: tid, duration: 3000 });
      fetchSchedules();
    } catch {
      toast.error('동기화 실패', { id: tid });
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
  // Render – Tab 1: Templates
  // ---------------------------------------------------------------------------

  const renderTemplatesTab = () => (
    <div className="space-y-4">
      {/* Info banner + action */}
      <div className="flex items-center gap-4">
        <div className="flex-1 rounded-2xl border border-[#E8F3FF] bg-[#E8F3FF] px-4 py-3 text-label text-[#3182F6] dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-300">
          메시지 템플릿을 만들어두면 스케줄에서 자동으로 발송할 수 있습니다.{' '}
          <code className="rounded bg-[#F2F4F6] px-1 py-0.5 font-mono text-[#3182F6] dark:bg-blue-800/40">{'{{변수명}}'}</code>{' '}
          형식으로 변수를 사용하세요.
        </div>
        <Button size="sm" onClick={openCreateTemplate}>
          <Plus className="mr-1.5 h-4 w-4" />
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
          <div className="overflow-x-auto">
            <Table hoverable striped>
              <TableHead>
                <TableRow>
                  <TableHeadCell className="w-12 whitespace-nowrap">ID</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">템플릿 키</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap min-w-[120px]">템플릿 이름</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">카테고리</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">사용 변수</TableHeadCell>
                  <TableHeadCell className="w-16 whitespace-nowrap">상태</TableHeadCell>
                  <TableHeadCell className="w-16 whitespace-nowrap">스케줄</TableHeadCell>
                  <TableHeadCell className="w-20 whitespace-nowrap">작업</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {templates.map(t => (
                  <TableRow key={t.id}>
                    <TableCell>
                      <span className="tabular-nums text-gray-400 dark:text-gray-500">{t.id}</span>
                    </TableCell>
                    <TableCell>
                      <code className="rounded bg-[#F2F4F6] px-1.5 py-0.5 font-mono text-caption text-[#3182F6] dark:bg-gray-700 dark:text-blue-400">
                        {t.key}
                      </code>
                    </TableCell>
                    <TableCell>
                      <span className="font-medium text-gray-900 dark:text-white">{t.name}</span>
                    </TableCell>
                    <TableCell>
                      {t.category ? (
                        <Badge color="indigo" size="sm">{CATEGORY_LABELS[t.category] ?? t.category}</Badge>
                      ) : (
                        <span className="text-[#B0B8C1] dark:text-gray-500">-</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {t.variables ? (
                        <div className="flex flex-wrap gap-1">
                          {t.variables.split(',').filter(Boolean).map(v => (
                            <Badge key={v} color="purple" size="sm">
                              <code className="font-mono">{v.trim()}</code>
                            </Badge>
                          ))}
                        </div>
                      ) : (
                        <span className="text-caption text-gray-400 dark:text-gray-500">없음</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge color={t.active ? 'success' : 'gray'} size="sm">
                        {t.active ? '활성' : '비활성'}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {t.schedule_count > 0 ? (
                        <Badge color="blue" size="sm">{t.schedule_count}개</Badge>
                      ) : (
                        <span className="text-caption text-gray-400 dark:text-gray-500">0</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Button size="xs" color="light" onClick={() => openEditTemplate(t)} title="수정">
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button size="xs" color="failure" onClick={() => setDeleteTemplateTarget(t)} title="삭제">
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
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
      <div className="flex items-center gap-4">
        <div className="flex-1 rounded-2xl border border-[#E8F3FF] bg-[#E8F3FF] px-4 py-3 text-label text-[#3182F6] dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-300">
          템플릿을 자동으로 발송할 시간을 설정합니다. 매일, 매주, 매시간, 또는 N분마다 발송할 수 있습니다.
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" color="light" onClick={handleSyncSchedules}>
            <RefreshCw className="mr-1.5 h-4 w-4" />
            동기화
          </Button>
          <Button size="sm" onClick={openCreateSchedule}>
            <Plus className="mr-1.5 h-4 w-4" />
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
          <div className="overflow-x-auto">
            <Table hoverable striped>
              <TableHead>
                <TableRow>
                  <TableHeadCell className="w-12 whitespace-nowrap">ID</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">스케줄 이름</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">사용 템플릿</TableHeadCell>
                  <TableHeadCell className="w-20 whitespace-nowrap">주기</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">발송 시간</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">발송 대상</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">다음 실행</TableHeadCell>
                  <TableHeadCell className="w-16 whitespace-nowrap">상태</TableHeadCell>
                  <TableHeadCell className="w-28 whitespace-nowrap">작업</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {schedules.map(s => {
                  const nextRun = formatRelativeTime(s.next_run);
                  const isNextRunSoon = s.next_run && (() => {
                    const diff = new Date(s.next_run!).getTime() - Date.now();
                    return diff > 0 && diff < 3600000;
                  })();
                  return (
                    <TableRow key={s.id}>
                      <TableCell>
                        <span className="tabular-nums text-gray-400 dark:text-gray-500">{s.id}</span>
                      </TableCell>
                      <TableCell>
                        <span className="font-medium text-gray-900 dark:text-white">{s.schedule_name}</span>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-0.5">
                          <span className="text-body text-[#4E5968] dark:text-gray-300">{s.template_name}</span>
                          <code className="text-caption text-[#8B95A1] dark:text-gray-500">{s.template_key}</code>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge color="indigo" size="sm">{getScheduleTypeLabel(s.schedule_type)}</Badge>
                      </TableCell>
                      <TableCell>
                        <span className="text-body text-[#4E5968] dark:text-gray-300">{formatScheduleTime(s)}</span>
                      </TableCell>
                      <TableCell>
                        <Badge color="gray" size="sm">{getTargetLabel(s)}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge color={isNextRunSoon ? 'warning' : 'gray'} size="sm">{nextRun}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge color={s.active ? 'success' : 'gray'} size="sm">
                          {s.active ? '활성' : '비활성'}
                        </Badge>
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
          </div>
        )}
      </div>
    </div>
  );

  // ---------------------------------------------------------------------------
  // Render – Tab 3: Campaign history
  // ---------------------------------------------------------------------------

  const renderCampaignsTab = () => (
    <div className="space-y-4">
      {/* Info banner + action */}
      <div className="flex items-center gap-4">
        <div className="flex-1 rounded-2xl border border-[#E8F3FF] bg-[#E8F3FF] px-4 py-3 text-label text-[#3182F6] dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-300">
          지금까지 발송한 메시지 이력입니다. 템플릿 스케줄 자동 발송과 수동 발송 모두 기록됩니다.
        </div>
        <Button size="sm" color="light" onClick={fetchCampaigns} disabled={loadingCampaigns}>
          {loadingCampaigns ? (
            <Spinner size="sm" className="mr-1.5" />
          ) : (
            <RefreshCw className="mr-1.5 h-4 w-4" />
          )}
          새로고침
        </Button>
      </div>

      {/* Table card */}
      <div className="section-card">
        {loadingCampaigns ? (
          <div className="flex items-center justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : campaigns.length === 0 ? (
          <div className="empty-state">
            <BarChart3 className="h-10 w-10" />
            <p className="text-body font-medium">발송 이력이 없습니다</p>
            <p className="text-label">스케줄 또는 수동 발송 후 이력이 기록됩니다</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table hoverable striped>
              <TableHead>
                <TableRow>
                  <TableHeadCell className="w-12 whitespace-nowrap">ID</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">발송 타입</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">대상 태그</TableHeadCell>
                  <TableHeadCell className="w-20 whitespace-nowrap">대상 수</TableHeadCell>
                  <TableHeadCell className="w-20 whitespace-nowrap">성공</TableHeadCell>
                  <TableHeadCell className="w-20 whitespace-nowrap">실패</TableHeadCell>
                  <TableHeadCell className="whitespace-nowrap">발송 일시</TableHeadCell>
                </TableRow>
              </TableHead>
              <TableBody className="divide-y">
                {campaigns.map(c => (
                  <TableRow key={c.id}>
                    <TableCell>
                      <span className="tabular-nums text-gray-400 dark:text-gray-500">{c.id}</span>
                    </TableCell>
                    <TableCell>
                      <Badge color="indigo" size="sm">{getCampaignTypeLabel(c.campaign_type)}</Badge>
                    </TableCell>
                    <TableCell>
                      {c.target_tag ? (
                        <Badge color="purple" size="sm">{c.target_tag}</Badge>
                      ) : (
                        <span className="text-[#B0B8C1] dark:text-gray-500">-</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <span className="tabular-nums font-medium text-gray-900 dark:text-white">{c.target_count}</span>
                    </TableCell>
                    <TableCell>
                      <Badge color="success" size="sm">{c.sent_count}</Badge>
                    </TableCell>
                    <TableCell>
                      {c.failed_count > 0 ? (
                        <Badge color="failure" size="sm">{c.failed_count}</Badge>
                      ) : (
                        <span className="text-caption text-gray-400 dark:text-gray-500">0</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <span className="text-body text-gray-500 dark:text-gray-400">
                        {c.sent_at ? new Date(c.sent_at).toLocaleString('ko-KR') : '-'}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </div>
  );

  // ---------------------------------------------------------------------------
  // Render – Template dialog
  // ---------------------------------------------------------------------------

  const renderTemplateDialog = () => (
    <Modal show={templateDialogOpen} onClose={() => setTemplateDialogOpen(false)} size="2xl">
      <ModalHeader className="border-b border-[#F2F4F6] dark:border-gray-800">
        {editingTemplate ? '템플릿 수정' : '새 템플릿 만들기'}
      </ModalHeader>

      <ModalBody>
        <div className="space-y-5">
          {/* Key */}
          <div className="space-y-2">
            <Label htmlFor="t-key">
              템플릿 키 <span className="text-[#F04452] dark:text-red-400">*</span>
            </Label>
            <TextInput
              id="t-key"
              placeholder="예: welcome_message"
              value={tKey}
              onChange={e => { setTKey(e.target.value); setTKeyError(''); }}
              disabled={!!editingTemplate}
              color={tKeyError ? 'failure' : undefined}
            />
            {tKeyError ? (
              <p className="text-caption text-[#F04452] dark:text-red-400">{tKeyError}</p>
            ) : (
              <p className="text-caption text-gray-400 dark:text-gray-500">시스템 고유 식별자. 영문 소문자와 _ 만 허용됩니다.</p>
            )}
          </div>

          {/* Name */}
          <div className="space-y-2">
            <Label htmlFor="t-name">
              템플릿 이름 <span className="text-[#F04452] dark:text-red-400">*</span>
            </Label>
            <TextInput
              id="t-name"
              placeholder="예: 환영 메시지"
              value={tName}
              onChange={e => setTName(e.target.value)}
            />
            <p className="text-caption text-gray-400 dark:text-gray-500">관리자가 보는 이름입니다. 한글로 작성하세요.</p>
          </div>

          {/* Category */}
          <div className="space-y-2">
            <Label>카테고리</Label>
            <Select value={tCategory} onChange={e => setTCategory(e.target.value)}>
              <option value="">카테고리 선택 (선택사항)</option>
              <option value="room_guide">객실 안내</option>
              <option value="party_guide">파티 안내</option>
              <option value="confirmation">예약 확인</option>
              <option value="reminder">리마인더</option>
              <option value="other">기타</option>
            </Select>
          </div>

          {/* Content */}
          <div className="space-y-2">
            <Label htmlFor="t-content">
              메시지 내용 <span className="text-[#F04452] dark:text-red-400">*</span>
            </Label>
            <Textarea
              id="t-content"
              rows={8}
              placeholder={`예시:\n안녕하세요 {{name}}님!\n금일 객실은 {{building}}동 {{roomNum}}호입니다.\n비밀번호: {{password}}`}
              value={tContent}
              onChange={e => handleContentChange(e.target.value)}
              className="font-mono text-body"
            />
            <p className="text-caption text-gray-400 dark:text-gray-500">
              <code className="rounded bg-[#F2F4F6] px-1 py-0.5 font-mono text-[#3182F6] dark:bg-gray-700 dark:text-blue-400">{'{{변수명}}'}</code>{' '}
              형식으로 변수를 삽입하세요
            </p>
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

          {/* Available variables reference (collapsible) */}
          {availableVariables && (
            <div className="rounded-2xl border border-[#F2F4F6] dark:border-gray-800">
              <button
                type="button"
                className="flex w-full items-center justify-between px-4 py-3 text-body font-medium text-[#4E5968] hover:bg-[#F2F4F6] dark:text-gray-300 dark:hover:bg-[#2C2C34]"
                onClick={() => setShowVarRef(v => !v)}
              >
                <span>사용 가능한 변수 참고</span>
                {showVarRef ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              </button>
              {showVarRef && (
                <div className="border-t border-[#F2F4F6] px-4 py-4 dark:border-gray-800">
                  <div className="space-y-4">
                    {Object.entries(availableVariables.categories ?? {}).map(([cat, vars]: [string, any]) => (
                      <div key={cat}>
                        <p className="mb-2 text-overline font-semibold uppercase tracking-wide text-[#8B95A1] dark:text-gray-400">
                          {CATEGORY_ICON[cat] ?? cat}
                        </p>
                        <div className="flex flex-wrap gap-1.5">
                          {(vars as any[]).map((v: any) => (
                            <span
                              key={v.name}
                              className="inline-flex items-center gap-1 rounded-xl bg-[#F2F4F6] px-2 py-0.5 text-caption text-[#4E5968] dark:bg-gray-700 dark:text-gray-300"
                            >
                              <code className="font-mono text-[#3182F6] dark:text-blue-400">{`{{${v.name}}}`}</code>
                              <span className="text-[#8B95A1] dark:text-gray-400"> — {v.description}</span>
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Active */}
          <div className="flex items-center justify-between rounded-2xl border border-[#F2F4F6] px-4 py-3 dark:border-gray-800">
            <div>
              <p className="text-body font-medium text-gray-900 dark:text-white">활성 상태</p>
              <p className="text-caption text-gray-400 dark:text-gray-500">비활성화하면 이 템플릿을 사용할 수 없습니다</p>
            </div>
            <ToggleSwitch id="t-active" checked={tActive} onChange={setTActive} label="" />
          </div>
        </div>
      </ModalBody>

      <ModalFooter className="flex justify-end gap-2 border-t border-[#F2F4F6] dark:border-gray-800">
        <Button color="blue" size="sm" onClick={handleSaveTemplate} disabled={savingTemplate}>
          {savingTemplate ? <><Spinner size="sm" className="mr-2" />저장 중...</> : '저장'}
        </Button>
        <Button color="light" size="sm" onClick={() => setTemplateDialogOpen(false)}>취소</Button>
      </ModalFooter>
    </Modal>
  );

  // ---------------------------------------------------------------------------
  // Render – Schedule dialog
  // ---------------------------------------------------------------------------

  const renderScheduleDialog = () => (
    <Modal show={scheduleDialogOpen} onClose={() => setScheduleDialogOpen(false)} size="2xl">
      <ModalHeader className="border-b border-[#F2F4F6] dark:border-gray-800">
        {editingSchedule ? '스케줄 수정' : '새 발송 스케줄 만들기'}
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
                  {t.name} ({t.key})
                </option>
              ))}
            </Select>
          </div>

          <div className="border-t border-[#F2F4F6] dark:border-gray-800" />

          {/* Schedule type */}
          <div className="space-y-3">
            <Label>발송 주기 <span className="text-[#F04452] dark:text-red-400">*</span></Label>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {[
                { value: 'daily', label: '매일' },
                { value: 'weekly', label: '매주' },
                { value: 'hourly', label: '매시간' },
                { value: 'interval', label: '간격' },
              ].map(opt => (
                <label
                  key={opt.value}
                  className={`flex cursor-pointer items-center justify-center gap-2 rounded-xl border px-3 py-2.5 text-body font-medium transition-colors ${
                    sType === opt.value
                      ? 'border-[#3182F6] bg-[#E8F3FF] text-[#3182F6] dark:border-blue-400 dark:bg-blue-900/20 dark:text-blue-300'
                      : 'border-[#F2F4F6] bg-white text-[#4E5968] hover:bg-[#F2F4F6] dark:border-gray-600 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-[#2C2C34]'
                  }`}
                >
                  <Radio
                    name="scheduleType"
                    value={opt.value}
                    checked={sType === opt.value}
                    onChange={() => setSType(opt.value)}
                    className="hidden"
                  />
                  <span>{opt.label}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Dynamic time fields */}
          {sType === 'daily' && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label>시 (Hour)</Label>
                <Select value={sHour} onChange={e => setSHour(e.target.value)}>
                  {Array.from({ length: 24 }, (_, i) => (
                    <option key={i} value={String(i)}>{String(i).padStart(2, '0')}시</option>
                  ))}
                </Select>
              </div>
              <div className="space-y-2">
                <Label>분 (Minute)</Label>
                <Select value={sMinute} onChange={e => setSMinute(e.target.value)}>
                  {Array.from({ length: 60 }, (_, i) => (
                    <option key={i} value={String(i)}>{String(i).padStart(2, '0')}분</option>
                  ))}
                </Select>
              </div>
            </div>
          )}

          {sType === 'weekly' && (
            <div className="space-y-3">
              <div className="space-y-2">
                <Label>요일</Label>
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
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label>시</Label>
                  <Select value={sHour} onChange={e => setSHour(e.target.value)}>
                    {Array.from({ length: 24 }, (_, i) => (
                      <option key={i} value={String(i)}>{String(i).padStart(2, '0')}시</option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>분</Label>
                  <Select value={sMinute} onChange={e => setSMinute(e.target.value)}>
                    {Array.from({ length: 60 }, (_, i) => (
                      <option key={i} value={String(i)}>{String(i).padStart(2, '0')}분</option>
                    ))}
                  </Select>
                </div>
              </div>
            </div>
          )}

          {sType === 'hourly' && (
            <div className="space-y-2">
              <Label>분 (Minute)</Label>
              <Select value={sMinute} onChange={e => setSMinute(e.target.value)}>
                {Array.from({ length: 60 }, (_, i) => (
                  <option key={i} value={String(i)}>매시간 {String(i).padStart(2, '0')}분</option>
                ))}
              </Select>
              <p className="text-caption text-gray-400 dark:text-gray-500">매시간 이 분에 발송됩니다 (예: 10분 → 1:10, 2:10, 3:10...)</p>
            </div>
          )}

          {sType === 'interval' && (
            <div className="space-y-2">
              <Label>간격 (분)</Label>
              <div className="flex items-center gap-2">
                <TextInput
                  type="number"
                  min={1}
                  max={1440}
                  placeholder="예: 10"
                  value={sIntervalMinutes}
                  onChange={e => setSIntervalMinutes(e.target.value)}
                  className="w-32"
                />
                <span className="text-body text-gray-500 dark:text-gray-400">분마다</span>
              </div>
              <p className="text-caption text-gray-400 dark:text-gray-500">N분마다 반복 발송됩니다</p>
            </div>
          )}

          <div className="border-t border-[#F2F4F6] dark:border-gray-800" />

          {/* Target type */}
          <div className="space-y-2">
            <Label>발송 대상 <span className="text-[#F04452] dark:text-red-400">*</span></Label>
            <Select value={sTargetType} onChange={e => setSTargetType(e.target.value)}>
              <option value="all">전체 예약자</option>
              <option value="tag">특정 태그가 있는 사람</option>
              <option value="room_assigned">객실이 배정된 사람</option>
              <option value="party_only">파티만 참석하는 사람</option>
            </Select>
          </div>

          {sTargetType === 'tag' && (
            <div className="space-y-2">
              <Label>태그 이름 <span className="text-[#F04452] dark:text-red-400">*</span></Label>
              <TextInput
                placeholder="예: 파티만"
                value={sTargetValue}
                onChange={e => setSTargetValue(e.target.value)}
              />
              <p className="text-caption text-gray-400 dark:text-gray-500">예약자에게 붙은 태그를 입력하세요 (예: 파티만, 1초, 2차만)</p>
            </div>
          )}

          {/* Date filter */}
          <div className="space-y-2">
            <Label>날짜 필터</Label>
            <Select value={sDateFilter} onChange={e => setSDateFilter(e.target.value)}>
              <option value="">필터 없음 (모든 날짜)</option>
              <option value="today">오늘 예약자</option>
              <option value="tomorrow">내일 예약자</option>
            </Select>
          </div>

          {/* SMS type */}
          <div className="space-y-3">
            <Label>SMS 유형</Label>
            <div className="flex gap-3">
              {[
                { value: 'room', label: '객실 (Room)' },
                { value: 'party', label: '파티 (Party)' },
              ].map(opt => (
                <label
                  key={opt.value}
                  className={`flex cursor-pointer items-center gap-2 rounded-xl border px-4 py-2.5 text-body font-medium transition-colors ${
                    sSmsType === opt.value
                      ? 'border-[#3182F6] bg-[#E8F3FF] text-[#3182F6] dark:border-blue-400 dark:bg-blue-900/20 dark:text-blue-300'
                      : 'border-[#F2F4F6] bg-white text-[#4E5968] hover:bg-[#F2F4F6] dark:border-gray-600 dark:bg-gray-700 dark:text-gray-300'
                  }`}
                >
                  <Radio
                    name="smsType"
                    value={opt.value}
                    checked={sSmsType === opt.value}
                    onChange={() => setSSmsType(opt.value)}
                    className="hidden"
                  />
                  <span>{opt.label}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Exclude sent */}
          <div className="flex items-start gap-3 rounded-2xl border border-[#F2F4F6] px-4 py-3 dark:border-gray-800">
            <Checkbox
              id="s-exclude"
              checked={sExcludeSent}
              onChange={e => setSExcludeSent(e.target.checked)}
              className="mt-0.5"
            />
            <div>
              <label htmlFor="s-exclude" className="cursor-pointer text-body font-medium text-gray-900 dark:text-white">
                이미 발송된 대상은 제외
              </label>
              <p className="text-caption text-gray-400 dark:text-gray-500">이미 발송한 사람에게는 다시 보내지 않습니다</p>
            </div>
          </div>

          {/* Active */}
          <div className="flex items-center justify-between rounded-2xl border border-[#F2F4F6] px-4 py-3 dark:border-gray-800">
            <div>
              <p className="text-body font-medium text-gray-900 dark:text-white">활성 상태</p>
              <p className="text-caption text-gray-400 dark:text-gray-500">비활성화하면 자동 발송이 중단됩니다</p>
            </div>
            <ToggleSwitch id="s-active" checked={sActive} onChange={setSActive} label="" />
          </div>
        </div>
      </ModalBody>

      <ModalFooter className="flex justify-end gap-2 border-t border-[#F2F4F6] dark:border-gray-800">
        <Button color="blue" size="sm" onClick={handleSaveSchedule} disabled={savingSchedule}>
          {savingSchedule ? <><Spinner size="sm" className="mr-2" />저장 중...</> : '저장'}
        </Button>
        <Button color="light" size="sm" onClick={() => setScheduleDialogOpen(false)}>취소</Button>
      </ModalFooter>
    </Modal>
  );

  // ---------------------------------------------------------------------------
  // Render – Preview targets dialog
  // ---------------------------------------------------------------------------

  const renderPreviewDialog = () => (
    <Modal show={previewDialogOpen} onClose={() => setPreviewDialogOpen(false)} size="4xl">
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
              <div className="overflow-x-auto">
                <Table hoverable striped>
                  <TableHead>
                    <TableRow>
                      <TableHeadCell className="w-12 whitespace-nowrap">ID</TableHeadCell>
                      <TableHeadCell className="whitespace-nowrap">이름</TableHeadCell>
                      <TableHeadCell className="whitespace-nowrap">전화번호</TableHeadCell>
                      <TableHeadCell className="whitespace-nowrap">객실</TableHeadCell>
                      <TableHeadCell className="whitespace-nowrap">발송 완료</TableHeadCell>
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
                        <TableCell>
                          <div className="flex gap-1">
                            {p.room_sms_sent && <Badge color="blue" size="sm">객실</Badge>}
                            {p.party_sms_sent && <Badge color="purple" size="sm">파티</Badge>}
                            {!p.room_sms_sent && !p.party_sms_sent && (
                              <span className="text-caption text-gray-400 dark:text-gray-500">없음</span>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}
          <p className="text-body text-gray-500 dark:text-gray-400">
            총 <strong className="font-semibold text-[#191F28] dark:text-white">{previewTargets.length}명</strong>에게 발송됩니다
          </p>
        </div>
      </ModalBody>
      <ModalFooter className="flex justify-end border-t border-[#F2F4F6] dark:border-gray-800">
        <Button size="sm" onClick={() => setPreviewDialogOpen(false)}>확인</Button>
      </ModalFooter>
    </Modal>
  );

  // ---------------------------------------------------------------------------
  // Root render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-6 p-6">
      {/* Page header */}
      <div>
        <div className="flex items-center gap-2.5">
          <div className="stat-icon bg-[#F3EEFF] text-[#7B61FF] dark:bg-violet-900/30 dark:text-violet-400">
            <FileText size={20} />
          </div>
          <div>
            <h1 className="page-title">메시지 템플릿 및 스케줄 관리</h1>
            <p className="page-subtitle">템플릿을 만들고 자동 발송 스케줄을 설정하세요</p>
          </div>
        </div>
      </div>

      {/* Tab card */}
      <div className="section-card">
        <Tabs
          variant="underline"
          onActiveTabChange={idx => {
            const tabs = ['templates', 'schedules', 'campaigns'];
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
            <div className="px-6 pb-6">
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
            <div className="px-6 pb-6">
              {renderSchedulesTab()}
            </div>
          </TabItem>
          <TabItem
            active={activeTab === 'campaigns'}
            title={
              <span className="flex items-center gap-1.5">
                <BarChart3 className="h-3.5 w-3.5" />
                발송 이력
              </span>
            }
          >
            <div className="px-6 pb-6">
              {renderCampaignsTab()}
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
