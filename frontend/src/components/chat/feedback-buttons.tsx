"use client";

import { useState } from "react";
import { ThumbsUp, ThumbsDown, Check } from "lucide-react";
import { submitFeedback, type FeedbackRating } from "@/lib/api";

interface FeedbackButtonsProps {
  messageId: string;
}

/**
 * Validation simple d'une réponse de Jenny : pouce haut / pouce bas.
 * Sur un pouce bas, on propose (facultatif) un court commentaire d'amélioration.
 * Optimiste : l'UI réagit tout de suite, l'appel réseau suit ; en cas d'échec
 * on revient à l'état précédent. (Pas d'hydratation d'un vote passé : le chat
 * de test repart de zéro à chaque visite, un message n'est donc noté qu'une fois.)
 */
export function FeedbackButtons({ messageId }: FeedbackButtonsProps) {
  const [rating, setRating] = useState<number | null>(null);
  const [showComment, setShowComment] = useState(false);
  const [comment, setComment] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const send = async (value: FeedbackRating, text?: string) => {
    const prev = rating;
    setRating(value); // optimiste
    setBusy(true);
    try {
      await submitFeedback(messageId, value, text);
      if (text !== undefined) {
        setSaved(true);
        setShowComment(false);
        setTimeout(() => setSaved(false), 1800);
      }
    } catch {
      setRating(prev); // rollback
    } finally {
      setBusy(false);
    }
  };

  const handleUp = () => {
    setShowComment(false);
    void send(1);
  };

  const handleDown = () => {
    void send(-1);
    setShowComment(true);
  };

  const btnBase: React.CSSProperties = {
    display: "grid",
    placeItems: "center",
    width: 26,
    height: 26,
    borderRadius: 7,
    border: "1px solid var(--divider)",
    background: "var(--surface)",
    cursor: busy ? "default" : "pointer",
    transition: "all .14s ease",
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <button
          type="button"
          onClick={handleUp}
          aria-label="Réponse utile"
          aria-pressed={rating === 1}
          title="Réponse utile"
          style={{
            ...btnBase,
            borderColor: rating === 1 ? "var(--success)" : "var(--divider)",
            background:
              rating === 1 ? "color-mix(in srgb, var(--success) 14%, transparent)" : "var(--surface)",
          }}
        >
          <ThumbsUp
            style={{
              width: 13,
              height: 13,
              color: rating === 1 ? "var(--success)" : "var(--text-3)",
            }}
          />
        </button>
        <button
          type="button"
          onClick={handleDown}
          aria-label="Réponse à revoir"
          aria-pressed={rating === -1}
          title="Réponse à revoir"
          style={{
            ...btnBase,
            borderColor: rating === -1 ? "var(--error)" : "var(--divider)",
            background:
              rating === -1 ? "color-mix(in srgb, var(--error) 14%, transparent)" : "var(--surface)",
          }}
        >
          <ThumbsDown
            style={{
              width: 13,
              height: 13,
              color: rating === -1 ? "var(--error)" : "var(--text-3)",
            }}
          />
        </button>
        {saved && (
          <span
            className="jmono"
            style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 10.5, color: "var(--success)" }}
          >
            <Check style={{ width: 12, height: 12 }} /> Merci
          </span>
        )}
      </div>

      {showComment && (
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void send(-1, comment.trim());
            }}
            placeholder="Qu'est-ce qui n'allait pas ? (facultatif)"
            maxLength={1000}
            style={{
              flex: 1,
              height: 28,
              padding: "0 10px",
              fontSize: 12,
              color: "var(--text)",
              background: "var(--bg)",
              border: "1px solid var(--divider)",
              borderRadius: 8,
              outline: "none",
            }}
          />
          <button
            type="button"
            onClick={() => void send(-1, comment.trim())}
            style={{
              height: 28,
              padding: "0 10px",
              fontSize: 12,
              fontWeight: 600,
              color: "#fff",
              background: "var(--coral)",
              border: "none",
              borderRadius: 8,
              cursor: "pointer",
            }}
          >
            Envoyer
          </button>
        </div>
      )}
    </div>
  );
}
