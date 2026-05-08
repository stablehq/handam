import { useCallback } from 'react';
import type { Dayjs } from 'dayjs';
import { toast } from 'sonner';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { smsAssignmentsAPI } from '../../../services/api';
import { queryKeys } from '@/lib/queryKeys';
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
  /** handleSmsToggle 이 발송 확인 모달 열기 신호 보내는 콜백 */
  onToggleConfirmRequest: (params: {
    resId: number;
    templateKey: string;
    customerName: string;
    templateName: string;
  }) => void;
}

/** 두 캐시(당일 + 익일)에서 특정 예약의 sms_assignments 를 immutable 갱신 */
function updateSmsInCaches(
  qc: ReturnType<typeof useQueryClient>,
  dateStr: string,
  nextDateStr: string,
  resId: number,
  updater: (assignments: SmsAssignment[]) => SmsAssignment[],
) {
  for (const key of [
    queryKeys.reservations.list(dateStr),
    queryKeys.reservations.list(nextDateStr),
  ]) {
    qc.setQueryData<Reservation[]>(key, (prev) =>
      prev?.map((r) =>
        r.id === resId
          ? { ...r, sms_assignments: updater(r.sms_assignments || []) }
          : r,
      ),
    );
  }
}

/**
 * SMS 칩 할당 / 토글 / 제거 — useMutation 낙관적 업데이트 + 실패 롤백.
 *
 * Phase 3a: useMutation + onMutate/onError/onSettled 패턴으로 전환.
 * 외부 인터페이스(handleSmsToggle, doSmsToggle, handleSmsAssign, handleSmsRemove) 유지.
 */
