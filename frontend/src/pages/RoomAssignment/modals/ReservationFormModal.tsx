import { Modal, ModalHeader, ModalBody, ModalFooter } from '@/components/ui/modal';
import { TextInput } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';

interface ReservationFormModalProps {
  show: boolean;
  onClose: () => void;
  editingId: number | null;
  formValues: any;
  setFormValues: (next: any) => void;
  saving: boolean;
  onSubmit: () => void;
}

export function ReservationFormModal({
  show,
  onClose,
  editingId,
  formValues,
  setFormValues,
  saving,
  onSubmit,
}: ReservationFormModalProps) {
  return (
    <Modal show={show} onClose={onClose} size="md">
      <ModalHeader>{editingId ? '게스트 수정' : '예약자 추가'}</ModalHeader>
      <ModalBody>
        <div className="flex flex-col gap-4">
          {!editingId && (
            <div className="flex gap-2">
              {[
                { value: 'party_only', label: '파티만' },
                { value: 'manual', label: '객실 포함' },
              ].map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => {
                    setFormValues({ ...formValues, guest_type: opt.value });
                  }}
                  className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors cursor-pointer
                    ${(formValues.guest_type || 'party_only') === opt.value
                      ? 'bg-[#3182F6] text-white'
                      : 'bg-[#F2F4F6] text-[#4E5968] hover:bg-[#E5E8EB] dark:bg-[#2C2C34] dark:text-white dark:hover:bg-[#2C2C34]'
                    }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="customer-name">이름 <span className="text-[#F04452] dark:text-[#F04452]">*</span></Label>
              <TextInput
                id="customer-name"
                value={formValues.customer_name || ''}
                onChange={(e) => setFormValues({ ...formValues, customer_name: e.target.value })}
                placeholder="이름"
                sizing="sm"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="phone">전화번호 <span className="text-[#F04452] dark:text-[#F04452]">*</span></Label>
              <TextInput
                id="phone"
                value={formValues.phone || ''}
                onChange={(e) => setFormValues({ ...formValues, phone: e.target.value })}
                placeholder="010-1234-5678"
                sizing="sm"
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="date">날짜 <span className="text-[#F04452] dark:text-[#F04452]">*</span></Label>
            <div className="flex gap-3 items-center">
              <TextInput
                id="date"
                type="date"
                value={formValues.date || ''}
                onChange={(e) => setFormValues({ ...formValues, date: e.target.value })}
                sizing="sm"
                className="flex-1"
              />
              <label className="flex items-center gap-1.5 cursor-pointer select-none whitespace-nowrap">
                <input
                  type="checkbox"
                  checked={!!formValues.multi_night}
                  onChange={(e) => setFormValues({ ...formValues, multi_night: e.target.checked, nights: e.target.checked ? (formValues.nights || 2) : null })}
                  className="rounded border-[#E5E8EB] text-[#3182F6] focus:ring-[#3182F6]"
                />
                <span className="text-sm text-[#4E5968] dark:text-gray-300">연박</span>
              </label>
              <div className="flex items-center gap-0">
                <input
                  type="number"
                  min={2}
                  max={30}
                  value={formValues.multi_night ? (formValues.nights || 2) : ''}
                  onChange={(e) => setFormValues({ ...formValues, nights: e.target.value ? Number(e.target.value) : 2 })}
                  disabled={!formValues.multi_night}
                  placeholder="2"
                  className={`w-16 rounded-l-lg border border-r-0 border-[#E5E8EB] dark:border-[#2C2C34] text-sm text-center px-2 py-1.5 focus:border-[#3182F6] focus:ring-[#3182F6] outline-none ${
                    formValues.multi_night
                      ? 'bg-white dark:bg-[#1E1E24] text-[#191F28] dark:text-white'
                      : 'bg-[#F2F4F6] dark:bg-[#2C2C34] text-[#B0B8C1] dark:text-gray-600 cursor-not-allowed'
                  }`}
                />
                <span className={`flex-shrink-0 px-2 py-1.5 rounded-r-lg border border-[#E5E8EB] dark:border-[#2C2C34] text-sm font-medium ${
                  formValues.multi_night
                    ? 'bg-[#F2F4F6] dark:bg-[#2C2C34] text-[#4E5968] dark:text-white'
                    : 'bg-[#F2F4F6] dark:bg-[#2C2C34] text-[#B0B8C1] dark:text-gray-600'
                }`}>박</span>
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <Label>성별 / 인원</Label>
            <div className="flex gap-3">
              <div className="flex items-center gap-0 flex-1">
                <span className="flex-shrink-0 px-3 py-1.5 rounded-l-lg bg-[#F2F4F6] dark:bg-[#2C2C34] border border-r-0 border-[#E5E8EB] dark:border-[#2C2C34] text-sm font-medium text-[#4E5968] dark:text-white">남</span>
                <input
                  type="number"
                  min={0}
                  value={formValues.male_count ?? ''}
                  onChange={(e) => setFormValues({ ...formValues, male_count: e.target.value ? Number(e.target.value) : null })}
                  placeholder="0"
                  className="w-full rounded-r-lg rounded-l-none border border-[#E5E8EB] dark:border-[#2C2C34] bg-white dark:bg-[#1E1E24] text-sm text-[#191F28] dark:text-white px-3 py-1.5 focus:border-[#3182F6] focus:ring-[#3182F6] outline-none"
                />
              </div>
              <div className="flex items-center gap-0 flex-1">
                <span className="flex-shrink-0 px-3 py-1.5 rounded-l-lg bg-[#F2F4F6] dark:bg-[#2C2C34] border border-r-0 border-[#E5E8EB] dark:border-[#2C2C34] text-sm font-medium text-[#4E5968] dark:text-white">여</span>
                <input
                  type="number"
                  min={0}
                  value={formValues.female_count ?? ''}
                  onChange={(e) => setFormValues({ ...formValues, female_count: e.target.value ? Number(e.target.value) : null })}
                  placeholder="0"
                  className="w-full rounded-r-lg rounded-l-none border border-[#E5E8EB] dark:border-[#2C2C34] bg-white dark:bg-[#1E1E24] text-sm text-[#191F28] dark:text-white px-3 py-1.5 focus:border-[#3182F6] focus:ring-[#3182F6] outline-none"
                />
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="notes">메모</Label>
            <TextInput
              id="notes"
              value={formValues.notes || ''}
              onChange={(e) => setFormValues({ ...formValues, notes: e.target.value })}
              placeholder="메모"
              sizing="sm"
            />
          </div>
        </div>
      </ModalBody>
      <ModalFooter>
        <Button color="light" onClick={onClose}>취소</Button>
        <Button color="blue" onClick={onSubmit} disabled={saving}>
          {saving ? '저장 중...' : '저장'}
        </Button>
      </ModalFooter>
    </Modal>
  );
}
