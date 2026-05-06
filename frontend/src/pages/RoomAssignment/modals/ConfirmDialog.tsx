import { Trash2 } from 'lucide-react';
import { Modal, ModalBody } from '@/components/ui/modal';
import { Button } from '@/components/ui/button';
import type { ConfirmState } from '../types';

interface ConfirmDialogProps {
  state: ConfirmState;
  onClose: () => void;
}

export function ConfirmDialog({ state, onClose }: ConfirmDialogProps) {
  return (
    <Modal show={state.open} onClose={onClose} size="sm">
      <ModalBody>
        <div className="text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-[#F04452]/10 dark:bg-[#F04452]/10">
            <Trash2 className="h-6 w-6 text-[#F04452]" />
          </div>
          <h3 className="mb-2 text-lg font-semibold text-[#191F28] dark:text-white">{state.title}</h3>
          <p className="mb-5 text-sm text-[#8B95A1] dark:text-[#8B95A1]">{state.content}</p>
          <div className="flex justify-center gap-3">
            <Button
              color="blue"
              onClick={() => {
                onClose();
                state.onOk();
              }}
            >
              확인
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
