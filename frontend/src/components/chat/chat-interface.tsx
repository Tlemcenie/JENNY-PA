"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, AlertCircle, RotateCcw, Sparkles, Info, CalendarPlus } from "lucide-react";
import { sendMessage, streamChat, type ConversationResponse, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { generateUUID } from "@/lib/utils";
import { MessageBubble } from "./message-bubble";
import { TypingIndicator } from "./typing-indicator";
import { Button } from "@/components/ui/button";
import { ScheduleAppointmentDialog } from "@/components/customer/schedule-appointment-dialog";

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
          // Si aucun token n'est arrivé (réponse vide), on crée quand même la
          // bulle pour ne pas laisser le fil sans réponse.
          const finalMeta = {
            intent: typeof meta.intent === "string" ? meta.intent : undefined,
            confidence:
              typeof meta.intent_confidence === "number" ? meta.intent_confidence : undefined,
            agent: typeof meta.agent_used === "string" ? meta.agent_used : undefined,
            phase:
              typeof meta.conversation_phase === "string" ? meta.conversation_phase : undefined,
          };
          if (!firstTokenReceived) {
            firstTokenReceived = true;
            setIsTyping(false);
            setMessages((prev) => [
              ...prev,
              {
                id: jennyId,
                content: "",
                isUser: false,
                timestamp: jennyTimestamp,
                meta: finalMeta,
              },
            ]);
            return;
          }
          setMessages((prev) =>
            prev.map((m) => (m.id === jennyId ? { ...m, meta: finalMeta } : m))
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
    <div className="flex flex-col h-full bg-white">
      {/* Chat header */}
      <div className="px-5 md:px-8 py-4 border-b border-jenny-divider">
        <div className="flex items-center gap-3.5">
          <div className="w-11 h-11 rounded-2xl bg-brand-gradient flex items-center justify-center shadow-sm shadow-jenny-coral/25">
            <Sparkles className="w-5 h-5 text-white" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="font-semibold text-[0.9375rem] text-jenny-text">Jenny</h2>
            <p className="text-[0.75rem] text-jenny-text-secondary leading-snug truncate">
              Votre assistante, connectée en direct
            </p>
          </div>
          <button
            onClick={() => setScheduleOpen(true)}
            title="Planifier un rendez-vous"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-jenny-divider text-[0.75rem] font-medium text-jenny-text-secondary hover:text-jenny-coral hover:border-jenny-coral/40 hover:bg-jenny-coral/[0.04] transition-all"
          >
            <CalendarPlus className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Planifier un RDV</span>
          </button>
          <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-jenny-mint/60 text-[0.6875rem] font-medium text-jenny-text-secondary">
            <div className="w-1.5 h-1.5 rounded-full bg-jenny-success" />
            <code>/conversation/chat</code>
          </div>
        </div>
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-5 md:px-8 py-6">
        <div className="max-w-3xl mx-auto space-y-5">
          {messages.length === 0 && (
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex flex-col items-center justify-center min-h-[50vh] text-center px-4"
            >
              <div className="w-20 h-20 rounded-3xl bg-gradient-to-br from-jenny-coral/10 via-jenny-coral/5 to-jenny-mint/40 flex items-center justify-center mb-7">
                <Sparkles className="w-9 h-9 text-jenny-coral" />
              </div>
              <h3 className="text-xl md:text-2xl font-bold text-jenny-text mb-2.5 tracking-tight max-w-none">
                Discutez avec Jenny
              </h3>
              <p className="text-jenny-text-secondary text-[0.9375rem] leading-relaxed max-w-lg mb-8">
                Posez vos questions comme le ferait un client : Jenny comprend et répond
                naturellement, en temps réel.
              </p>
              <div className="flex flex-wrap gap-2.5 justify-center mb-10">
                {[
                  "Quels sont vos horaires ?",
                  "Je voudrais un devis",
                  "Suivi de ma commande",
                ].map((suggestion) => (
                  <button
                    key={suggestion}
                    onClick={() => {
                      setInput(suggestion);
                      inputRef.current?.focus();
                    }}
                    className="px-4 py-2.5 rounded-xl bg-white border border-jenny-divider text-[0.875rem] text-jenny-text hover:border-jenny-coral/40 hover:bg-jenny-coral/[0.03] transition-all duration-150"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>

              <div className="flex items-start gap-2.5 p-4 rounded-xl bg-jenny-mint/30 border border-jenny-mint-dark/20 text-[0.8125rem] text-jenny-text-secondary max-w-lg text-left leading-relaxed">
                <Info className="w-4 h-4 flex-shrink-0 mt-0.5 text-jenny-coral/70" />
                <span>
                  Ce chat utilise le vrai endpoint{" "}
                  <code className="font-mono text-[0.75rem] bg-white/60 px-1.5 py-0.5 rounded-md">/api/v1/conversation/chat</code>.
                  Les réponses dépendent du LLM configuré côté backend.
                </span>
              </div>
            </motion.div>
          )}

          {messages.map((msg) =>
            msg.error ? (
              <motion.div
                key={msg.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex items-start gap-3 max-w-[85%]"
              >
                <div className="w-9 h-9 rounded-xl bg-jenny-error/8 flex items-center justify-center flex-shrink-0">
                  <AlertCircle className="w-4 h-4 text-jenny-error" />
                </div>
                <div className="bg-jenny-error/[0.04] border border-jenny-error/15 rounded-2xl rounded-tl-lg px-4 py-3.5">
                  <p className="text-[0.875rem] text-jenny-error leading-relaxed">{msg.content}</p>
                  <button
                    onClick={handleRetry}
                    className="flex items-center gap-1.5 mt-2.5 text-[0.8125rem] text-jenny-error/80 hover:text-jenny-error transition-colors font-medium"
                  >
                    <RotateCcw className="w-3.5 h-3.5" />
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

          <AnimatePresence>{isTyping && <TypingIndicator />}</AnimatePresence>
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input area */}
      <div className="border-t border-jenny-divider bg-white px-5 md:px-8 py-4">
        {error && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            className="mb-3 p-3 rounded-xl bg-jenny-warning/8 border border-jenny-warning/15 text-jenny-warning text-[0.8125rem] flex items-center gap-2.5 leading-snug"
          >
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            Connexion au backend instable
          </motion.div>
        )}
        <div className="max-w-3xl mx-auto flex items-end gap-3">
          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Écrivez votre message..."
              rows={1}
              className="w-full resize-none px-4 py-3.5 rounded-xl bg-jenny-bg border border-jenny-divider text-[0.9375rem] text-jenny-text placeholder:text-jenny-text-secondary/50 focus:outline-none focus:ring-2 focus:ring-jenny-coral/20 focus:border-jenny-coral transition-all leading-relaxed"
              style={{ maxHeight: 140 }}
            />
          </div>
          <Button
            onClick={handleSend}
            disabled={!input.trim() || isTyping}
            size="md"
            className="h-12 w-12 p-0 rounded-xl flex-shrink-0"
          >
            <Send className="w-[18px] h-[18px]" />
          </Button>
        </div>
        <p className="text-[0.6875rem] text-jenny-text-secondary/40 mt-2.5 text-center max-w-3xl mx-auto">
          Maj+Entrée pour retour à la ligne &middot; Entrée pour envoyer
        </p>
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
