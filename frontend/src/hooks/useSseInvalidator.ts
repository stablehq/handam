import { useEffect, useRef } from 'react';
import type { Dayjs } from 'dayjs';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { queryKeys } from '@/lib/queryKeys';

/**
 * SSE 어댑터 훅 — schedule_complete / room_assign_failed 이벤트 처리.
 *
 * - 연결은 tenantId / token 변경 시에만 재수립 (날짜 변경 시 재연결 없음).
 * - schedule_complete: 현재 날짜 + 익일 쿼리 무효화.
 * - room_assign_failed: 활동 로그 링크를 포함한 toast.
 */
export function useSseInvalidator(selectedDate: Dayjs): void {
  const qc = useQueryClient();
  // 최신 selectedDate 를 ref 로 유지 — handler 클로저가 stale 날짜를 참조하지 않도록.
  const dateRef = useRef<Dayjs>(selectedDate);
  useEffect(() => { dateRef.current = selectedDate; }, [selectedDate]);

  useEffect(() => {
    const token = localStorage.getItem('sms-token') || '';
    const tenantId = localStorage.getItem('sms-tenant-id') || '';

    const es = new EventSource(
      `/api/events/stream?token=${encodeURIComponent(token)}&tenant_id=${tenantId}`,
    );

    es.onmessage = (e) => {
      try {
        const { event, data } = JSON.parse(e.data);

        if (event === 'schedule_complete') {
          const currentDateStr = dateRef.current.format('YYYY-MM-DD');
          const nextDateStr = dateRef.current.add(1, 'day').format('YYYY-MM-DD');
          qc.invalidateQueries({ queryKey: queryKeys.reservations.list(currentDateStr) });
          qc.invalidateQueries({ queryKey: queryKeys.reservations.list(nextDateStr) });
        } else if (event === 'room_assign_failed') {
          const count = data?.count ?? 0;
          toast.warning(`객실 자동 배정 실패 ${count}건 — 활동 로그에서 확인하세요`, {
            duration: 10000,
            action: {
              label: '로그 보기',
              onClick: () => { window.location.href = '/activity-logs'; },
            },
          });
        }
      } catch {
        // malformed payload, ignore
      }
    };

    return () => es.close();
  }, [qc]); // token/tenantId 는 렌더마다 읽으므로 qc 만 dep — 마운트 1회 연결
}
