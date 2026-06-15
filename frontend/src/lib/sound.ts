// Préférence de son pour les notifications (persistée en localStorage).
// Le son est un petit carillon synthétisé via Web Audio — aucun asset requis.

const SOUND_KEY = "jenny-sound";

export function isSoundEnabled(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(SOUND_KEY) !== "off"; // activé par défaut
}

export function setSoundEnabled(on: boolean): void {
  try {
    localStorage.setItem(SOUND_KEY, on ? "on" : "off");
  } catch {
    // mode privé : on ignore
  }
}

type AudioCtor = typeof AudioContext;

export function playNotificationSound(): void {
  if (!isSoundEnabled() || typeof window === "undefined") return;
  const Ctor: AudioCtor | undefined =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: AudioCtor }).webkitAudioContext;
  if (!Ctor) return;
  try {
    const ctx = new Ctor();
    void ctx.resume?.();
    const now = ctx.currentTime;
    // Carillon à deux notes (montant), discret et agréable.
    const notes: Array<[number, number]> = [
      [880, 0],
      [1320, 0.12],
    ];
    for (const [freq, offset] of notes) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, now + offset);
      gain.gain.exponentialRampToValueAtTime(0.14, now + offset + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.18);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now + offset);
      osc.stop(now + offset + 0.2);
    }
    setTimeout(() => void ctx.close().catch(() => {}), 500);
  } catch {
    // politique d'autoplay / contexte indisponible : on ignore
  }
}
