import type { Dayjs } from 'dayjs';
import { Send } from 'lucide-react';
import { Modal, ModalHeader, ModalBody } from '@/components/ui/modal';
import { Button } from '@/components/ui/button';
import type { Reservation } from '../types';

export interface SendConfirmData {
  type: 'campaign' | 'toggle';
  resId?: number;
  templateKey?: string;
  customerName?: string;
  templateName?: string;
}

interface TemplateLabel {
  template_key: string;
  name: string;
  short_label: string | null;
}

interface SendConfirmModalProps {
  data: SendConfirmData | null;
  onClose: () => void;
  // 메시지/버튼 텍스트 계산용 컨텍스트
  reservations: Reservation[];
  templateLabels: TemplateLabel[];
  selectedTemplateKey: string | null;
  targetsCount: number;
  selectedDate: Dayjs;
  // 액션
  onSendCampaign: () => void;
  onSmsToggle: (resId: number, templateKey: string, skipSend?: boolean) => void;
}

export function SendConfirmModal({
  data,
  onClose,
  reservations,
  templateLabels,
  selectedTemplateKey,
  targetsCount,
  selectedDate,
  onSendCampaign,
  onSmsToggle,
}: SendConfirmModalProps) {
  // 토글 모드의 'isSent' 계산 — 동일 reservation 의 today/any assignment 우선순위로
  const computeIsSent = (): boolean => {
    if (data?.type !== 'toggle') return false;
    const r = reservations.find((res) => res.id === data.resId);
    const dateStr = selectedDate.format('YYYY-MM-DD');
    const ta = r?.sms_assignments?.find(
      (a) => a.template_key === data.templateKey && a.date === dateStr,
    ) || r?.sms_assignments?.find((a) => a.template_key === data.templateKey);
    return ta ? !!ta.sent_at : false;
  };

  const isSent = computeIsSent();

  // 토글 모드에서 '발송 없이 완료 처리' 가 노출 가능한 조건: 아직 미발송일 때만
  const canSkipSend = data?.type === 'toggle' && !isSent;

  return (
    <Modal show={!!data} onClose={onClose} size="md" popup>
      <ModalHeader />
      <ModalBody>
        <div className="text-center">
          <Send className="mx-auto mb-4 h-10 w-10 text-[#3182F6]" />
          <h3 className="mb-2 text-heading font-semibold text-gray-800 dark:text-white">
            SMS 발송 확인
          </h3>
          <p className="mb-6 text-body text-[#4E5968] dark:text-gray-300">
            {data?.type === 'campaign'
              ? `${templateLabels.find((t) => t.template_key === selectedTemplateKey)?.name || selectedTemplateKey} — ${targetsCount}건을 발송하시겠습니까?`
              : isSent
                ? `${data?.customerName}님의 ${data?.templateName} 발송을 취소하시겠습니까?`
                : `${data?.customerName}님에게 ${data?.templateName}을(를) 발송하시겠습니까?`}
          </p>
          <div className="flex flex-col items-center gap-4">
            <div className="flex justify-center gap-3">
              <Button
                color="blue"
                onClick={() => {
                  if (data?.type === 'campaign') {
                    onSendCampaign();
                  } else if (data?.type === 'toggle' && data.resId && data.templateKey) {
                    onClose();
                    onSmsToggle(data.resId, data.templateKey);
                  }
                }}
              >
                {isSent ? '발송 취소' : '발송'}
              </Button>
              <Button color="light" onClick={onClose}>
                취소
              </Button>
            </div>
            {canSkipSend && (
              <button
                className="text-caption text-[#8B95A1] underline hover:text-[#4E5968] dark:text-gray-500 dark:hover:text-gray-300"
                onClick={() => {
                  if (data?.resId && data.templateKey) {
                    onClose();
                    onSmsToggle(data.resId, data.templateKey, true);
                  }
                }}
              >
                발송 없이 완료 처리
              </button>
            )}
          </div>
        </div>
      </ModalBody>
    </Modal>
  );
}
