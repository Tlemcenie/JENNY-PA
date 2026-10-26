// couleurs du widget

export const DEFAULT_ACCENT = "#FF7F6A";
const HEX = /^#[0-9a-fA-F]{6}$/;
const DARK_TEXT = "#1A1D26";

export function safeColor(value: string | null | undefined, fallback: string = DEFAULT_ACCENT): string {
  return value && HEX.test(value) ? value : fallback;
}

// luminance relative wcag
function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const v = parseInt(hex.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: number, b: number): number {
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

// texte lisible sur l'accent
export function onAccent(hex: string): string {
  const l = luminance(safeColor(hex));
  const white = contrast(l, 1);
  if (white >= 4.5) return "#FFFFFF";
  return contrast(l, luminance(DARK_TEXT)) > white ? DARK_TEXT : "#FFFFFF";
}
