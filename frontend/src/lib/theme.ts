// Gestion du thème (clair/sombre/système) et de la couleur d'accent (#19).
// L'accent surcharge les variables CSS Tailwind `--color-jenny-coral*` sur
// <html>, donc TOUT le `bg-jenny-coral`/`text-jenny-coral` suit la couleur
// choisie, sans recompilation. Le thème système suit `prefers-color-scheme`.

export type ThemeMode = "light" | "dark" | "system";

export interface AccentPreset {
  name: string;
  value: string;
}

// Palette d'accents proposée (la 1re est la couleur de marque par défaut).
export const ACCENTS: AccentPreset[] = [
  { name: "Corail", value: "#FF7F6A" },
  { name: "Bleu", value: "#3B82F6" },
  { name: "Violet", value: "#8B5CF6" },
  { name: "Émeraude", value: "#10B981" },
  { name: "Ambre", value: "#F59E0B" },
  { name: "Rose", value: "#EC4899" },
  { name: "Cyan", value: "#06B6D4" },
];

export const DEFAULT_ACCENT = ACCENTS[0].value;

const THEME_KEY = "jenny-theme";
const ACCENT_KEY = "jenny-accent";

function clampHex(c: number): string {
  return Math.max(0, Math.min(255, Math.round(c))).toString(16).padStart(2, "0");
}

/** Mélange une couleur hex vers blanc (p>0) ou noir, proportion `p` ∈ [0,1]. */
function mix(hex: string, target: number, p: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const f = (c: number) => clampHex(c + (target - c) * p);
  return `#${f(r)}${f(g)}${f(b)}`;
}

/** Applique la couleur d'accent (base + variantes claire/sombre) à <html>. */
export function applyAccent(hex: string): void {
  if (typeof document === "undefined") return;
  const s = document.documentElement.style;
  s.setProperty("--color-jenny-coral", hex);
  s.setProperty("--color-jenny-coral-light", mix(hex, 255, 0.45));
  s.setProperty("--color-jenny-coral-dark", mix(hex, 0, 0.12));
}

export function getStoredAccent(): string {
  if (typeof localStorage === "undefined") return DEFAULT_ACCENT;
  return localStorage.getItem(ACCENT_KEY) || DEFAULT_ACCENT;
}

export function setStoredAccent(hex: string): void {
  try {
    if (hex === DEFAULT_ACCENT) localStorage.removeItem(ACCENT_KEY);
    else localStorage.setItem(ACCENT_KEY, hex);
  } catch {
    // ignore (navigation privée)
  }
  applyAccent(hex);
}

export function getStoredTheme(): ThemeMode {
  if (typeof localStorage === "undefined") return "system";
  const t = localStorage.getItem(THEME_KEY);
  return t === "light" || t === "dark" || t === "system" ? t : "system";
}

/** Applique un mode de thème et le persiste. Met à jour la classe `.dark`. */
export function applyTheme(mode: ThemeMode): void {
  if (typeof document === "undefined") return;
  const prefersDark =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches;
  const dark = mode === "dark" || (mode === "system" && prefersDark);
  document.documentElement.classList.toggle("dark", dark);
  try {
    localStorage.setItem(THEME_KEY, mode);
  } catch {
    // ignore
  }
}
