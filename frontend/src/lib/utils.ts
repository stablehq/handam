import { clsx, type ClassValue } from 'clsx'
import { extendTailwindMerge } from 'tailwind-merge'

const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      'font-size': [
        'text-display',
        'text-title',
        'text-heading',
        'text-subheading',
        'text-body',
        'text-label',
        'text-caption',
        'text-overline',
        'text-tiny',
      ],
    },
  },
})

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Backend returns UTC-naive ISO strings (no 'Z'). Normalize for correct browser parsing. */
export function normalizeUtcString(iso: string): string {
  if (!iso.includes('T')) return iso;  // date-only string, no TZ needed
  return iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z';
}
