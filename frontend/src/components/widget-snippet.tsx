"use client";

import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { Check, Code, Copy, ExternalLink, MessageCircle, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { getBusiness } from "@/lib/api";
import { DEFAULT_ACCENT, onAccent, safeColor } from "@/components/widget/widget-color";
import { cn } from "@/lib/utils";

// code à coller + aperçu

const SWATCHES = ["#FF7F6A", "#E4405F", "#7C5CFF", "#2563EB", "#0F766E", "#1A1D26"];

type Side = "right" | "left";
type Theme = "auto" | "light" | "dark";

interface WidgetSnippetProps {
  slug?: string;
  className?: string;
}

const noop = () => () => {};

function attr(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

// copie avec repli
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
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  }
}

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { id: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-xl border border-jenny-divider p-0.5">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          role="radio"
          aria-checked={value === o.id}
          onClick={() => onChange(o.id)}
          className={cn(
            "px-3 h-8 rounded-[10px] text-[0.8125rem] font-medium transition-colors",
            value === o.id
              ? "bg-jenny-coral/10 text-jenny-coral"
              : "text-jenny-text-secondary hover:text-jenny-text"
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function WidgetSnippet({ slug: slugProp, className }: WidgetSnippetProps) {
  const [fetchedSlug, setFetchedSlug] = useState("");
  const [loadError, setLoadError] = useState(false);
  const [color, setColor] = useState(DEFAULT_ACCENT);
  const [side, setSide] = useState<Side>("right");
  const [theme, setTheme] = useState<Theme>("auto");
  const [copied, setCopied] = useState<"ok" | "ko" | null>(null);
  const [live, setLive] = useState(false);

  const slug = slugProp || fetchedSlug;

  // origine du site, côté client
  const origin = useSyncExternalStore(noop, () => window.location.origin, () => "");

  // slug du salon connecté
  useEffect(() => {
    if (slugProp) return;
    let off = false;
    getBusiness()
      .then((b) => {
        if (!off) setFetchedSlug(b.slug);
      })
      .catch(() => {
        if (!off) setLoadError(true);
      });
    return () => {
      off = true;
    };
  }, [slugProp]);

  const code = useMemo(() => {
    if (!slug || !origin) return "";
    const attrs = [`src="${attr(origin)}/embed.js"`, `data-salon="${attr(slug)}"`];
    if (color.toLowerCase() !== DEFAULT_ACCENT.toLowerCase()) attrs.push(`data-color="${color}"`);
    if (side === "left") attrs.push('data-position="left"');
    if (theme !== "auto") attrs.push(`data-theme="${theme}"`);
    return `<script ${attrs.join(" ")} async></script>`;
  }, [slug, origin, color, side, theme]);

  const previewSrc = slug
    ? `/widget/${encodeURIComponent(slug)}?c=${encodeURIComponent(color)}&t=${theme}`
    : "";

  const onCopy = async () => {
    if (!code) return;
    const ok = await copyText(code);
    setCopied(ok ? "ok" : "ko");
    setTimeout(() => setCopied(null), 2000);
  };

  const fg = onAccent(color);

  return (
    <Card className={cn("p-6", className)}>
      <div className="flex items-center gap-3 mb-2">
        <Code className="w-5 h-5 text-jenny-coral" aria-hidden="true" />
        <h3 className="font-semibold text-jenny-text">Jenny sur votre site</h3>
      </div>
      <p className="text-sm text-jenny-text-secondary mb-5">
        Copiez le code à coller sur votre site : une bulle apparaît en bas de vos pages et Jenny,
        votre assistante virtuelle, répond à vos visiteurs et prend leurs rendez-vous 24h/24.
      </p>

      {loadError && !slug && (
        <p role="alert" className="text-sm text-jenny-error mb-4">
          Impossible de charger votre salon. Rechargez la page.
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        {/* réglages + code */}
        <div className="space-y-4 min-w-0">
          <div>
            <p className="text-xs font-semibold text-jenny-text-secondary mb-2">Couleur</p>
            <div className="flex flex-wrap items-center gap-2">
              {SWATCHES.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setColor(s)}
                  aria-label={`Couleur ${s}`}
                  aria-pressed={color.toLowerCase() === s.toLowerCase()}
                  className={cn(
                    "w-8 h-8 rounded-full border-2 transition-transform",
                    color.toLowerCase() === s.toLowerCase()
                      ? "border-jenny-text scale-110"
                      : "border-transparent motion-safe:hover:scale-105"
                  )}
                  style={{ background: s }}
                />
              ))}
              <label className="inline-flex items-center gap-2 text-xs text-jenny-text-secondary ml-1">
                <input
                  type="color"
                  value={color.toLowerCase()}
                  onChange={(e) => setColor(safeColor(e.target.value))}
                  className="w-8 h-8 rounded-lg border border-jenny-divider bg-transparent cursor-pointer"
                  aria-label="Couleur personnalisée"
                />
                Autre
              </label>
            </div>
          </div>

          <div className="flex flex-wrap gap-4">
            <div>
              <p className="text-xs font-semibold text-jenny-text-secondary mb-2">Position</p>
              <Segmented
                label="Position de la bulle"
                value={side}
                onChange={setSide}
                options={[
                  { id: "right", label: "Droite" },
                  { id: "left", label: "Gauche" },
                ]}
              />
            </div>
            <div>
              <p className="text-xs font-semibold text-jenny-text-secondary mb-2">Thème</p>
              <Segmented
                label="Thème du widget"
                value={theme}
                onChange={setTheme}
                options={[
                  { id: "auto", label: "Auto" },
                  { id: "light", label: "Clair" },
                  { id: "dark", label: "Sombre" },
                ]}
              />
            </div>
          </div>

          <div>
            <p className="text-xs font-semibold text-jenny-text-secondary mb-2">
              Code à coller juste avant <span className="font-mono">&lt;/body&gt;</span>
            </p>
            <div className="relative">
              <pre
                className="text-xs font-mono bg-jenny-bg border border-jenny-divider rounded-xl p-3 pr-12 text-jenny-text whitespace-pre-wrap break-all min-h-[64px]"
                aria-label="Code du widget"
              >
                {code || "Chargement…"}
              </pre>
              <button
                type="button"
                onClick={onCopy}
                disabled={!code}
                aria-label="Copier le code"
                className="absolute top-2 right-2 p-2 rounded-lg text-jenny-text-secondary hover:text-jenny-coral hover:bg-jenny-coral/10 transition-colors disabled:opacity-40"
              >
                {copied === "ok" ? (
                  <Check className="w-4 h-4 text-jenny-success" />
                ) : (
                  <Copy className="w-4 h-4" />
                )}
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-3 mt-3">
              <button
                type="button"
                onClick={onCopy}
                disabled={!code}
                className="inline-flex items-center gap-2 h-10 px-4 rounded-xl bg-jenny-coral text-white text-sm font-semibold hover:bg-jenny-coral-dark transition-colors disabled:opacity-40"
              >
                <Copy className="w-4 h-4" aria-hidden="true" />
                Copier le code à coller sur votre site
              </button>
              <span aria-live="polite" className="text-xs text-jenny-text-secondary">
                {copied === "ok" ? "Copié !" : copied === "ko" ? "Copie impossible, sélectionnez le code." : ""}
              </span>
            </div>
          </div>

          <ul className="text-xs text-jenny-text-secondary space-y-1.5 list-disc pl-4">
            <li>WordPress, Wix, Shopify, Squarespace : collez-le dans « code personnalisé » du pied de page.</li>
            <li>
              Un bouton de votre site peut ouvrir Jenny : ajoutez-lui{" "}
              <span className="font-mono text-jenny-text">data-jenny-open</span>.
            </li>
            <li>Jenny se présente toujours comme assistante virtuelle à vos visiteurs.</li>
          </ul>
        </div>

        {/* aperçu */}
        <div className="min-w-0">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-semibold text-jenny-text-secondary">Aperçu</p>
            {previewSrc && (
              <a
                href={previewSrc}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-jenny-text-secondary hover:text-jenny-coral"
              >
                Ouvrir en grand <ExternalLink className="w-3 h-3" aria-hidden="true" />
              </a>
            )}
          </div>
          <div
            className="relative h-[460px] rounded-2xl border border-jenny-divider overflow-hidden bg-jenny-bg"
            aria-label="Aperçu du widget sur un site"
          >
            {/* faux navigateur */}
            <div className="flex items-center gap-1.5 h-8 px-3 border-b border-jenny-divider bg-jenny-surface">
              <span className="w-2.5 h-2.5 rounded-full bg-jenny-divider" />
              <span className="w-2.5 h-2.5 rounded-full bg-jenny-divider" />
              <span className="w-2.5 h-2.5 rounded-full bg-jenny-divider" />
              <span className="ml-3 h-4 flex-1 max-w-[220px] rounded-md bg-jenny-divider/60" />
            </div>
            <div className="p-5 space-y-3" aria-hidden="true">
              <div className="h-5 w-2/5 rounded bg-jenny-divider/70" />
              <div className="h-3 w-4/5 rounded bg-jenny-divider/50" />
              <div className="h-3 w-3/5 rounded bg-jenny-divider/50" />
              <div className="h-24 w-full rounded-xl bg-jenny-divider/40 mt-4" />
            </div>

            {live && previewSrc && (
              <div
                className={cn(
                  "absolute bottom-[84px] w-[min(340px,calc(100%-32px))] h-[330px] rounded-2xl overflow-hidden shadow-2xl border border-jenny-divider bg-white",
                  side === "left" ? "left-4" : "right-4"
                )}
              >
                <iframe
                  src={previewSrc}
                  title="Aperçu en direct de Jenny"
                  className="w-full h-full border-0 block"
                />
              </div>
            )}

            {!live && (
              <div
                className={cn(
                  "absolute bottom-[84px] max-w-[220px] rounded-2xl bg-white text-[#1A1D26] text-[13px] leading-snug px-3.5 py-2.5 shadow-lg",
                  side === "left" ? "left-4" : "right-4"
                )}
                aria-hidden="true"
              >
                Une question ? Je suis Jenny, l&apos;assistante virtuelle du salon.
              </div>
            )}

            <button
              type="button"
              onClick={() => setLive((v) => !v)}
              disabled={!previewSrc}
              aria-label={live ? "Fermer l'aperçu en direct" : "Tester le widget en direct"}
              aria-pressed={live}
              className={cn(
                "absolute bottom-4 w-14 h-14 rounded-full grid place-items-center shadow-xl transition-transform motion-safe:hover:-translate-y-0.5 disabled:opacity-50",
                side === "left" ? "left-4" : "right-4"
              )}
              style={{ background: color, color: fg }}
            >
              {live ? <X className="w-6 h-6" /> : <MessageCircle className="w-6 h-6" />}
            </button>
          </div>
          <p className="text-[11px] text-jenny-text-secondary mt-2">
            Cliquez sur la bulle pour discuter avec Jenny comme un visiteur. Les messages
            envoyés ici arrivent vraiment dans vos conversations.
          </p>
        </div>
      </div>
    </Card>
  );
}
