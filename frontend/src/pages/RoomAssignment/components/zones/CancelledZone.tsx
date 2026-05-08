import { GuestZone, type GuestZoneProps } from './GuestZone';

type WrapperProps = Omit<
  GuestZoneProps,
  'title' | 'titleColorClass' | 'accept' | 'hideWhenEmpty' | 'rowZone' | 'zoneClassName' | 'count'
>;

/** 취소 zone 래퍼 — 드롭 안 받음, 빨강 테마, 카운트 표시 + 흐림(opacity-60), 비었으면 숨김. */
export function CancelledZone(props: WrapperProps) {
  return (
    <GuestZone
      title="취소"
      titleColorClass="text-[#F04452] dark:text-[#FF6B7A]"
      accept={false}
      hideWhenEmpty
      rowZone="cancelled"
      zoneClassName="opacity-60"
      count={props.guests.length}
      {...props}
    />
  );
}