export function useSmsAssignment({
  reservations,
  selectedDate,
  templateLabels,
  onToggleConfirmRequest,
}: UseSmsAssignmentProps) {
  const qc = useQueryClient();

  // ── Mutation: doSmsToggle ──────────────────────────────────────────────────
  const toggleMutation = useMutation({
    mutationFn: (vars: {
      resId: number;
      templateKey: string;
      skipSend?: boolean;
      assignmentDate: string;
    }) =>
      smsAssignmentsAPI.toggle(
        vars.resId,
        vars.templateKey,
        vars.skipSend,
        vars.assignmentDate,
      ),

    onMutate: async (vars) => {
      const dateStr = selectedDate.format('YYYY-MM-DD');
      const nextDateStr = selectedDate.add(1, 'day').format('YYYY-MM-DD');

      await Promise.all([
        qc.cancelQueries({ queryKey: queryKeys.reservations.list(dateStr) }),
        qc.cancelQueries({ queryKey: queryKeys.reservations.list(nextDateStr) }),
      ]);

      const prevToday = qc.getQueryData<Reservation[]>(
        queryKeys.reservations.list(dateStr),
      );
      const prevNext = qc.getQueryData<Reservation[]>(
        queryKeys.reservations.list(nextDateStr),
      );

      // Snapshot the current assignment to know if it was sent
      const res = (prevToday ?? []).find((r) => r.id === vars.resId)
        ?? (prevNext ?? []).find((r) => r.id === vars.resId);
      const assignment =
        res?.sms_assignments?.find(
          (a) => a.template_key === vars.templateKey && a.date === vars.assignmentDate,
        ) ?? res?.sms_assignments?.find((a) => a.template_key === vars.templateKey);
      const wasSent = !!assignment?.sent_at;

      updateSmsInCaches(qc, dateStr, nextDateStr, vars.resId, (assignments) =>
        assignments.map((a) =>
          a.template_key === vars.templateKey
            ? {
                ...a,
                sent_at: wasSent ? null : new Date().toISOString(),
                send_status: wasSent ? null : 'sent',
                send_error: null,
              }
            : a,
        ),
      );

      return { prevToday, prevNext, dateStr, nextDateStr };
    },

    onError: (_err, _vars, ctx) => {
      if (ctx?.prevToday)
        qc.setQueryData(queryKeys.reservations.list(ctx.dateStr), ctx.prevToday);
      if (ctx?.prevNext)
        qc.setQueryData(queryKeys.reservations.list(ctx.nextDateStr), ctx.prevNext);
      toast.error('발송 상태 변경 실패');
    },

    onSettled: (_data, _err, _vars, ctx) => {
      if (!ctx) return;
      qc.invalidateQueries({ queryKey: queryKeys.reservations.list(ctx.dateStr) });
      qc.invalidateQueries({ queryKey: queryKeys.reservations.list(ctx.nextDateStr) });
    },
  });

  // ── Mutation: handleSmsAssign ─────────────────────────────────────────────
  const assignMutation = useMutation({
    mutationFn: (vars: { resId: number; templateKey: string; dateStr: string }) =>
      smsAssignmentsAPI.assign(vars.resId, {
        template_key: vars.templateKey,
        date: vars.dateStr,
      }),

    onMutate: async (vars) => {
      const nextDateStr = selectedDate.add(1, 'day').format('YYYY-MM-DD');

      await Promise.all([
        qc.cancelQueries({ queryKey: queryKeys.reservations.list(vars.dateStr) }),
        qc.cancelQueries({ queryKey: queryKeys.reservations.list(nextDateStr) }),
      ]);

      const prevToday = qc.getQueryData<Reservation[]>(
        queryKeys.reservations.list(vars.dateStr),
      );
      const prevNext = qc.getQueryData<Reservation[]>(
        queryKeys.reservations.list(nextDateStr),
      );

      updateSmsInCaches(qc, vars.dateStr, nextDateStr, vars.resId, (assignments) => [
        ...assignments,
        {
          id: 0,
          reservation_id: vars.resId,
          template_key: vars.templateKey,
          assigned_at: new Date().toISOString(),
          sent_at: null,
          assigned_by: 'manual',
          date: vars.dateStr,
        } as SmsAssignment,
      ]);

      return { prevToday, prevNext, dateStr: vars.dateStr, nextDateStr };
    },

    onError: (_err, _vars, ctx) => {
      if (ctx?.prevToday)
        qc.setQueryData(queryKeys.reservations.list(ctx.dateStr), ctx.prevToday);
      if (ctx?.prevNext)
        qc.setQueryData(queryKeys.reservations.list(ctx.nextDateStr), ctx.prevNext);
      toast.error('할당 실패');
    },

    onSettled: (_data, _err, _vars, ctx) => {
      if (!ctx) return;
      qc.invalidateQueries({ queryKey: queryKeys.reservations.list(ctx.dateStr) });
      qc.invalidateQueries({ queryKey: queryKeys.reservations.list(ctx.nextDateStr) });
    },
  });

  // ── Mutation: handleSmsRemove ─────────────────────────────────────────────
  const removeMutation = useMutation({
    mutationFn: (vars: { resId: number; templateKey: string; dateStr: string }) =>
      smsAssignmentsAPI.remove(vars.resId, vars.templateKey, vars.dateStr),

    onMutate: async (vars) => {
      const nextDateStr = selectedDate.add(1, 'day').format('YYYY-MM-DD');

      await Promise.all([
        qc.cancelQueries({ queryKey: queryKeys.reservations.list(vars.dateStr) }),
        qc.cancelQueries({ queryKey: queryKeys.reservations.list(nextDateStr) }),
      ]);

      const prevToday = qc.getQueryData<Reservation[]>(
        queryKeys.reservations.list(vars.dateStr),
      );
      const prevNext = qc.getQueryData<Reservation[]>(
        queryKeys.reservations.list(nextDateStr),
      );

      updateSmsInCaches(qc, vars.dateStr, nextDateStr, vars.resId, (assignments) =>
        assignments.filter((a) => a.template_key !== vars.templateKey),
      );

      return { prevToday, prevNext, dateStr: vars.dateStr, nextDateStr };
    },

    onError: (_err, _vars, ctx) => {
      if (ctx?.prevToday)
        qc.setQueryData(queryKeys.reservations.list(ctx.dateStr), ctx.prevToday);
      if (ctx?.prevNext)
        qc.setQueryData(queryKeys.reservations.list(ctx.nextDateStr), ctx.prevNext);
      toast.error('제거 실패');
    },

    onSettled: (_data, _err, _vars, ctx) => {
      if (!ctx) return;
      qc.invalidateQueries({ queryKey: queryKeys.reservations.list(ctx.dateStr) });
      qc.invalidateQueries({ queryKey: queryKeys.reservations.list(ctx.nextDateStr) });
    },
  });

  // ── Public handlers (same signature as before) ────────────────────────────

  // 칩 클릭 → 모달 열기 신호 (즉시 토글 X)
  const handleSmsToggle = useCallback(
    (resId: number, templateKey: string) => {
      const res = reservations.find((r) => r.id === resId);
      const tpl = templateLabels.find((t) => t.template_key === templateKey);
      onToggleConfirmRequest({
        resId,
        templateKey,
        customerName: res?.customer_name || '',
        templateName: tpl?.name || templateKey,
      });
    },
    [reservations, templateLabels, onToggleConfirmRequest],
  );

  // 모달 확인 → 실제 발송 상태 토글
  const doSmsToggle = useCallback(
    (resId: number, templateKey: string, skipSend?: boolean) => {
      const dateStr = selectedDate.format('YYYY-MM-DD');
      const res = qc
        .getQueryData<Reservation[]>(queryKeys.reservations.list(dateStr))
        ?.find((r) => r.id === resId)
        ?? qc
            .getQueryData<Reservation[]>(
              queryKeys.reservations.list(selectedDate.add(1, 'day').format('YYYY-MM-DD')),
            )
            ?.find((r) => r.id === resId);
      const assignment =
        res?.sms_assignments?.find(
          (a) => a.template_key === templateKey && a.date === dateStr,
        ) ?? res?.sms_assignments?.find((a) => a.template_key === templateKey);
      toggleMutation.mutate({
        resId,
        templateKey,
        skipSend,
        assignmentDate: assignment?.date || dateStr,
      });
    },
    [selectedDate, qc, toggleMutation],
  );

  // + 드롭다운에서 체크 → 새 항목 낙관적 추가
  const handleSmsAssign = useCallback(
    (resId: number, templateKey: string) => {
      assignMutation.mutate({
        resId,
        templateKey,
        dateStr: selectedDate.format('YYYY-MM-DD'),
      });
    },
    [selectedDate, assignMutation],
  );

  // + 드롭다운에서 체크 해제 → 항목 즉시 제거
  const handleSmsRemove = useCallback(
    (resId: number, templateKey: string) => {
      removeMutation.mutate({
        resId,
        templateKey,
        dateStr: selectedDate.format('YYYY-MM-DD'),
      });
    },
    [selectedDate, removeMutation],
  );

  return {
    handleSmsToggle,
    doSmsToggle,
    handleSmsAssign,
    handleSmsRemove,
  };
}
