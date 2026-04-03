// Shared highlight color definitions and utilities
// Used by GuestContextMenu, RoomAssignment, and TableSettingsModal

interface HighlightStyle {
  bg: string;
  hover: string;
  text?: string;
}

/** Tailwind class-based styles for preset colors */
export const PRESET_HIGHLIGHT_STYLES: Record<string, HighlightStyle> = {
  yellow: { bg: 'bg-[#FFF8E1] dark:bg-[#FFF8E1]/15', hover: 'hover:bg-[#FFF0C0] dark:hover:bg-[#FFF8E1]/25' },
  pink: { bg: 'bg-[#FFE8EE] dark:bg-[#FFE8EE]/15', hover: 'hover:bg-[#FFD6E0] dark:hover:bg-[#FFE8EE]/25' },
  green: { bg: 'bg-[#E8F5E9] dark:bg-[#E8F5E9]/15', hover: 'hover:bg-[#D0ECD2] dark:hover:bg-[#E8F5E9]/25' },
  blue: { bg: 'bg-[#E3F2FD] dark:bg-[#E3F2FD]/15', hover: 'hover:bg-[#CFEBFF] dark:hover:bg-[#E3F2FD]/25' },
  purple: { bg: 'bg-[#F3E5F5] dark:bg-[#F3E5F5]/15', hover: 'hover:bg-[#E8D0ED] dark:hover:bg-[#F3E5F5]/25' },
  'yellow-dark': { bg: 'bg-[#FFD54F] dark:bg-[#FFD54F]/25', hover: 'hover:bg-[#FFCA28] dark:hover:bg-[#FFD54F]/35', text: 'text-[#191F28] dark:text-white' },
  'pink-dark': { bg: 'bg-[#F48FB1] dark:bg-[#F48FB1]/25', hover: 'hover:bg-[#F06292] dark:hover:bg-[#F48FB1]/35', text: 'text-[#191F28] dark:text-white' },
  'green-dark': { bg: 'bg-[#81C784] dark:bg-[#81C784]/25', hover: 'hover:bg-[#66BB6A] dark:hover:bg-[#81C784]/35', text: 'text-[#191F28] dark:text-white' },
  'blue-dark': { bg: 'bg-[#64B5F6] dark:bg-[#64B5F6]/25', hover: 'hover:bg-[#42A5F5] dark:hover:bg-[#64B5F6]/35', text: 'text-[#191F28] dark:text-white' },
  'purple-dark': { bg: 'bg-[#CE93D8] dark:bg-[#CE93D8]/25', hover: 'hover:bg-[#BA68C8] dark:hover:bg-[#CE93D8]/35', text: 'text-[#191F28] dark:text-white' },
};

/** Check if hex color is light (luminance > 0.6) for text contrast */
export function isLightColor(hex: string): boolean {
  const c = hex.replace('#', '');
  const r = parseInt(c.slice(0, 2), 16);
  const g = parseInt(c.slice(2, 4), 16);
  const b = parseInt(c.slice(4, 6), 16);
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6;
}

/** Check if a color key is a custom hex color (starts with #) */
export function isCustomHexColor(key: string | null | undefined): key is string {
  return !!key && key.startsWith('#');
}

/** Get inline background style for custom hex colors (dark mode uses alpha) */
export function getCustomBgStyle(hex: string, isDark: boolean): { backgroundColor: string } {
  return { backgroundColor: isDark ? `${hex}26` : hex }; // 26 hex ≈ 15% opacity
}

/** Get text class for custom hex color based on luminance */
export function getCustomTextClass(hex: string): string {
  return isLightColor(hex) ? 'text-[#191F28] dark:text-white' : 'text-white dark:text-white';
}

/** Google Sheets default color palette (10 columns × 8 rows) */
export const GOOGLE_SHEETS_PALETTE: string[][] = [
  // Row 1: Grayscale
  ['#000000', '#434343', '#666666', '#999999', '#b7b7b7', '#cccccc', '#d9d9d9', '#efefef', '#f3f3f3', '#ffffff'],
  // Row 2: Vivid
  ['#980000', '#ff0000', '#ff9900', '#ffff00', '#00ff00', '#00ffff', '#4a86e8', '#0000ff', '#9900ff', '#ff00ff'],
  // Rows 3-8: Lightest → Darkest (per color family column)
  ['#e6b8af', '#f4cccc', '#fce5cd', '#fff2cc', '#d9ead3', '#d0e0e3', '#c9daf8', '#cfe2f3', '#d9d2e9', '#ead1dc'],
  ['#dd7e6b', '#ea9999', '#f9cb9c', '#ffe599', '#b6d7a8', '#a2c4c9', '#a4c2f4', '#9fc5e8', '#b4a7d6', '#d5a6bd'],
  ['#cc4125', '#e06666', '#f6b26b', '#ffd966', '#93c47d', '#76a5af', '#6d9eeb', '#6fa8dc', '#8e7cc3', '#c27ba0'],
  ['#a61c00', '#cc0000', '#e69138', '#f1c232', '#6aa84f', '#45818e', '#3c78d8', '#3d85c6', '#674ea7', '#a64d79'],
  ['#85200c', '#990000', '#b45f06', '#bf9000', '#38761d', '#134f5c', '#1155cc', '#0b5394', '#351c75', '#741b47'],
  ['#5b0f00', '#660000', '#783f04', '#7f6000', '#274e13', '#0c343d', '#1c4587', '#073763', '#20124d', '#4c1130'],
];

/** Default row stripe colors */
export const DEFAULT_ROW_COLORS = {
  even: '#FFFFFF',        // bg-white
  odd: '#F8F9FA',         // bg-[#F8F9FA]
  evenDark: '#1E1E24',    // dark:bg-[#1E1E24]
  oddDark: '#17171C',     // dark:bg-[#17171C]
  overbooking: '#FFF8E1', // bg-[#FFF8E1] (non-dorm, ≥2 guests)
  overbookingDark: '#FFF8E1',
};

export interface RowColorSettings {
  even: string;
  odd: string;
  evenDark: string;
  oddDark: string;
  overbooking: string;
  overbookingDark: string;
}

/** Load row colors from localStorage */
export function loadRowColors(): RowColorSettings {
  try {
    const saved = localStorage.getItem('roomAssignment_rowColors');
    if (saved) return { ...DEFAULT_ROW_COLORS, ...JSON.parse(saved) };
  } catch { /* ignore */ }
  return { ...DEFAULT_ROW_COLORS };
}

/** Save row colors to localStorage */
export function saveRowColors(colors: RowColorSettings): void {
  localStorage.setItem('roomAssignment_rowColors', JSON.stringify(colors));
}

/** Default divider colors */
export const DEFAULT_DIVIDER_COLOR = '#D1D5DB';
