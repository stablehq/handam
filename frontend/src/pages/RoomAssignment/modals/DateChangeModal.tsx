import { toast } from 'sonner';
import { Modal, ModalHeader, ModalBody, ModalFooter } from '@/components/ui/modal';
import { TextInput } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';

export interface DateChangeModalData {
  open: boolean;
  resId: number;
  customerName: string;
  checkIn: string;
  checkOut: string;
}

interface DateChangeModalProps {
  data: DateChangeModalData | null;
  onChange: (next: DateChangeModalData) => void;
  onClose: () => void;
  /**
   * 부모가 API 호출/토스트/refetch 책임. 모달은 입력 검증만 수행한 뒤 호출.
   * resolve 되면 모달은 닫힌다 (parent 가 onClose 도 같이 부르거나 별도 처리).
   */
  onSubmit: (resId: number, checkIn: string, checkOut: string) => Promise<void>;
}

export function DateChangeModal({ data, onChange, onClose, onSubmit }: DateChangeModalProps) {
  return (
    <Modal show={!!data?.open} onClose={onClose} size="md">
      <ModalHeader>예약 날짜 변경 — {data?.customerName}</ModalHeader>
      <ModalBody>
        <div className="flex items-end gap-3">
          <div className="flex-1">
            <Label className="mb-1 block text-label font-medium text-[#4E5968] dark:text-gray-300">체크인</Label>
            <TextInput
              type="date"
              value={data?.checkIn || ''}
              onChange={(e) => data && onChange({ ...data, checkIn: e.target.value })}
            />
          </div>
          <span className="pb-2 text-[#8B95A1]">~</span>
          <div className="flex-1">
            <Label className="mb-1 block text-label font-medium text-[#4E5968] dark:text-gray-300">체크아웃</Label>
            <TextInput
              type="date"
              value={data?.checkOut || ''}
              onChange={(e) => data && onChange({ ...data, checkOut: e.target.value })}
            />
          </div>
        </div>
      </ModalBody>
      <ModalFooter>
        <div className="flex gap-2 justify-end w-full">
          <Button color="light" onClick={onClose}>취소</Button>
          <Button
            color="blue"
            onClick={async () => {
              if (!data) return;
              const { resId, checkIn, checkOut } = data;
              if (!checkIn) { toast.error('체크인 날짜를 입력하세요'); return; }
              if (!checkOut) { toast.error('체크아웃 날짜를 입력하세요'); return; }
              // co == ci 는 백엔드에서 "당일 1박" 으로 NULL 과 동일 취급되므로 허용.
              // co < ci 만 차단.
              if (checkOut < checkIn) { toast.error('체크아웃은 체크인보다 이전일 수 없습니다'); return; }
              await onSubmit(resId, checkIn, checkOut);
            }}
          >
            변경
          </Button>
        </div>
      </ModalFooter>
    </Modal>
  );
}
