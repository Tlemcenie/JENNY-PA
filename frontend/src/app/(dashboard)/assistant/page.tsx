"use client";

import {
  useState,
  useRef,
  useEffect,
  useCallback,
  type KeyboardEvent,
} from "react";
import Image from "next/image";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Loader2, AlertCircle } from "lucide-react";
import { ownerChat, ApiError, type OwnerChatResponse } from "@/lib/api";
import { easeOutExpo } from "@/lib/motion";
import { generateUUID, cn } from "@/lib/utils";

// ════════════════════════════════════════════════════════════════════════
// Page « Assistant Jenny » (#62) — chat côté GÉRANT du salon.
// Ici Jenny est transparente : c'est l'assistante du coiffeur. Elle fait des
// comptes rendus, bloque des créneaux, enrichit la base et répond aux
// questions. (À ne pas confondre avec le chat client où Jenny se présente
// comme un membre humain de l'équipe.)
// Branchée sur le vrai endpoint `ownerChat` → POST /api/v1/owner/chat.
// ════════════════════════════════════════════════════════════════════════

// Action métier renvoyée par le backend → petit badge discret sur la bulle.
const ACTION_BADGES: Record<string, { emoji: string; label: string }> = {
  block_slot: { emoji: "📅", label: "créneau bloqué" },
  add_knowledge: { emoji: "📚", label: "ajouté à la base" },
  report: { emoji: "📊", label: "compte rendu" },
};

interface ChatMessage {
  id: string;
  content: string;
  isUser: boolean;
  timestamp: string;
  action?: string;
  error?: boolean;
}

// Suggestions rapides au-dessus de la saisie. `insert` insère le texte dans le
// champ (sans envoyer) au lieu de déclencher l'appel — utile pour « Note que… ».
const SUGGESTIONS: { label: string; insert?: boolean }[] = [
  { label: "Combien j'ai de rendez-vous ?" },
  { label: "Bloque demain de 12h à 14h" },
  { label: "Note que", insert: true },
  { label: "Fais-moi un résumé" },
];

