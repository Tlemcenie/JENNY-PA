"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { CreditCard, FileText } from "lucide-react";
import { intentLabel } from "@/lib/utils";
import { openQuotePdf } from "@/lib/api";
import { JennyAvatar } from "@/components/ui/jenny-avatar";
import { FeedbackButtons } from "./feedback-buttons";

interface MessageBubbleProps {
  content: string;
  isUser: boolean;
  timestamp?: string;
  meta?: {
    intent?: string;
    confidence?: number;
    agent?: string;
    phase?: string;
    // Devis généré par Jenny : URL du PDF à télécharger (bouton sous la bulle).
    pdfUrl?: string;
    // acompte : lien de paiement Stripe
    payUrl?: string;
    payAmount?: number;
  };
  // Id du message Jenny persisté : active la validation 👍/👎 sous la bulle.
  messageId?: string;
}

function QuotePdfButton({ pdfUrl }: { pdfUrl: string }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        setBusy(true);
        setFailed(false);
        try {
          await openQuotePdf(pdfUrl);
        } catch {
          setFailed(true);
        } finally {
          setBusy(false);
        }
      }}
      aria-label="Ouvrir le devis en PDF"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 7,
        marginTop: 8,
        padding: "7px 12px",
        fontSize: 12.5,
        fontWeight: 600,
        color: "#fff",
        background: "var(--coral)",
        border: "none",
        borderRadius: 9,
        cursor: busy ? "default" : "pointer",
        opacity: busy ? 0.7 : 1,
      }}
    >
      <FileText style={{ width: 14, height: 14 }} />
      {busy ? "Ouverture…" : failed ? "Réessayer le devis PDF" : "Voir le devis (PDF)"}
    </button>
  );
}

// bouton acompte : ouvre le paiement Stripe
function DepositPayButton({ payUrl, amount }: { payUrl: string; amount?: number }) {
  return (
    <a
      href={payUrl}
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Payer l'acompte en ligne"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 7,
        marginTop: 8,
        padding: "7px 12px",
        fontSize: 12.5,
        fontWeight: 600,
        color: "#fff",
        background: "var(--coral)",
        border: "none",
        borderRadius: 9,
        textDecoration: "none",
      }}
    >
      <CreditCard style={{ width: 14, height: 14 }} />
      {amount ? `Payer l'acompte (${Math.round(amount)}€)` : "Payer l'acompte"}
    </a>
  );
}

export function MessageBubble({ content, isUser, timestamp, meta, messageId }: MessageBubbleProps) {
  // ── Message client (à droite) : bulle coral `.jbubble--me`, horodatage mono dessous.
  if (isUser) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 10, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ type: "spring", stiffness: 380, damping: 30, mass: 0.7 }}
        style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}
      >
        <div className="jbubble jbubble--me">{content}</div>
        {timestamp && (
          <div
            className="jmono"
            style={{ fontSize: 10.5, color: "var(--text-3)", marginTop: 5, letterSpacing: "0.06em" }}
          >
            {timestamp}
          </div>
        )}
      </motion.div>
    );
  }

  // ── Message Jenny (à gauche) : avatar 32 + bulle blanche `.jbubble--them`,
  //    ligne meta/horodatage en mono dessous (intent · confiance · agent — vraies données).
  const hasMeta = !!meta && (!!meta.intent || !!meta.agent);
  return (
    <motion.div
      initial={{ opacity: 0, y: 10, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: "spring", stiffness: 380, damping: 30, mass: 0.7 }}
      style={{ alignSelf: "flex-start", display: "flex", gap: 10, maxWidth: "84%" }}
    >
      <JennyAvatar size={32} tone="light" className="mt-0.5" />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="jbubble jbubble--them" style={{ maxWidth: "100%" }}>
          {content}
        </div>
        {(timestamp || hasMeta) && (
          <div
            className="jmono"
            style={{
              fontSize: 10.5,
              color: "var(--text-3)",
              marginTop: 5,
              letterSpacing: "0.04em",
              display: "flex",
              alignItems: "center",
              gap: 7,
              flexWrap: "wrap",
            }}
          >
            {timestamp && <span>{timestamp}</span>}
            {meta?.intent && (
              <>
                <span aria-hidden>·</span>
                <span>
                  {intentLabel(meta.intent)}
                  {meta.confidence != null && ` ${Math.round(meta.confidence * 100)}%`}
                </span>
              </>
            )}
            {meta?.agent && (
              <>
                <span aria-hidden>·</span>
                <b style={{ color: "var(--coral)" }}>{meta.agent}</b>
              </>
            )}
          </div>
        )}
        {/* Devis PDF proposé par Jenny (bouton d'ouverture authentifié). */}
        {meta?.pdfUrl && <QuotePdfButton pdfUrl={meta.pdfUrl} />}
        {meta?.payUrl && <DepositPayButton payUrl={meta.payUrl} amount={meta.payAmount} />}
        {/* Validation de la réponse (uniquement une fois le message persisté). */}
        {messageId && content.trim().length > 0 && (
          <FeedbackButtons messageId={messageId} />
        )}
      </div>
    </motion.div>
  );
}
