"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, AlertCircle, RotateCcw, CalendarPlus, Paperclip, ImageIcon } from "lucide-react";
import { sendMessage, streamChat, type ConversationResponse, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { generateUUID } from "@/lib/utils";
import { MessageBubble } from "./message-bubble";
import { TypingIndicator } from "./typing-indicator";
import { JennyAvatar } from "@/components/ui/jenny-avatar";
import { ScheduleAppointmentDialog } from "@/components/customer/schedule-appointment-dialog";

// Suggestions clientes (présentation) : elles ne font que pré-remplir l'input —
// même comportement que l'état vide existant, aucune logique réseau ajoutée.
const QUICK_SUGGESTIONS = [
  "Quels sont vos horaires ?",
  "Je voudrais prendre rendez-vous",
  "Combien coûte une coupe ?",
];

interface ChatMessage {
  id: string;
  content: string;
  isUser: boolean;
  timestamp: string;
  meta?: {
    intent?: string;
    confidence?: number;
    agent?: string;
    phase?: string;
  };
  error?: boolean;
}

export function ChatInterface() {
  const { user } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [conversationId] = useState(() => generateUUID());
  const [error, setError] = useState<string | null>(null);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping, scrollToBottom]);

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = "auto";
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 140) + "px";
    }
  }, [input]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || isTyping) return;
    if (!user?.business_id) {
      setError("Session invalide : aucun business associé à votre compte.");
      return;
    }

    setInput("");
    setError(null);

    const userMsg: ChatMessage = {
      id: generateUUID(),
      content: text,
      isUser: true,
      timestamp: new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }),
    };

    setMessages((prev) => [...prev, userMsg]);
    setIsTyping(true);

    // Bulle Jenny vide qui va se remplir token par token. On garde son id
    // stable pendant tout le stream pour ne mettre à jour que ce message.
    const jennyId = generateUUID();
    const jennyTimestamp = new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });

    // Append d'un token au contenu de la bulle Jenny en cours.
    const appendToken = (token: string) => {
      setMessages((prev) =>
        prev.map((m) => (m.id === jennyId ? { ...m, content: m.content + token } : m))
      );
    };

    try {
      let firstTokenReceived = false;

      await streamChat(
        {
          conversation_id: conversationId,
          business_id: user.business_id,
          message: text,
          channel: "api",
          language: "fr",
        },
        (token) => {
          // Au tout premier token : on insère la bulle Jenny puis on coupe
          // l'indicateur « Jenny écrit… » — le texte prend le relais.
          if (!firstTokenReceived) {
            firstTokenReceived = true;
            setIsTyping(false);
            setMessages((prev) => [
              ...prev,
              {
                id: jennyId,
                content: token,
                isUser: false,
                timestamp: jennyTimestamp,
              },
            ]);
            return;
          }
          appendToken(token);
        },
        (meta) => {
          // Fin du stream : on attache les métadonnées (intent, agent…).
          const finalMeta = {
            intent: typeof meta.intent === "string" ? meta.intent : undefined,
            confidence:
              typeof meta.intent_confidence === "number" ? meta.intent_confidence : undefined,
            agent: typeof meta.agent_used === "string" ? meta.agent_used : undefined,
            phase:
              typeof meta.conversation_phase === "string" ? meta.conversation_phase : undefined,
          };
          // Le back envoie la version FINALE nettoyée (garde-fou persona) dans
          // `text` : elle fait autorité → on remplace l'affichage brut par elle.
          const finalText = typeof meta.text === "string" ? meta.text : undefined;
          if (!firstTokenReceived) {
            firstTokenReceived = true;
            setIsTyping(false);
            setMessages((prev) => [
              ...prev,
              {
                id: jennyId,
                content: finalText ?? "",
                isUser: false,
                timestamp: jennyTimestamp,
                meta: finalMeta,
              },
            ]);
            return;
          }
          setMessages((prev) =>
            prev.map((m) =>
              m.id === jennyId
                ? { ...m, meta: finalMeta, content: finalText ?? m.content }
                : m
            )
          );
        }
      );
    } catch (streamErr) {
      // Le streaming a échoué : on retombe proprement sur l'appel non-streamé
      // existant pour ne rien casser. La bulle Jenny n'a pas encore été insérée
      // (ou est vide), donc on la (re)construit avec la réponse complète.
      setMessages((prev) => prev.filter((m) => m.id !== jennyId));

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const response: ConversationResponse = await sendMessage(
          conversationId,
          user.business_id,
          text,
          controller.signal
        );

        const jennyMsg: ChatMessage = {
          id: jennyId,
          content: response.response,
          isUser: false,
          timestamp: new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }),
          meta: {
            intent: response.intent,
            confidence: response.intent_confidence,
            agent: response.agent_used,
            phase: response.conversation_phase,
          },
        };

        setMessages((prev) => [...prev, jennyMsg]);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;

        let errorMessage = "Impossible d'obtenir une réponse. Vérifiez que le backend est lancé.";
        if (err instanceof ApiError) {
          const detail = (err.data as { detail?: string })?.detail;
          errorMessage = detail || `Erreur ${err.status}: ${err.statusText}`;
        } else if (streamErr instanceof ApiError) {
          const detail = (streamErr.data as { detail?: string })?.detail;
          errorMessage = detail || `Erreur ${streamErr.status}: ${streamErr.statusText}`;
        }

        setError(errorMessage);

        const errorMsg: ChatMessage = {
          id: generateUUID(),
          content: errorMessage,
          isUser: false,
          timestamp: new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }),
          error: true,
        };

        setMessages((prev) => [...prev, errorMsg]);
      }
    } finally {
      setIsTyping(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleRetry = () => {
    const lastUserMsg = [...messages].reverse().find((m) => m.isUser);
    if (lastUserMsg) {
      setMessages((prev) => prev.filter((m) => !m.error));
      setInput(lastUserMsg.content);
      setError(null);
    }
  };

  return (
    <div
      className="jx"
      style={{ display: "grid", gridTemplateRows: "auto 1fr", height: "100%", background: "var(--surface)" }}
    >
      {/* ── En-tête du chat : avatar + nom + badge « EN LIGNE » + sous-titre réel ── */}
      <div
        style={{
          padding: "16px 32px",
          borderBottom: "1px solid var(--divider)",
          display: "flex",
          alignItems: "center",
          gap: 14,
        }}
      >
        <JennyAvatar size={46} tone="light" priority />
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 15.5, fontWeight: 600, letterSpacing: "-0.01em", color: "var(--text)" }}>
              Jenny
            </span>
            <span
              className="jmono"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                padding: "2px 9px",
                background: "rgba(16,185,129,0.1)",
                color: "var(--success)",
                borderRadius: 999,
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: "0.06em",
              }}
            >
              <span style={{ width: 5, height: 5, background: "var(--success)", borderRadius: "50%" }} />
              EN LIGNE
            </span>
          </div>
          <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 1 }}>
            Répond comme un membre de votre équipe · en direct
          </div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <button
            type="button"
            onClick={() => setScheduleOpen(true)}
            title="Planifier un rendez-vous"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              height: 32,
              padding: "0 12px",
              borderRadius: "var(--r-btn)",
              border: "1px solid var(--divider)",
              background: "var(--surface)",
              color: "var(--text-2)",
              fontSize: 12,
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            <CalendarPlus style={{ width: 14, height: 14 }} />
            <span className="hidden sm:inline">Planifier un RDV</span>
          </button>
        </div>
      </div>

      {/* ── Colonne de messages : fond dégradé, colonne centrée max 680 ── */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
          background: "linear-gradient(180deg, var(--bg-tint) 0%, var(--surface) 30%)",
        }}
      >
        <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "24px 32px" }}>
          <div style={{ maxWidth: 680, margin: "0 auto", display: "flex", flexDirection: "column", gap: 16 }}>
            {messages.length === 0 ? (
              <motion.div
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  textAlign: "center",
                  minHeight: "48vh",
                  padding: "0 16px",
                }}
              >
                <JennyAvatar size={80} tone="light" priority className="mb-7" />
                <h3 className="jserif" style={{ fontSize: 30, lineHeight: 1.05, color: "var(--text)", marginBottom: 10 }}>
                  Discutez avec <span style={{ fontStyle: "italic", color: "var(--coral)" }}>Jenny.</span>
                </h3>
                <p
                  style={{
                    fontSize: 14.5,
                    lineHeight: 1.6,
                    color: "var(--text-2)",
                    maxWidth: 460,
                    margin: "0 0 28px",
                  }}
                >
                  Posez vos questions comme le ferait un client : Jenny comprend et répond
                  naturellement, en temps réel.
                </p>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
                  {QUICK_SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      className="jpill"
                      onClick={() => {
                        setInput(suggestion);
                        inputRef.current?.focus();
                      }}
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </motion.div>
            ) : (
              <>
                {/* Séparateur de date — étiquette mono entre deux filets */}
                <div style={{ display: "flex", alignItems: "center", gap: 12, margin: "2px 0 4px" }}>
                  <div style={{ flex: 1, height: 1, background: "var(--divider)" }} />
                  <span
                    className="jmono"
                    style={{
                      fontSize: 11,
                      color: "var(--text-3)",
                      letterSpacing: "0.12em",
                      textTransform: "uppercase",
                    }}
                  >
                    Aujourd&apos;hui — {messages[0]?.timestamp}
                  </span>
                  <div style={{ flex: 1, height: 1, background: "var(--divider)" }} />
                </div>

                {messages.map((msg) =>
                  msg.error ? (
                    <motion.div
                      key={msg.id}
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      style={{ alignSelf: "flex-start", display: "flex", gap: 10, maxWidth: "84%" }}
                    >
                      <div
                        style={{
                          width: 32,
                          height: 32,
                          borderRadius: 8,
                          flexShrink: 0,
                          marginTop: 2,
                          display: "grid",
                          placeItems: "center",
                          background: "color-mix(in srgb, var(--error) 10%, transparent)",
                        }}
                      >
                        <AlertCircle style={{ width: 16, height: 16, color: "var(--error)" }} />
                      </div>
                      <div
                        className="jbubble jbubble--them"
                        style={{
                          maxWidth: "100%",
                          borderColor: "color-mix(in srgb, var(--error) 22%, var(--divider))",
                        }}
                      >
                        <div style={{ color: "var(--error)" }}>{msg.content}</div>
                        <button
                          type="button"
                          onClick={handleRetry}
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 6,
                            marginTop: 10,
                            fontSize: 12.5,
                            fontWeight: 600,
                            color: "var(--error)",
                            background: "transparent",
                            border: "none",
                            cursor: "pointer",
                          }}
                        >
                          <RotateCcw style={{ width: 13, height: 13 }} />
                          Réessayer
                        </button>
                      </div>
                    </motion.div>
                  ) : (
                    <MessageBubble
                      key={msg.id}
                      content={msg.content}
                      isUser={msg.isUser}
                      timestamp={msg.timestamp}
                      meta={msg.meta}
                    />
                  )
                )}
              </>
            )}

            <AnimatePresence>{isTyping && <TypingIndicator />}</AnimatePresence>
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* ── Dock de saisie : pilules de suggestion + barre arrondie + envoi coral ── */}
        <div style={{ padding: "14px 32px 20px", borderTop: "1px solid var(--divider)", background: "var(--surface)" }}>
          <div style={{ maxWidth: 680, margin: "0 auto" }}>
            {error && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 10,
                  padding: "8px 12px",
                  borderRadius: 12,
                  fontSize: 12.5,
                  color: "var(--warning)",
                  background: "color-mix(in srgb, var(--warning) 10%, transparent)",
                  border: "1px solid color-mix(in srgb, var(--warning) 22%, transparent)",
                }}
              >
                <AlertCircle style={{ width: 15, height: 15, flexShrink: 0 }} />
                Connexion au backend instable
              </motion.div>
            )}

            <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
              {QUICK_SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  className="jpill"
                  onClick={() => {
                    setInput(suggestion);
                    inputRef.current?.focus();
                  }}
                >
                  {suggestion}
                </button>
              ))}
            </div>

            <div
              className="jcomposer"
              style={{
                display: "flex",
                alignItems: "flex-end",
                gap: 8,
                padding: 8,
                background: "var(--bg)",
                border: "1px solid var(--divider)",
                borderRadius: "calc(var(--r-card) * .85)",
                transition: "box-shadow .15s ease, border-color .15s ease",
              }}
            >
              <button
                type="button"
                aria-label="Joindre un fichier"
                style={{ display: "grid", placeItems: "center", width: 34, height: 34, border: "none", background: "transparent", cursor: "pointer" }}
              >
                <Paperclip style={{ width: 17, height: 17, color: "var(--text-2)" }} />
              </button>
              <button
                type="button"
                aria-label="Joindre une image"
                style={{ display: "grid", placeItems: "center", width: 34, height: 34, border: "none", background: "transparent", cursor: "pointer" }}
              >
                <ImageIcon style={{ width: 17, height: 17, color: "var(--text-2)" }} />
              </button>
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Écrivez votre message à Jenny…"
                rows={1}
                style={{
                  flex: 1,
                  minHeight: 24,
                  maxHeight: 140,
                  resize: "none",
                  background: "transparent",
                  border: "none",
                  outline: "none",
                  fontFamily: "var(--font-sans)",
                  fontSize: 14.5,
                  lineHeight: 1.55,
                  color: "var(--text)",
                  paddingTop: 9,
                  paddingBottom: 3,
                }}
              />
              <button
                type="button"
                onClick={handleSend}
                disabled={!input.trim() || isTyping}
                aria-label="Envoyer"
                style={{
                  display: "grid",
                  placeItems: "center",
                  width: 40,
                  height: 40,
                  flexShrink: 0,
                  padding: 0,
                  borderRadius: "var(--r-btn)",
                  border: "none",
                  background: "var(--coral)",
                  color: "#fff",
                  cursor: !input.trim() || isTyping ? "not-allowed" : "pointer",
                  opacity: !input.trim() || isTyping ? 0.5 : 1,
                  boxShadow: "var(--shadow-pop)",
                  transition: "opacity 0.16s ease, filter 0.16s ease",
                }}
              >
                <Send style={{ width: 17, height: 17 }} />
              </button>
            </div>

            <div
              className="jmono"
              style={{ fontSize: 10.5, color: "var(--text-3)", textAlign: "center", marginTop: 9, letterSpacing: "0.05em" }}
            >
              Maj+Entrée pour un retour à la ligne · Entrée pour envoyer
            </div>
          </div>
        </div>
      </div>

      {/* Planifier un rendez-vous lié à la conversation courante (#27) */}
      <ScheduleAppointmentDialog
        open={scheduleOpen}
        onClose={() => setScheduleOpen(false)}
        context={{ conversationId }}
      />
    </div>
  );
}
