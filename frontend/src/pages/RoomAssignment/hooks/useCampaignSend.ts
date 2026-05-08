import { useCallback, useEffect, useRef, useState } from 'react';
import type { Dayjs } from 'dayjs';
import { toast } from 'sonner';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { reservationsAPI } from '../../../services/api';
import { queryKeys } from '@/lib/queryKeys';
import type { Reservation } from '../types';

interface TemplateLabel {
  template_key: string;
  name: string;
  short_label: string | null;
}

interface UseCampaignSendProps {
  reservations: Reservation[];
  selectedDate: Dayjs;
  templateLabels: TemplateLabel[];
  onConfirmRequest: () => void;
  onConfirmClose: () => void;
}

/**
 * 캠페인 일괄 발송 흐름(템플릿 선택 → 대상조회 → 확인 모달 → API 호출).
 *
 * Phase B-2: RoomAssignment.tsx 의 selectedTemplateKey/campaignDropdownOpen/targets/sending 통합.
 * Phase 3b: smsSendByTag → useMutation. Backend 200 + !success → throw.
 */
export function useCampaignSend({
  reservations,
  selectedDate,
  templateLabels,
  onConfirmRequest,
  onConfirmClose,
}: UseCampaignSendProps) {
  const qc = useQueryClient();
  const [selectedTemplateKey, setSelectedTemplateKey] = useState<string | null>(null);
  const [campaignDropdownOpen, setCampaignDropdownOpen] = useState(false);
  const campaignDropdownRef = useRef<HTMLDivElement>(null);
  const [targets, setTargets] = useState<Reservation[]>([]);

  // 드롭다운 외부 클릭 시 닫기
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (campaignDropdownRef.current && !campaignDropdownRef.current.contains(e.target as Node)) {
        setCampaignDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const clearTargets = useCallback(() => setTargets([]), []);

  const loadTargets = useCallback(() => {
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
  }, [selectedTemplateKey, reservations]);

  const requestSendCampaign = useCallback(() => {
    if (!selectedTemplateKey || targets.length === 0) {
      toast.warning('발송 대상이 없습니다');
      return;
    }
    onConfirmRequest();
  }, [selectedTemplateKey, targets.length, onConfirmRequest]);

  const sendMutation = useMutation({
    mutationFn: async (vars: { template_key: string; date: string }) => {
      const res = await reservationsAPI.smsSendByTag(vars);
      if (!res.data?.success) {
        throw new Error(res.data?.detail || res.data?.message || res.data?.error || '발송 실패');
      }
      return res.data;
    },
    onSuccess: (data) => {
      const tpl = templateLabels.find(t => t.template_key === selectedTemplateKey);
      toast.success(`${tpl?.name || selectedTemplateKey} 발송 완료: ${data.sent_count}건`);
      setTargets([]);
      qc.invalidateQueries({ queryKey: queryKeys.reservations.all() });
    },
    onError: (err: any) => {
      toast.error(err?.message || '발송 실패');
    },
  });

  const handleSendCampaign = useCallback(() => {
    if (!selectedTemplateKey || targets.length === 0) return;
    onConfirmClose();
    sendMutation.mutate({
      template_key: selectedTemplateKey,
      date: selectedDate.format('YYYY-MM-DD'),
    });
  }, [selectedTemplateKey, targets.length, selectedDate, onConfirmClose, sendMutation]);

  return {
    selectedTemplateKey,
    setSelectedTemplateKey,
    campaignDropdownOpen,
    setCampaignDropdownOpen,
    campaignDropdownRef,
    targets,
    setTargets,
    clearTargets,
    sending: sendMutation.isPending,
    loadTargets,
    requestSendCampaign,
    handleSendCampaign,
  };
}
