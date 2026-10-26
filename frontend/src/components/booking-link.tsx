"use client";

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { CalendarCheck, Check, Copy, Download, ExternalLink, Share2 } from "lucide-react";
import { makeQr, qrPath } from "@/lib/qr";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

// lien de réservation à partager

const QR_MARGIN = 4;
const QR_DARK = "#0E0B14";

const noop = () => () => {};

// copie avec repli ancien
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      return ok;
    } catch {
      return false;
    }
  }
}

// qr en png pour impression
function downloadQrPng(matrix: boolean[][], fileName: string) {
  const cell = 16;
  const side = (matrix.length + QR_MARGIN * 2) * cell;
  const canvas = document.createElement("canvas");
  canvas.width = side;
  canvas.height = side;
  const ctx = canvas.getContext("2d");
  if (!ctx) return false;
  ctx.fillStyle = "#FFFFFF";
  ctx.fillRect(0, 0, side, side);
  ctx.fillStyle = QR_DARK;
  matrix.forEach((row, y) =>
    row.forEach((on, x) => {
      if (on) ctx.fillRect((x + QR_MARGIN) * cell, (y + QR_MARGIN) * cell, cell, cell);
    })
  );
  canvas.toBlob((blob) => {
    if (!blob) return;
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = fileName;
    a.click();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
  }, "image/png");
  return true;
}

/** Carte lien public + QR. */
export function BookingLink({
  slug,
  businessName,
  className,
}: {
  slug: string;
  businessName: string;
  className?: string;
}) {
  const toast = useToast();
  const origin = useSyncExternalStore(noop, () => window.location.origin, () => "");
  const canShare = useSyncExternalStore(
    noop,
    () => typeof navigator.share === "function",
    () => false
  );
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const url = origin ? `${origin}/book/${encodeURIComponent(slug)}` : "";
  const shownUrl = url.replace(/^https?:\/\//, "");

  // qr calculé une fois
  const qr = useMemo(() => {
    if (!url) return null;
    try {
      return makeQr(url, "M");
    } catch {
      return null;
    }
  }, [url]);

  const onCopy = async () => {
    if (!url) return;
    if (await copyText(url)) {
      setCopied(true);
      toast.success("Lien copié, collez-le dans votre bio.");
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 2000);
    } else {
      toast.error("Copie impossible, sélectionnez le lien à la main.");
    }
  };

  const onShare = async () => {
    try {
      await navigator.share({
        title: businessName,
        text: `Réservez chez ${businessName} en ligne :`,
        url,
      });
    } catch {
      // partage annulé
    }
  };

  const onDownload = () => {
    if (!qr) return;
    if (!downloadQrPng(qr, `qr-reservation-${slug}.png`)) toast.error("Téléchargement impossible.");
  };

  const btn =
    "inline-flex items-center justify-center gap-1.5 h-9 px-3.5 rounded-xl text-[0.8125rem] font-semibold transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-jenny-coral/40 disabled:opacity-40 disabled:pointer-events-none";
  const ghostBtn = cn(
    btn,
    "bg-jenny-surface border border-jenny-divider text-jenny-text hover:border-jenny-coral/40 hover:text-jenny-coral"
  );

  return (
    <section
      aria-labelledby="booking-link-title"
      className={cn("bg-jenny-surface rounded-2xl border border-jenny-divider p-6", className)}
    >
      <div className="flex items-center gap-3 mb-1.5">
        <CalendarCheck className="w-5 h-5 text-jenny-coral" aria-hidden="true" />
        <h3 id="booking-link-title" className="font-semibold text-jenny-text">
          Votre page de réservation
        </h3>
        <span className="ml-auto inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-[0.08em] text-jenny-success">
          <span className="w-1.5 h-1.5 rounded-full bg-jenny-success" aria-hidden="true" />
          En ligne
        </span>
      </div>
      <p className="text-[0.8125rem] text-jenny-text-secondary leading-relaxed mb-5">
        Un lien à mettre dans votre bio Instagram, sur Google et WhatsApp : vos clients
        réservent seuls, 24h/24.
      </p>

      <div className="flex flex-col sm:flex-row gap-5 sm:items-center">
        {/* qr toujours sur fond clair */}
        <div
          className="shrink-0 self-center sm:self-auto w-[132px] h-[132px] rounded-xl border border-jenny-divider p-1.5"
          style={{ background: "#FFFFFF" }}
        >
          {qr ? (
            <svg
              viewBox={`0 0 ${qr.length + QR_MARGIN * 2} ${qr.length + QR_MARGIN * 2}`}
              className="w-full h-full"
              shapeRendering="crispEdges"
              role="img"
              aria-label={`QR code vers ${shownUrl}`}
            >
              <path d={qrPath(qr, QR_MARGIN)} fill={QR_DARK} />
            </svg>
          ) : (
            <div className="w-full h-full rounded-lg animate-shimmer" aria-hidden="true" />
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 h-11 px-3.5 rounded-xl bg-jenny-bg border border-jenny-divider">
            {url ? (
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="min-w-0 flex-1 truncate font-mono text-[0.8125rem] text-jenny-text hover:text-jenny-coral underline-offset-2 hover:underline"
                title={url}
              >
                {shownUrl}
              </a>
            ) : (
              <span className="flex-1 h-3 rounded animate-shimmer" aria-hidden="true" />
            )}
            {url && <ExternalLink className="w-3.5 h-3.5 shrink-0 text-jenny-text-secondary" aria-hidden="true" />}
          </div>

          <div className="flex flex-wrap gap-2 mt-3">
            <button
              type="button"
              onClick={onCopy}
              disabled={!url}
              className={cn(btn, "bg-jenny-coral text-white hover:bg-jenny-coral-dark shadow-sm shadow-jenny-coral/20")}
            >
              {copied ? <Check className="w-4 h-4" aria-hidden="true" /> : <Copy className="w-4 h-4" aria-hidden="true" />}
              {copied ? "Copié" : "Copier le lien"}
            </button>
            {canShare && (
              <button type="button" onClick={onShare} disabled={!url} className={ghostBtn}>
                <Share2 className="w-4 h-4" aria-hidden="true" />
                Partager
              </button>
            )}
            <button type="button" onClick={onDownload} disabled={!qr} className={ghostBtn}>
              <Download className="w-4 h-4" aria-hidden="true" />
              QR code (PNG)
            </button>
          </div>
          <p className="mt-3 text-xs text-jenny-text-secondary">
            Astuce : imprimez le QR code et posez-le près de la caisse.
          </p>
          <span role="status" className="sr-only">
            {copied ? "Lien copié dans le presse-papiers" : ""}
          </span>
        </div>
      </div>
    </section>
  );
}
