"use client";

import { useCallback, useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { CalendarDays, CircleAlert, CreditCard, RotateCcw, SendHorizontal, X } from "lucide-react";
import { JennyAvatar } from "@/components/ui/jenny-avatar";
import {
  ApiError,
  getWidgetConfig,
  pollWidgetTeam,
  sendWidgetMessage,
  widgetErrorText,
  type WidgetConfig,
  type WidgetPoll,
  type WidgetReply,
} from "@/lib/api-widget";
import { onAccent, safeColor } from "./widget-color";
import { loadSession, resetSession, saveLog, type StoredMessage } from "./widget-storage";
import styles from "./widget.module.css";

const MAX_LEN = 1000;
const WARN_LEN = 850;
const FAST_POLL = 8_000;
const SLOW_POLL = 30_000;
const ACTIVE_MS = 3 * 60_000;
const RECENT_MS = 10 * 60_000;
// réponse qui parle de RDV
const BOOK_RE = /rendez-vous|\brdv\b|réserv|créneau|disponib/i;
// RDV déjà calé
const DONE_RE = /confirm|c'est noté|enregistr|annul/i;

type Phase = "loading" | "ready" | "notfound" | "error";
type Theme = "auto" | "light" | "dark";

interface ChatMessage extends StoredMessage {
  failed?: boolean;
}

interface WidgetError {
  text: string;
  rate: boolean;
  gone?: boolean;
}

interface WidgetChatProps {
  slug: string;
  color?: string;
  theme?: string;
  embedded?: boolean;
}

// message vers la page hôte
function toHost(type: string, extra?: Record<string, unknown>): void {
  if (typeof window === "undefined" || window.parent === window) return;
  try {
    window.parent.postMessage({ jw: 1, type, ...extra }, "*");
  } catch {
    // hôte injoignable
  }
}

function localId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

// liens cliquables
const URL_RE = /(https?:\/\/[^\s<>"')]*[^\s<>"').,;:!?])/g;

function linkify(text: string): ReactNode[] {
  return text.split(URL_RE).map((part, i) =>
    i % 2 === 1 ? (
      <a key={i} href={part} target="_blank" rel="noopener noreferrer nofollow">
        {part}
      </a>
    ) : (
      part
    )
  );
}

function euros(value: number): string {
  return new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(value);
}

function QuoteCard({ quote }: { quote: NonNullable<StoredMessage["quote"]> }) {
  return (
    <div className={styles.card}>
      <div className={styles.cardTitle}>Devis{quote.reference ? ` ${quote.reference}` : ""}</div>
      {quote.lines.map((l, i) => (
        <div key={`${l.name}-${i}`} className={styles.line}>
          <span>{l.name}</span>
          <span>{euros(l.price_eur)}</span>
        </div>
      ))}
      {quote.total_eur !== null && (
        <div className={styles.total}>
          <span>Total TTC</span>
          <span>{euros(quote.total_eur)}</span>
        </div>
      )}
    </div>
  );
}

function MessageRow({
  m,
  busy,
  onRetry,
}: {
  m: ChatMessage;
  busy: boolean;
  onRetry: (m: ChatMessage) => void;
}) {
  const visitor = m.role === "visitor";
  const tone = visitor ? styles.bubbleVisitor : m.role === "team" ? styles.bubbleTeam : styles.bubbleJenny;
  const who = visitor ? "Vous" : m.role === "team" ? "L'équipe du salon" : "Jenny";
  return (
    <div className={`${styles.row} ${visitor ? styles.rowVisitor : ""}`}>
      {m.role === "team" && (
        <span className={styles.who} aria-hidden="true">
          L&apos;équipe du salon
        </span>
      )}
      <div className={`${styles.bubble} ${tone} ${m.failed ? styles.failed : ""}`}>
        <span className={styles.srOnly}>{who} : </span>
        {linkify(m.text)}
      </div>
      {m.quote && <QuoteCard quote={m.quote} />}
      {m.payment && (
        <a className={styles.payBtn} href={m.payment.url} target="_blank" rel="noopener noreferrer">
          <CreditCard size={16} aria-hidden="true" />
          {m.payment.amount_eur ? `Régler l'acompte de ${euros(m.payment.amount_eur)}` : "Régler l'acompte"}
        </a>
      )}
      {m.failed && (
        <button type="button" className={styles.retry} onClick={() => onRetry(m)} disabled={busy}>
          Non envoyé · Réessayer
        </button>
      )}
    </div>
  );
}

export function WidgetChat({ slug, color, theme, embedded = false }: WidgetChatProps) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [config, setConfig] = useState<WidgetConfig | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [visitorId, setVisitorId] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [human, setHuman] = useState(false);
  const [quick, setQuick] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const [error, setError] = useState<WidgetError | null>(null);
  const [cooldown, setCooldown] = useState(0);
  const [open, setOpen] = useState(!embedded);

  const logRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const messagesRef = useRef<ChatMessage[]>([]);
  const openRef = useRef(open);
  const humanRef = useRef(human);
  const lastActivity = useRef(0);
  const unread = useRef(0);
  const teamSeen = useRef<Set<string>>(new Set());
  const wantFocus = useRef(false);
  const inputId = useId();
  const hintId = useId();

  const themeAttr: Theme = theme === "light" || theme === "dark" ? theme : "auto";
  const accent = safeColor(color, safeColor(config?.color));
  const rootStyle = { "--w-accent": accent, "--w-on-accent": onAccent(accent) } as CSSProperties;

  // refs à jour
  useEffect(() => {
    messagesRef.current = messages;
    openRef.current = open;
    humanRef.current = human;
  }, [messages, open, human]);

  // session locale
  useEffect(() => {
    const s = loadSession(slug);
    teamSeen.current = new Set(s.teamSeen);
    setVisitorId(s.visitorId);
    setMessages(s.messages);
    setHuman(s.human);
  }, [slug]);

  // config du salon
  useEffect(() => {
    const ctrl = new AbortController();
    getWidgetConfig(slug, ctrl.signal)
      .then((c) => {
        setConfig(c);
        setPhase("ready");
      })
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setPhase(err instanceof ApiError && err.status === 404 ? "notfound" : "error");
      });
    return () => ctrl.abort();
  }, [slug, reloadKey]);

  // sauvegarde locale
  useEffect(() => {
    if (!visitorId) return;
    saveLog(
      slug,
      messages.filter((m) => !m.failed),
      human,
      Array.from(teamSeen.current)
    );
  }, [slug, visitorId, messages, human]);

  // scroll en bas
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, typing, quick, human, phase]);

  // textarea auto
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
  }, [input]);

  // compte à rebours
  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => {
      setCooldown((c) => c - 1);
      if (cooldown === 1) setError((e) => (e?.rate ? null : e));
    }, 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  const focusInput = useCallback(() => {
    const fine = typeof window !== "undefined" && window.matchMedia?.("(pointer: fine)").matches;
    const target = fine ? inputRef.current : logRef.current;
    // pas encore affiché : plus tard
    if (!target) {
      wantFocus.current = true;
      return;
    }
    wantFocus.current = false;
    try {
      window.focus();
    } catch {
      // ignore
    }
    target.focus({ preventScroll: true });
  }, []);

  // focus en attente
  useEffect(() => {
    if (phase === "ready" && wantFocus.current) focusInput();
  }, [phase, focusInput]);

  // dialogue avec embed.js
  useEffect(() => {
    if (!embedded) return;
    const onMessage = (e: MessageEvent) => {
      if (e.source !== window.parent) return;
      const d = e.data as { jw?: number; type?: string } | null;
      if (!d || d.jw !== 1) return;
      if (d.type === "open") {
        setOpen(true);
        unread.current = 0;
        focusInput();
      } else if (d.type === "closed") {
        setOpen(false);
      }
    };
    window.addEventListener("message", onMessage);
    toHost("ready");
    return () => window.removeEventListener("message", onMessage);
  }, [embedded, focusInput]);

  // échap
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (embedded) {
        e.preventDefault();
        toHost("close");
      } else if (document.activeElement === inputRef.current) {
        inputRef.current?.blur();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [embedded]);

  const mergeTeam = useCallback((res: WidgetPoll) => {
    setHuman(res.human);
    const known = new Set(messagesRef.current.map((m) => m.id));
    // déjà vus, même hors log
    const fresh: ChatMessage[] = res.messages
      .filter((t) => !known.has(`t-${t.id}`) && !teamSeen.current.has(`t-${t.id}`))
      .map((t) => ({
        id: `t-${t.id}`,
        role: "team",
        text: t.text,
        at: (t.at && Date.parse(t.at)) || Date.now(),
      }));
    if (!fresh.length) return;
    for (const m of fresh) teamSeen.current.add(m.id);
    lastActivity.current = Date.now();
    setMessages((prev) => {
      const ids = new Set(prev.map((m) => m.id));
      return [...prev, ...fresh.filter((m) => !ids.has(m.id))];
    });
    if (!openRef.current) {
      unread.current += fresh.length;
      toHost("unread", { count: unread.current });
    }
  }, []);

  const started = messages.some((m) => m.role === "visitor");

  // réponses de l'équipe
  useEffect(() => {
    if (!visitorId || phase !== "ready" || !started) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ctrl = new AbortController();
    const tick = async () => {
      if (stop) return;
      const visible = document.visibilityState === "visible";
      // fermé : seulement si récent
      const recent = Date.now() - lastActivity.current < RECENT_MS;
      if (visible && (openRef.current || humanRef.current || recent)) {
        try {
          const res = await pollWidgetTeam(slug, visitorId, ctrl.signal);
          if (!stop) mergeTeam(res);
        } catch {
          // silencieux, on retente
        }
      }
      if (stop) return;
      const active = Date.now() - lastActivity.current < ACTIVE_MS;
      timer = setTimeout(tick, openRef.current && active ? FAST_POLL : SLOW_POLL);
    };
    timer = setTimeout(tick, 4_000);
    return () => {
      stop = true;
      ctrl.abort();
      if (timer) clearTimeout(timer);
    };
  }, [slug, visitorId, phase, started, mergeTeam]);

  const handleReply = useCallback((r: WidgetReply) => {
    if (r.human) setHuman(true);
    if (r.handoff || r.human) lastActivity.current = Date.now();
    const text = (r.response || "").trim();
    if (text) {
      const payment = r.payment && r.payment.url.startsWith("https://") ? r.payment : null;
      setMessages((prev) => [
        ...prev,
        { id: localId("j"), role: "jenny", text, at: Date.now(), quote: r.quote, payment },
      ]);
    }
    setQuick(Array.isArray(r.quick_replies) ? r.quick_replies.slice(0, 4) : []);
  }, []);

  const send = useCallback(
    async (raw: string, retryOf?: string) => {
      const text = raw.trim();
      if (!text || text.length > MAX_LEN || typing || cooldown > 0 || !visitorId || phase !== "ready") return;
      const id = retryOf ?? localId("v");
      setError(null);
      setQuick([]);
      setOpen(true);
      lastActivity.current = Date.now();
      setMessages((prev) => [
        ...(retryOf ? prev.filter((m) => m.id !== retryOf) : prev),
        { id, role: "visitor", text, at: Date.now() },
      ]);
      if (!retryOf) setInput("");
      setTyping(true);
      try {
        handleReply(await sendWidgetMessage(slug, visitorId, text));
      } catch (err) {
        const { text: message, retryAfter, gone } = widgetErrorText(err);
        setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, failed: true } : m)));
        setError({ text: message, rate: retryAfter > 0, gone });
        if (retryAfter > 0) setCooldown(Math.min(retryAfter, 120));
      } finally {
        setTyping(false);
      }
    },
    [typing, cooldown, visitorId, phase, slug, handleReply]
  );

  const reset = () => {
    teamSeen.current = new Set();
    setVisitorId(resetSession(slug));
    setMessages([]);
    setHuman(false);
    setQuick([]);
    setError(null);
    setInput("");
    focusInput();
  };

  const name = config?.name ?? "";
  const last = messages[messages.length - 1];
  const chips = !config ? [] : !started ? config.suggestions : last?.role === "jenny" ? quick : [];
  // lien de réservation utile ?
  const bookTalk =
    last?.role === "jenny" && BOOK_RE.test(last.text) && !DONE_RE.test(last.text) && !quick.includes("Oui");
  const showBook = !!config && !human && (!started || bookTalk);
  const bookUrl = `/book/${encodeURIComponent(slug)}`;
  const busy = typing || cooldown > 0;
  const tooLong = input.length > MAX_LEN;

  return (
    <section
      className={styles.root}
      data-theme={themeAttr}
      style={rootStyle}
      aria-label={`Discussion avec Jenny, assistante virtuelle${name ? ` de ${name}` : ""}`}
    >
      <header className={styles.header}>
        <JennyAvatar size={38} />
        <div className={styles.headText}>
          <h1 className={styles.title}>{name ? `Jenny · ${name}` : "Jenny"}</h1>
          <p className={styles.subtitle}>
            <span className={styles.online} aria-hidden="true" />
            {human ? "L'équipe du salon vous répond" : "Assistante virtuelle"}
          </p>
        </div>
        {phase === "ready" && (
          <a
            className={styles.iconBtn}
            href={bookUrl}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Réserver en ligne (nouvel onglet)"
            title="Réserver en ligne"
          >
            <CalendarDays size={18} aria-hidden="true" />
          </a>
        )}
        {messages.length > 0 && (
          <button
            type="button"
            className={styles.iconBtn}
            onClick={reset}
            disabled={typing}
            aria-label="Nouvelle conversation"
            title="Nouvelle conversation"
          >
            <RotateCcw size={17} aria-hidden="true" />
          </button>
        )}
        {embedded && (
          <button
            type="button"
            className={styles.iconBtn}
            onClick={() => toHost("close")}
            aria-label="Fermer la discussion"
            title="Fermer (Échap)"
          >
            <X size={19} aria-hidden="true" />
          </button>
        )}
      </header>

      {phase === "loading" && (
        <div className={styles.center} role="status">
          <span className={styles.spinner} aria-hidden="true" />
          Connexion à Jenny…
        </div>
      )}

      {phase === "notfound" && (
        <div className={styles.center} role="alert">
          Ce salon n&apos;est pas disponible pour le moment.
        </div>
      )}

      {phase === "error" && (
        <div className={styles.center} role="alert">
          Impossible de joindre Jenny pour l&apos;instant.
          <button
            type="button"
            className={styles.ghostBtn}
            onClick={() => {
              setPhase("loading");
              setReloadKey((k) => k + 1);
            }}
          >
            Réessayer
          </button>
        </div>
      )}

      {phase === "ready" && config && (
        <>
          <div
            ref={logRef}
            className={styles.log}
            role="log"
            aria-live="polite"
            aria-label="Messages"
            tabIndex={-1}
          >
            <MessageRow m={{ id: "greeting", role: "jenny", text: config.greeting, at: 0 }} busy onRetry={() => {}} />
            {messages.map((m) => (
              <MessageRow key={m.id} m={m} busy={busy} onRetry={(f) => void send(f.text, f.id)} />
            ))}
            {human && <p className={styles.note}>L&apos;équipe du salon a pris le relais ici.</p>}
            {typing && (
              <div className={styles.row}>
                <span className={styles.typing}>
                  <span className={styles.dots} aria-hidden="true">
                    <span />
                    <span />
                    <span />
                  </span>
                  {human ? "Envoi à l'équipe…" : "Jenny écrit…"}
                </span>
              </div>
            )}
          </div>

          {(chips.length > 0 || showBook) && !typing && (
            <div className={styles.chips} role="group" aria-label="Réponses rapides">
              {chips.map((c) => (
                <button
                  key={c}
                  type="button"
                  className={styles.chip}
                  onClick={() => void send(c)}
                  disabled={busy}
                >
                  {c}
                </button>
              ))}
              {showBook && (
                <a className={`${styles.chip} ${styles.chipBook}`} href={bookUrl} target="_blank" rel="noopener noreferrer">
                  <CalendarDays size={14} aria-hidden="true" />
                  Réserver en ligne
                  <span className={styles.srOnly}> (nouvel onglet)</span>
                </a>
              )}
            </div>
          )}

          {error && (
            <div className={styles.error} role="alert">
              <CircleAlert size={16} aria-hidden="true" />
              <span>{error.text}</span>
              {error.gone && (
                <button type="button" className={styles.errorAction} onClick={reset} disabled={typing}>
                  Nouvelle conversation
                </button>
              )}
            </div>
          )}

          <form
            className={styles.composer}
            onSubmit={(e) => {
              e.preventDefault();
              void send(input);
            }}
          >
            <label htmlFor={inputId} className={styles.srOnly}>
              Votre message à Jenny
            </label>
            <textarea
              id={inputId}
              ref={inputRef}
              className={styles.input}
              rows={1}
              value={input}
              maxLength={MAX_LEN}
              placeholder="Écrivez votre message…"
              aria-describedby={hintId}
              aria-invalid={tooLong || undefined}
              enterKeyHint="send"
              autoComplete="off"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  void send(input);
                }
              }}
            />
            <button
              type="submit"
              className={styles.send}
              disabled={!input.trim() || tooLong || busy}
              aria-label="Envoyer le message"
            >
              <SendHorizontal size={19} aria-hidden="true" />
            </button>
          </form>
          <div className={styles.foot} id={hintId}>
            <span>
              {cooldown > 0 ? `Patientez ${cooldown} s avant le prochain message.` : "Jenny est une assistante virtuelle."}
            </span>
            {input.length > WARN_LEN && (
              <span className={input.length >= MAX_LEN ? styles.counterWarn : undefined}>
                {input.length}/{MAX_LEN}
              </span>
            )}
          </div>
        </>
      )}
    </section>
  );
}
