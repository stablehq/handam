import React from 'react';
import { ChevronDown, RefreshCw, Send, Layers, UserPlus, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Spinner } from '@/components/ui/spinner';
import type { Reservation } from '../types';

interface TemplateLabel {
  template_key: string;
  name: string;
  short_label: string | null;
}

export interface CampaignToolbarProps {
  // 데이터
  templateLabels: TemplateLabel[];

  // useCampaignSend 결과 forward
  selectedTemplateKey: string | null;
  setSelectedTemplateKey: (key: string | null) => void;
  campaignDropdownOpen: boolean;
  setCampaignDropdownOpen: (open: boolean) => void;
  campaignDropdownRef: React.RefObject<HTMLDivElement>;
  targets: Reservation[];
  clearTargets: () => void;
  sending: boolean;
  loadTargets: () => void;
  requestSendCampaign: () => void;

  // 외부 액션
  onOpenTableSettings: () => void;
  onAddPartyGuest: () => void;
}

/**
 * 객실 배정 페이지 상단 액션 툴바.
 *
 * - 템플릿 선택 드롭다운 (click-outside 는 useCampaignSend hook 안에서 처리, ref 만 forward)
 * - 대상조회 / 발송 버튼
 * - 테이블 설정 / 예약자 추가 버튼
 * - 발송 대상 표시 패널 (targets 있을 때)
 */
export function CampaignToolbar({
  templateLabels,
  selectedTemplateKey,
  setSelectedTemplateKey,
  campaignDropdownOpen,
  setCampaignDropdownOpen,
  campaignDropdownRef,
  targets,
  clearTargets,
  sending,
  loadTargets,
  requestSendCampaign,
  onOpenTableSettings,
  onAddPartyGuest,
}: CampaignToolbarProps) {
  return (
    <div className="section-card !overflow-visible">
      <div className="section-body py-3">
        <div className="flex flex-wrap gap-2 items-center">
          {/* Campaign dropdown selector */}
          <div className="relative" ref={campaignDropdownRef}>
            <button
              type="button"
              onClick={() => setCampaignDropdownOpen(!campaignDropdownOpen)}
              className="flex items-center justify-between gap-2 px-3 py-1.5 text-sm font-medium rounded-lg border border-[#E5E8EB] dark:border-[#2C2C34] bg-white dark:bg-[#1E1E24] text-[#191F28] dark:text-white hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34] transition-colors cursor-pointer min-w-[160px]"
            >
              {selectedTemplateKey
                ? templateLabels.find(t => t.template_key === selectedTemplateKey)?.name || '템플릿 선택'
                : '템플릿 선택'}
              <ChevronDown size={14} className={`text-[#8B95A1] transition-transform ${campaignDropdownOpen ? 'rotate-180' : ''}`} />
            </button>
            {campaignDropdownOpen && (
              <div className="absolute top-full left-0 mt-1 z-30 min-w-[160px] rounded-xl border border-[#E5E8EB] dark:border-[#2C2C34] bg-white dark:bg-[#1E1E24] shadow-lg shadow-black/8 py-1 animate-in fade-in slide-in-from-top-1 duration-150">
                {templateLabels.map(t => (
                  <button
                    key={t.template_key}
                    type="button"
                    onClick={() => { setSelectedTemplateKey(t.template_key); setCampaignDropdownOpen(false); clearTargets(); }}
                    className={`w-full text-left px-3 py-2 text-sm transition-colors cursor-pointer
                      ${selectedTemplateKey === t.template_key ? 'bg-[#F2F4F6] dark:bg-[#2C2C34] text-[#3182F6] font-medium' : 'text-[#4E5968] dark:text-white hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34]'}`}
                  >
                    {t.name}
                  </button>
                ))}
              </div>
            )}
          </div>

          <Button
            color="light"
            size="sm"
            onClick={loadTargets}
            disabled={!selectedTemplateKey}
          >
            <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
            대상조회
          </Button>
          <Button
            color="blue"
            size="sm"
            onClick={requestSendCampaign}
            disabled={sending || targets.length === 0 || !selectedTemplateKey}
          >
            {sending ? (
              <Spinner size="sm" className="mr-1.5" />
            ) : (
              <Send className="h-3.5 w-3.5 mr-1.5" />
            )}
            발송 ({targets.length}건)
          </Button>

          <div className="ml-auto flex items-center gap-2">
            <Button
              color="light"
              size="sm"
              onClick={onOpenTableSettings}
            >
              <Layers className="h-3.5 w-3.5 mr-1.5" />
              테이블 설정
            </Button>

            <Button
              color="light"
              size="sm"
              onClick={onAddPartyGuest}
            >
              <UserPlus className="h-3.5 w-3.5 mr-1.5" />
              예약자 추가
            </Button>
          </div>
        </div>

        {targets.length > 0 && (
          <div className="mt-3 rounded-lg border border-[#E5E8EB] dark:border-[#2C2C34] bg-[#F8F9FA] dark:bg-[#17171C] p-3">
            <div className="flex justify-between items-center mb-2">
              <Badge color="info" size="sm">발송 대상 {targets.length}건</Badge>
              <Button
                color="light"
                size="xs"
                onClick={clearTargets}
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {targets.map((t) => (
                <Badge key={t.id} color="gray" size="sm">
                  {t.customer_name} {t.phone} {t.room_number || ''}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
