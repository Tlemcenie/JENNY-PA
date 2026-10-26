// client api du widget public
import { ApiError } from "./api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface WidgetConfig {
  name: string;
  color: string;
  greeting: string;
  suggestions: string[];
}

export interface WidgetQuote {
  reference: string | null;
  lines: { name: string; price_eur: number }[];
  total_eur: number | null;
}

export interface WidgetPayment {
  amount_eur: number | null;
  url: string;
}

export interface WidgetReply {
  response: string;
  quick_replies: string[];
  handoff: boolean;
  human: boolean;
  quote: WidgetQuote | null;
  payment: WidgetPayment | null;
}

export interface WidgetTeamMessage {
  id: string;
  text: string;
  at: string | null;
}

export interface WidgetPoll {
  human: boolean;
  messages: WidgetTeamMessage[];
}

interface CallOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}

function base(slug: string): string {
  return `/api/v1/public/chat/${encodeURIComponent(slug)}`;
}

// sans token ni stockage
async function bareRequest<T>(endpoint: string, { method = "GET", body, signal }: CallOptions): Promise<T> {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
    credentials: "omit",
    signal,
  });
  if (!res.ok) {
    let data: unknown;
    try {
      data = await res.json();
    } catch {
      // pas de json
    }
    throw new ApiError(res.status, res.statusText, data);
  }
  return res.json() as Promise<T>;
}

// toujours anonyme, sans jeton
function call<T>(endpoint: string, options: CallOptions = {}): Promise<T> {
  return bareRequest<T>(endpoint, options);
}

export function getWidgetConfig(slug: string, signal?: AbortSignal): Promise<WidgetConfig> {
  return call<WidgetConfig>(`${base(slug)}/config`, { signal });
}

export function sendWidgetMessage(
  slug: string,
  visitorId: string,
  message: string,
  signal?: AbortSignal
): Promise<WidgetReply> {
  return call<WidgetReply>(base(slug), {
    method: "POST",
    body: { visitor_id: visitorId, message },
    signal,
  });
}

export function pollWidgetTeam(slug: string, visitorId: string, signal?: AbortSignal): Promise<WidgetPoll> {
  return call<WidgetPoll>(`${base(slug)}/poll`, {
    method: "POST",
    body: { visitor_id: visitorId },
    signal,
  });
}

// message d'erreur lisible
export function widgetErrorText(err: unknown): { text: string; retryAfter: number; gone?: boolean } {
  if (err instanceof ApiError) {
    const data = (err.data ?? {}) as { detail?: unknown; retry_after?: unknown };
    const retry = typeof data.retry_after === "number" ? data.retry_after : 0;
    if (err.status === 429) {
      const text = typeof data.detail === "string" ? data.detail : "Trop de messages, patientez un peu.";
      return { text, retryAfter: Math.max(1, retry) };
    }
    if (err.status === 404) return { text: "Ce salon n'est pas disponible pour le moment.", retryAfter: 0 };
    // conv fermée : en refaire une
    if (err.status === 403)
      return { text: "Cette discussion n'est plus disponible, démarrez-en une nouvelle.", retryAfter: 0, gone: true };
    if (err.status === 413 || err.status === 422)
      return { text: "Message trop long ou invalide, raccourcissez-le un peu.", retryAfter: 0 };
    if (err.status >= 500) {
      const text = typeof data.detail === "string" ? data.detail : "Jenny est indisponible, réessayez dans un instant.";
      return { text, retryAfter: 0 };
    }
    return { text: "Une erreur est survenue, réessayez.", retryAfter: 0 };
  }
  if (typeof navigator !== "undefined" && navigator.onLine === false) {
    return { text: "Vous semblez hors ligne. Vérifiez votre connexion.", retryAfter: 0 };
  }
  return { text: "Connexion impossible pour le moment, réessayez.", retryAfter: 0 };
}

export { ApiError };