function nowTime(): string {
  return new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

// Petite pastille mascotte réutilisée (avatar des bulles Jenny + en-tête).
function JennyAvatar({ size = 36 }: { size?: number }) {
  return (
    <span
      className="rounded-xl overflow-hidden bg-jenny-mint block shrink-0 relative ring-1 ring-jenny-coral/15"
      style={{ width: size, height: size }}
    >
      <Image
        src="/jenny.png"
        alt="Jenny"
        width={size}
        height={size}
        className="object-cover w-[122%] h-[122%] mt-[2px] max-w-none"
      />
    </span>
  );
}

export default function AssistantPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: generateUUID(),
      content:
        "Salut ! Je suis là pour t'aider à piloter le salon. Que veux-tu savoir ?",
      isUser: false,
      timestamp: nowTime(),
    },
  ]);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, isSending, scrollToBottom]);

  // Hauteur auto de la zone de saisie (1 → ~6 lignes).
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, [input]);

  // Envoi d'un message : ajoute la bulle gérant, appelle `ownerChat`, puis la
  // réponse de Jenny (ou un message d'erreur dans le fil). `text` permet aux
  // chips d'envoyer directement sans passer par l'état du champ.
  const send = useCallback(
    async (raw?: string) => {
      const text = (raw ?? input).trim();
      if (!text || isSending) return;

      setInput("");
      setIsSending(true);

      const userMsg: ChatMessage = {
        id: generateUUID(),
        content: text,
        isUser: true,
        timestamp: nowTime(),
      };
      setMessages((prev) => [...prev, userMsg]);

      try {
        const res: OwnerChatResponse = await ownerChat(text);
        setMessages((prev) => [
          ...prev,
          {
            id: generateUUID(),
            content: res.response,
            isUser: false,
            timestamp: nowTime(),
            action: res.action,
          },
        ]);
      } catch (err) {
        let msg = "Oups, je n'ai pas pu traiter ta demande. Vérifie que le backend tourne et réessaie.";
        if (err instanceof ApiError) {
          const detail = (err.data as { detail?: string })?.detail;
          msg = detail || `Erreur ${err.status} : ${err.statusText}`;
        }
        setMessages((prev) => [
          ...prev,
          {
            id: generateUUID(),
            content: msg,
            isUser: false,
            timestamp: nowTime(),
            error: true,
          },
        ]);
      } finally {
        setIsSending(false);
        // Redonne le focus au champ après l'envoi (confort clavier).
        requestAnimationFrame(() => inputRef.current?.focus());
      }
    },
    [input, isSending]
  );

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  // Chip : soit on insère un préfixe dans le champ (« Note que »), soit on
  // envoie directement le message.
  const handleSuggestion = (s: { label: string; insert?: boolean }) => {
    if (s.insert) {
      setInput((prev) => {
        const base = prev.trim();
        return base ? `${base} ${s.label} ` : `${s.label} `;
      });
      inputRef.current?.focus();
      return;
    }
    void send(s.label);
  };

  return (
    <div className="flex flex-col h-full bg-jenny-bg">
      {/* ════════ En-tête ════════ */}
      <motion.header
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: easeOutExpo }}
        className="px-5 md:px-8 py-5 border-b border-jenny-divider bg-jenny-surface/60 backdrop-blur-sm"
      >
        <div className="max-w-3xl mx-auto flex items-center gap-4">
          <JennyAvatar size={52} />
          <div className="min-w-0">
            <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-jenny-coral mb-1">
              — Ton assistante —
            </div>
            <h1 className="font-display font-normal text-[clamp(22px,3.4vw,30px)] leading-[1.08] tracking-[-0.02em] text-jenny-text">
              Jenny, <span className="italic text-jenny-coral">ton assistante.</span>
            </h1>
            <p className="text-[13px] text-jenny-text-secondary leading-[1.5] mt-1.5 max-w-[560px]">
              Demande-lui un point sur tes rendez-vous, bloque un créneau, ou ajoute une info à ta
              base — par message.
            </p>
          </div>
        </div>
      </motion.header>

      {/* ════════ Zone de messages ════════ */}
      <div className="flex-1 overflow-y-auto px-5 md:px-8 py-6">
        <div className="max-w-3xl mx-auto space-y-4">
          <AnimatePresence initial={false}>
            {messages.map((msg) => (
              <motion.div
                key={msg.id}
                initial={{ opacity: 0, y: 10, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                transition={{ type: "spring", stiffness: 380, damping: 30, mass: 0.7 }}
                className={cn("flex items-start gap-3", msg.isUser ? "justify-end" : "")}
              >
                {/* Avatar Jenny (gauche) */}
                {!msg.isUser &&
                  (msg.error ? (
                    <span className="w-9 h-9 rounded-xl bg-jenny-error/10 flex items-center justify-center shrink-0">
                      <AlertCircle className="w-4 h-4 text-jenny-error" />
                    </span>
                  ) : (
                    <JennyAvatar size={36} />
                  ))}

                {/* Bulle + métadonnées */}
                <div
                  className={cn(
                    "max-w-[78%] md:max-w-[68%] flex flex-col gap-1.5",
                    msg.isUser ? "items-end" : "items-start"
                  )}
                >
                  <div
                    className={cn(
                      "px-4 py-3 text-[0.9375rem] leading-[1.6] whitespace-pre-wrap break-words",
                      msg.isUser
                        ? "bg-jenny-coral/[0.10] border border-jenny-coral/20 text-jenny-text rounded-2xl rounded-tr-md"
                        : msg.error
                          ? "bg-jenny-error/[0.05] border border-jenny-error/20 text-jenny-error rounded-2xl rounded-tl-md"
                          : "bg-jenny-surface border border-jenny-divider text-jenny-text rounded-2xl rounded-tl-md shadow-sm"
                    )}
                  >
                    {msg.content}
                  </div>

                  {/* Badge d'action métier (sur les bulles Jenny non-erreur) */}
                  {!msg.isUser && !msg.error && msg.action && ACTION_BADGES[msg.action] && (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-jenny-coral-tint dark:bg-jenny-coral/10 border border-jenny-coral/20 text-[0.6875rem] font-medium text-jenny-coral">
                      <span aria-hidden>{ACTION_BADGES[msg.action].emoji}</span>
                      {ACTION_BADGES[msg.action].label}
                    </span>
                  )}

                  <span className="text-[0.6875rem] text-jenny-text-secondary/40 px-1">
                    {msg.timestamp}
                  </span>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>

          {/* Indicateur « Jenny écrit… » */}
          <AnimatePresence>
            {isSending && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="flex items-start gap-3"
              >
                <JennyAvatar size={36} />
                <div className="bg-jenny-surface border border-jenny-divider rounded-2xl rounded-tl-md px-4 py-3 flex items-center gap-2 shadow-sm">
                  <Loader2 className="w-3.5 h-3.5 text-jenny-coral animate-spin" />
                  <span className="text-[0.8125rem] text-jenny-text-secondary">Jenny écrit…</span>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* ════════ Saisie + suggestions ════════ */}
      <div className="border-t border-jenny-divider bg-jenny-surface/60 backdrop-blur-sm px-5 md:px-8 py-4">
        <div className="max-w-3xl mx-auto">
          {/* Chips de suggestions rapides */}
          <div className="flex flex-wrap gap-2 mb-3">
            {SUGGESTIONS.map((s) => (
              <button
                key={s.label}
                type="button"
                onClick={() => handleSuggestion(s)}
                disabled={isSending}
                className="px-3 py-1.5 rounded-full bg-jenny-bg border border-jenny-divider text-[0.8125rem] text-jenny-text-secondary hover:text-jenny-coral hover:border-jenny-coral/40 hover:bg-jenny-coral/[0.04] transition-all duration-150 disabled:opacity-40 disabled:pointer-events-none"
              >
                {s.insert ? `${s.label}…` : s.label}
              </button>
            ))}
          </div>

          {/* Barre de saisie */}
          <div className="flex items-end gap-3">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Écris à Jenny… (ex. « Bloque vendredi de 14h à 16h »)"
              rows={1}
              aria-label="Message pour Jenny"
              className="flex-1 resize-none px-4 py-3.5 rounded-xl bg-jenny-bg border border-jenny-divider text-[0.9375rem] text-jenny-text placeholder:text-jenny-text-secondary/50 focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral transition-all leading-relaxed"
              style={{ maxHeight: 160 }}
            />
            <button
              type="button"
              onClick={() => void send()}
              disabled={!input.trim() || isSending}
              aria-label="Envoyer"
              className="h-12 w-12 shrink-0 rounded-xl bg-jenny-coral text-white inline-flex items-center justify-center shadow-sm shadow-jenny-coral/20 hover:bg-jenny-coral-dark active:scale-[0.97] transition-all disabled:opacity-40 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-jenny-coral/30 focus-visible:ring-offset-2"
            >
              {isSending ? (
                <Loader2 className="w-[18px] h-[18px] animate-spin" />
              ) : (
                <Send className="w-[18px] h-[18px]" />
              )}
            </button>
          </div>

          <p className="text-[0.6875rem] text-jenny-text-secondary/40 mt-2.5 text-center">
            Entrée pour envoyer &middot; Maj+Entrée pour un retour à la ligne
          </p>
        </div>
      </div>
    </div>
  );
}
