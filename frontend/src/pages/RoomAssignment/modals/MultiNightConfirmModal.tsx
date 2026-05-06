import { BedDouble } from 'lucide-react';
import { Modal, ModalBody } from '@/components/ui/modal';
import { Button } from '@/components/ui/button';

export interface MultiNightConfirmData {
  open: boolean;
  resId: number;
  resName: string;
  roomId: number;
  roomNumber: string;
  onConfirm: (applySubsequent: boolean) => void;
}

interface MultiNightConfirmModalProps {
  data: MultiNightConfirmData | null;
  onClose: () => void;
}

export function MultiNightConfirmModal({ data, onClose }: MultiNightConfirmModalProps) {
  return (
    <Modal show={!!data?.open} onClose={onClose} size="sm">
      <ModalBody>
        <div className="text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-[#E8F3FF] dark:bg-[#3182F6]/10">
            <BedDouble className="h-6 w-6 text-[#3182F6]" />
          </div>
          <h3 className="mb-2 text-lg font-semibold text-[#191F28] dark:text-white">연박 객실 이동</h3>
          <p className="mb-5 text-sm text-[#8B95A1] dark:text-[#8B95A1]">
            <span className="font-semibold text-[#191F28] dark:text-white">{data?.resName}</span> 님을{' '}
            <span className="font-semibold text-[#3182F6]">{data?.roomNumber}</span>(으)로 이동합니다.
            <br />이후 날짜도 같은 객실로 배정하시겠습니까?
          </p>
          <div className="flex justify-center gap-3">
            <Button color="blue" onClick={() => data?.onConfirm(true)}>
              오늘 이후 전체
            </Button>
            <Button color="light" onClick={() => data?.onConfirm(false)}>
              이 날짜만
            </Button>
            <Button color="light" onClick={onClose}>
              취소
            </Button>
          </div>
        </div>
      </ModalBody>
    </Modal>
  );
}
