import React, { useState, useEffect, useRef } from 'react';
import { Plus } from 'lucide-react';
import dayjs from 'dayjs';
import { normalizeUtcString } from '../../../lib/utils';
import type { Reservation } from '../types';

interface SmsCellProps {
  reservation: Reservation;
  templateLabels: { template_key: string; name: string; short_label: string | null }[];
  selectedDate: string;
  onToggle: (resId: number, templateKey: string) => void;
  onAssign: (resId: number, templateKey: string) => void;
  onRemove: (resId: number, templateKey: string) => void;
}

export const SmsCell: React.FC<SmsCellProps> = ({
  reservation,
  templateLabels,
  selectedDate,
  onToggle,
  onAssign,
  onRemove,
}) => {
  const scrollRef = useRef<HTMLDivElement>(null);

  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [dropdownPos, setDropdownPos] = useState<{ top?: number; bottom?: number; right: number }>({ right: 0 });
  const dropdownRef = useRef<HTMLDivElement>(null);
  const dropdownMenuRef = useRef<HTMLDivElement>(null);
  const buttonRectRef = useRef<DOMRect | null>(null);

  // Deduplicate by template_key: prefer today's chip, fallback to most recent sent chip
  const assignments = (() => {
    const raw = reservation.sms_assignments || [];
    const byKey = new Map<string, typeof raw[0]>();
    for (const a of raw) {
      const existing = byKey.get(a.template_key);
      if (!existing) {
        byKey.set(a.template_key, a);
      } else {
        // Prefer unsent (today's) over sent (past), or newer date
        if (!a.sent_at && existing.sent_at) {
          byKey.set(a.template_key, a);
        } else if (a.date > (existing.date || '')) {
          byKey.set(a.template_key, a);
        }
      }
    }
    return [...byKey.values()].sort((a, b) => {
      const ai = templateLabels.findIndex(t => t.template_key === a.template_key);
      const bi = templateLabels.findIndex(t => t.template_key === b.template_key);
      return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
    });
  })();


  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    if (dropdownOpen) {
      document.addEventListener('mousedown', handler);
      return () => document.removeEventListener('mousedown', handler);
    }
  }, [dropdownOpen]);

  // 드롭다운 실제 높이 측정 후 뷰포트 밖이면 위로 재배치
  useEffect(() => {
    if (dropdownOpen && dropdownMenuRef.current && buttonRectRef.current) {
      const menuRect = dropdownMenuRef.current.getBoundingClientRect();
      const rect = buttonRectRef.current;
      if (menuRect.bottom > window.innerHeight) {
        setDropdownPos({ bottom: window.innerHeight - rect.top + 4, right: window.innerWidth - rect.right });
      }
    }
  }, [dropdownOpen]);


  const getLabel = (key: string) => {
    const tpl = templateLabels.find(t => t.template_key === key);
    return tpl?.short_label || tpl?.name || key;
  };

  const getFullName = (key: string) => {
    const tpl = templateLabels.find(t => t.template_key === key);
    return tpl?.name || key;
  };

  const isAssigned = (key: string) => assignments.some(a => a.template_key === key);

  const isSentTemplate = (key: string) => !!assignments.find(a => a.template_key === key)?.sent_at;

  const handleDropdownToggle = (key: string) => {
    if (isSentTemplate(key)) return; // 발송완료된 항목은 해제 불가
    if (isAssigned(key)) {
      onRemove(reservation.id, key);
    } else {
      onAssign(reservation.id, key);
    }
  };

  return (
    <div className="relative flex items-center h-8">
      <div
        ref={scrollRef}
        className="flex-1 overflow-x-auto overflow-y-hidden flex items-center min-w-0 scrollbar-none"
      >
        <div className="flex items-center gap-1 flex-nowrap">
          {assignments.map((a) => {
            const isSent = !!a.sent_at;
            const isFailed = a.send_status === 'failed';
            const isPastChip = isSent && a.date < selectedDate;
            // 실패 상태인데 sent_at 이 남아있으면 "과거 성공 후 재시도 실패" — 툴팁에 병기 (KST 로 표시)
            const priorSendNote = isFailed && a.sent_at
              ? `\n(이전 발송 기록 있음: ${dayjs(normalizeUtcString(a.sent_at)).format('YYYY-MM-DD HH:mm')})`
              : '';
            // surcharge 칩은 총액 텍스트 우선 표시 (예: "추가요금 8만원")
            const baseTitle = a.surcharge_total_text || getFullName(a.template_key);
            const chipTitle = isFailed
              ? `${baseTitle} — 발송 실패: ${a.send_error || '알 수 없는 오류'}${priorSendNote}`
              : isPastChip
                ? `${baseTitle} (${a.date} 발송완료)`
                : baseTitle;
            return (
              <span
                key={a.template_key}
                title={chipTitle}
                className={`inline-flex items-center px-1.5 py-1 rounded text-[11px] leading-tight font-medium whitespace-nowrap cursor-pointer transition-all
                  ${isFailed
                    ? 'bg-[#FFEBEE] text-[#F04452] border border-[#F04452]/30 dark:bg-[#F04452]/20 dark:text-[#F04452] dark:border-[#F04452]/30'
                    : isSent
                      ? 'bg-[#E8F3FF] text-[#3182F6] border border-[#3182F6]/30 dark:bg-[#3182F6]/20 dark:text-[#3182F6] dark:border-[#3182F6]/30'
                      : 'bg-[#F2F4F6] text-[#8B95A1] border border-[#E5E8EB] dark:bg-[#2C2C34] dark:text-[#8B95A1] dark:border-[#2C2C34]'
                  }`}
                onClick={(e) => { e.stopPropagation(); onToggle(reservation.id, a.template_key); }}
              >
                {getLabel(a.template_key)}
              </span>
            );
          })}
          {assignments.length === 0 && (
            <span className="text-[#B0B8C1] dark:text-[#8B95A1] text-caption">-</span>
          )}
        </div>
      </div>
      {/* + button with checklist dropdown */}
      <div className="relative flex-shrink-0 ml-1" ref={dropdownRef}>
        <button
          onClick={(e) => {
            e.stopPropagation();
            if (!dropdownOpen) {
              const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
              buttonRectRef.current = rect;
              // 일단 아래로 열고, useEffect에서 실제 높이 측정 후 재배치
              setDropdownPos({ top: rect.bottom + 4, right: window.innerWidth - rect.right });
            }
            setDropdownOpen(!dropdownOpen);
          }}
          className="inline-flex items-center justify-center w-[18px] h-[18px] rounded bg-[#F2F4F6] dark:bg-[#2C2C34] text-[#4E5968] dark:text-gray-300 hover:bg-[#E5E8EB] hover:text-[#191F28] dark:hover:bg-[#35353E] dark:hover:text-white transition-colors cursor-pointer"
          title="문자 템플릿 관리"
        >
          <Plus size={10} />
        </button>
        {dropdownOpen && templateLabels.length > 0 && (
          <div
            ref={dropdownMenuRef}
            className="fixed z-[60] w-max rounded-lg border border-[#E5E8EB] dark:border-[#2C2C34] bg-white dark:bg-[#1E1E24] shadow-lg py-1"
            style={{ top: dropdownPos.top, bottom: dropdownPos.bottom, right: dropdownPos.right }}
          >
            {templateLabels.map(t => {
              const assigned = isAssigned(t.template_key);
              const sent = assignments.find(a => a.template_key === t.template_key)?.sent_at;
              return (
                <button
                  key={t.template_key}
                  className={`w-full flex items-center gap-2 px-3 py-1.5 text-caption transition-colors ${
                    sent ? 'opacity-60 cursor-not-allowed' : 'hover:bg-[#F2F4F6] dark:hover:bg-[#2C2C34] cursor-pointer'
                  }`}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDropdownToggle(t.template_key);
                  }}
                >
                  <span className={`flex items-center justify-center w-3.5 h-3.5 rounded border transition-colors ${
                    assigned
                      ? 'bg-[#3182F6] border-[#3182F6] text-white'
                      : 'border-[#E5E8EB] dark:border-[#4E5968]'
                  }`}>
                    {assigned && <span className="text-[9px] font-bold">✓</span>}
                  </span>
                  <span className={`flex items-center gap-1.5 ${assigned ? 'text-[#191F28] dark:text-white' : 'text-[#8B95A1] dark:text-[#4E5968]'}`}>
                    <span className={`font-medium ${sent ? 'line-through text-[#8B95A1] dark:text-[#4E5968]' : ''}`}>
                      {t.short_label ? (
                        <>{t.short_label} <span className="text-[#8B95A1] dark:text-[#4E5968] font-normal">({t.name})</span></>
                      ) : t.name}
                    </span>
                    {sent && <span className="text-[9px] text-[#3182F6] font-medium">발송완료</span>}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
