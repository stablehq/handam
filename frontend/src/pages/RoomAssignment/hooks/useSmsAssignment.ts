import { useCallback } from 'react';
import type { Dayjs } from 'dayjs';
import { toast } from 'sonner';
import { smsAssignmentsAPI } from '../../../services/api';
import type { Reservation, SmsAssignment } from '../types';

interface TemplateLabel {
  template_key: string;
  name: string;
  short_label: string | null;
}

interface UseSmsAssignmentProps {
  reservations: Reservation[];
  selectedDate: Dayjs;
  templateLabels: TemplateLabel[];
  setReservations: React.Dispatch<React.SetStateAction<Reservation[]>>;
  /** handleSmsToggle 이 발송 확인 모달 열기 신호 보내는 콜백 */
  onToggleConfirmRequest: (params: {
    resId: number;
    templateKey: string;
    customerName: string;
    templateName: string;
  }) => void;
}

/**
 * SMS 칩 할당 / 토글 / 제거 — 낙관적 업데이트 + 실패 롤백.
 *
 * Phase D-4: 4개 핸들러 + updateReservationSms 헬퍼 통합.
 * sendConfirm 모달 자체는 본체 잔존 (campaign 흐름과 공유).
 */
export function useSmsAssignment({
  reservations,
  selectedDate,
  templateLabels,
  setReservations,
  onToggleConfirmRequest,
}: UseSmsAssignmentProps) {
  // 특정 게스트의 sms_assignments 만 immutable 갱신
  const updateReservationSms = useCallback((
    resId: number,
    updater: (assignments: SmsAssignment[]) => SmsAssignment[],
  ) => {
    setReservations(prev => prev.map(r =>
      r.id === resId ? { ...r, sms_assignments: updater(r.sms_assignments || []) } : r
    ));
  }, [setReservations]);

  // 칩 클릭 → 모달 열기 신호 (즉시 토글 X)
  const handleSmsToggle = useCallback(async (resId: number, templateKey: string) => {
    const res = reservations.find(r => r.id === resId);
    const tpl = templateLabels.find(t => t.template_key === templateKey);
    onToggleConfirmRequest({
      resId,
      templateKey,
      customerName: res?.customer_name || '',
      templateName: tpl?.name || templateKey,
    });
  }, [reservations, templateLabels, onToggleConfirmRequest]);

  // 모달 확인 → 실제 발송 상태 토글 (낙관적 + API + 롤백)
  const doSmsToggle = useCallback(async (resId: number, templateKey: string, skipSend?: boolean) => {
    const res = reservations.find(r => r.id === resId);
    const dateStr = selectedDate.format('YYYY-MM-DD');
    const assignment = res?.sms_assignments?.find(a => a.template_key === templateKey && a.date === dateStr)
      || res?.sms_assignments?.find(a => a.template_key === templateKey);
    const wasSent = !!assignment?.sent_at;
    const originalSentAt = assignment?.sent_at ?? null;
    const originalSendStatus = assignment?.send_status ?? null;
    const originalSendError = assignment?.send_error ?? null;
    // 낙관적 업데이트 — 백엔드 toggle_sms_sent 가 세 필드 동기화하므로 프런트도 동일하게 반영.
    updateReservationSms(resId, assignments =>
      assignments.map(a => a.template_key === templateKey
        ? {
            ...a,
            sent_at: wasSent ? null : new Date().toISOString(),
            send_status: wasSent ? null : 'sent',
            send_error: null,
          }
        : a
      )
    );
    try {
      await smsAssignmentsAPI.toggle(resId, templateKey, skipSend, assignment?.date || selectedDate.format('YYYY-MM-DD'));
    } catch {
      updateReservationSms(resId, assignments =>
        assignments.map(a => a.template_key === templateKey
          ? { ...a, sent_at: originalSentAt, send_status: originalSendStatus, send_error: originalSendError }
          : a
        )
      );
      toast.error('발송 상태 변경 실패');
    }
  }, [reservations, selectedDate, updateReservationSms]);

  // + 드롭다운에서 체크 → 새 항목 낙관적 추가 + API + 실패 시 제거
  const handleSmsAssign = useCallback(async (resId: number, templateKey: string) => {
    updateReservationSms(resId, assignments => [
      ...assignments,
      { id: 0, reservation_id: resId, template_key: templateKey, assigned_at: new Date().toISOString(), sent_at: null, assigned_by: 'manual', date: selectedDate.format('YYYY-MM-DD') },
    ]);
    try {
      await smsAssignmentsAPI.assign(resId, { template_key: templateKey, date: selectedDate.format('YYYY-MM-DD') });
    } catch {
      updateReservationSms(resId, assignments =>
        assignments.filter(a => a.template_key !== templateKey)
      );
      toast.error('할당 실패');
    }
  }, [selectedDate, updateReservationSms]);

  // + 드롭다운에서 체크 해제 → 항목 즉시 제거 + API + 실패 시 복원
  const handleSmsRemove = useCallback(async (resId: number, templateKey: string) => {
    const res = reservations.find(r => r.id === resId);
    const dateStr = selectedDate.format('YYYY-MM-DD');
    const removed = res?.sms_assignments?.find(a => a.template_key === templateKey && a.date === dateStr)
      || res?.sms_assignments?.find(a => a.template_key === templateKey);
    updateReservationSms(resId, assignments =>
      assignments.filter(a => a.template_key !== templateKey)
    );
    try {
      await smsAssignmentsAPI.remove(resId, templateKey, selectedDate.format('YYYY-MM-DD'));
    } catch {
      if (removed) {
        updateReservationSms(resId, assignments => [...assignments, removed]);
      }
      toast.error('제거 실패');
    }
  }, [reservations, selectedDate, updateReservationSms]);

  return {
    handleSmsToggle,
    doSmsToggle,
    handleSmsAssign,
    handleSmsRemove,
  };
}
