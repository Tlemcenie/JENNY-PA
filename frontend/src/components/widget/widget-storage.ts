// stockage sûr du widget

export type WidgetRole = "visitor" | "jenny" | "team";

export interface StoredMessage {
  id: string;
  role: WidgetRole;
  text: string;
  at: number;
  quote?: {
    reference: string | null;
    lines: { name: string; price_eur: number }[];
    total_eur: number | null;
  } | null;
  payment?: { amount_eur: number | null; url: string } | null;
}

interface StoredLog {
  v: 1;
  at: number;
  human: boolean;
  messages: StoredMessage[];
}

const TTL_MS = 7 * 24 * 3600 * 1000; // une semaine
const MAX_KEPT = 60;
// repli en mémoire
const memory = new Map<string, string>();

function pickStore(): Storage | null {
  for (const name of ["localStorage", "sessionStorage"] as const) {
    try {
      const s = window[name];
      const probe = "jw-probe";
      s.setItem(probe, "1");
      s.removeItem(probe);
      return s;
    } catch {
      // bloqué, suivant
    }
  }
  return null;
}

let store: Storage | null | undefined;

function getStore(): Storage | null {
  if (typeof window === "undefined") return null;
  if (store === undefined) store = pickStore();
  return store;
}

function read(key: string): string | null {
  const s = getStore();
  if (s) {
    try {
      return s.getItem(key);
    } catch {
      // ignore
    }
  }
  return memory.get(key) ?? null;
}

function write(key: string, value: string | null): void {
  const s = getStore();
  if (value === null) memory.delete(key);
  else memory.set(key, value);
  if (!s) return;
  try {
    if (value === null) s.removeItem(key);
    else s.setItem(key, value);
  } catch {
    // quota plein
  }
}

const vidKey = (slug: string) => `jw1:${slug}:vid`;
const logKey = (slug: string) => `jw1:${slug}:log`;

// id visiteur aléatoire
export function newVisitorId(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  } catch {
    // très vieux navigateur
    return `v${Date.now().toString(36)}${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`;
  }
}

const VID_RE = /^[A-Za-z0-9_-]{16,64}$/;

export function loadSession(slug: string): { visitorId: string; messages: StoredMessage[]; human: boolean } {
  let visitorId = read(vidKey(slug)) || "";
  let messages: StoredMessage[] = [];
  let human = false;
  try {
    const raw = read(logKey(slug));
    const log = raw ? (JSON.parse(raw) as StoredLog) : null;
    if (log && log.v === 1 && Date.now() - log.at < TTL_MS && Array.isArray(log.messages)) {
      messages = log.messages.filter((m) => m && typeof m.text === "string" && typeof m.id === "string");
      human = log.human === true;
    } else if (log) {
      // trop vieux : on repart
      visitorId = "";
    }
  } catch {
    messages = [];
  }
  if (!VID_RE.test(visitorId)) {
    visitorId = newVisitorId();
    write(vidKey(slug), visitorId);
    write(logKey(slug), null);
    messages = [];
    human = false;
  }
  return { visitorId, messages, human };
}

export function saveLog(slug: string, messages: StoredMessage[], human: boolean): void {
  const log: StoredLog = { v: 1, at: Date.now(), human, messages: messages.slice(-MAX_KEPT) };
  write(logKey(slug), JSON.stringify(log));
}

export function resetSession(slug: string): string {
  const visitorId = newVisitorId();
  write(vidKey(slug), visitorId);
  write(logKey(slug), null);
  return visitorId;
}
