"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Check, ChevronRight, Loader2, X } from "lucide-react";
import {
  getBusiness,
  humanError,
  listChannels,
  listPrestations,
  seedCoiffeurTemplate,
} from "@/lib/api";

/** mise en route, depuis les vraies données */

interface SetupState {
  prestations: number;
  hours: boolean;
  tone: boolean;
  channel: boolean;
}

const HIDE_KEY = "jenny-setup-hidden";

async function loadSetup(): Promise<SetupState> {
  const [biz, presta, channels] = await Promise.all([
    getBusiness(),
    listPrestations(),
    listChannels(),
  ]);
  const hours = Object.values(biz.business_hours ?? {}).some((v) => Array.isArray(v));
  return {
    prestations: presta.total ?? presta.prestations.length,
    hours,
    tone: Boolean(biz.persona?.tone),
    channel: channels.some((c) => c.connected && !c.builtin),
  };
}

export function SetupChecklist({
  knowledgeEntries,
  onChanged,
}: {
  knowledgeEntries: number;
  onChanged?: () => void;
}) {
  const [state, setState] = useState<SetupState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hidden, setHidden] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [seedMsg, setSeedMsg] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      setState(await loadSetup());
    } catch (err) {
      setError(humanError(err, "Impossible de vérifier la configuration."));
    }
  }, []);

  useEffect(() => {
    try {
      if (localStorage.getItem(HIDE_KEY) === "1") setHidden(true);
    } catch {
      // stockage bloqué
    }
    void refresh();
  }, [refresh]);

  const hide = () => {
    setHidden(true);
    try {
      localStorage.setItem(HIDE_KEY, "1");
    } catch {
      // tant pis
    }
  };

  // catalogue type coiffeur
  const seed = async () => {
    setSeeding(true);
    setSeedMsg(null);
    try {
      const r = await seedCoiffeurTemplate();
      const kbNote =
        r.knowledge > 0
          ? ` ${r.knowledge} fiches génériques ajoutées à la base (horaires, annulation) : relisez-les.`
          : "";
      setSeedMsg(
        r.prestations > 0
          ? `${r.prestations} prestations ajoutées, à ajuster dans Prestations.${kbNote}`
          : `Vous aviez déjà des prestations : rien n'a été dupliqué.${kbNote}`
      );
      await refresh();
      onChanged?.();
    } catch (err) {
      setSeedMsg(humanError(err, "Le modèle n'a pas pu être chargé."));
    } finally {
      setSeeding(false);
    }
  };

  if (hidden) return null;

  if (error) {
    return (
      <div className="jcard" style={{ padding: 16, marginBottom: 20, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontSize: 13, color: "var(--text-2)", flex: 1, minWidth: 200 }}>{error}</span>
        <button type="button" className="jpill" onClick={() => void refresh()}>
          Réessayer
        </button>
      </div>
    );
  }

  if (!state) return null;

  const steps: { id: string; label: string; done: boolean; href: string; cta: string }[] = [
    {
      id: "prestations",
      label: state.prestations > 0 ? `${state.prestations} prestations au catalogue` : "Ajouter vos prestations et tarifs",
      done: state.prestations > 0,
      href: "/prestations",
      cta: "Saisir",
    },
    { id: "hours", label: "Indiquer vos horaires d'ouverture", done: state.hours, href: "/profile", cta: "Renseigner" },
    {
      id: "knowledge",
      label: knowledgeEntries > 0 ? `${knowledgeEntries} fiches dans la base` : "Remplir la base de connaissances",
      done: knowledgeEntries > 0,
      href: "/knowledge",
      cta: "Ajouter",
    },
    { id: "tone", label: "Choisir le ton de Jenny", done: state.tone, href: "/brain", cta: "Choisir" },
    { id: "channel", label: "Connecter WhatsApp, Instagram ou e-mail", done: state.channel, href: "/channels", cta: "Connecter" },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  if (doneCount === steps.length) return null;

  return (
    <section className="jcard" style={{ padding: 20, marginBottom: 24 }} aria-label="Mise en route">
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6, flexWrap: "wrap" }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text)" }}>Mise en route de Jenny</span>
        <span className="jmono" style={{ fontSize: 11, color: "var(--text-2)" }}>
          {doneCount}/{steps.length}
        </span>
        <button
          type="button"
          onClick={hide}
          aria-label="Masquer la mise en route"
          style={{ marginLeft: "auto", color: "var(--text-2)", background: "transparent", border: "none", cursor: "pointer", padding: 4 }}
        >
          <X style={{ width: 15, height: 15 }} />
        </button>
      </div>
      <div
        style={{ height: 4, background: "var(--divider-soft)", borderRadius: 2, overflow: "hidden", marginBottom: 14 }}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={steps.length}
        aria-valuenow={doneCount}
      >
        <div
          style={{
            width: `${(doneCount / steps.length) * 100}%`,
            height: "100%",
            background: "var(--coral)",
            transition: "width 0.5s ease",
          }}
        />
      </div>
      <ul style={{ display: "flex", flexDirection: "column", gap: 8, listStyle: "none", margin: 0, padding: 0 }}>
        {steps.map((s) => (
          <li key={s.id} style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span
              style={{
                width: 20,
                height: 20,
                borderRadius: "50%",
                flexShrink: 0,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                background: s.done ? "var(--success)" : "transparent",
                border: s.done ? "none" : "1.5px solid var(--divider)",
                color: "#fff",
              }}
            >
              {s.done && <Check style={{ width: 12, height: 12 }} />}
            </span>
            <span
              style={{
                fontSize: 13,
                flex: 1,
                minWidth: 160,
                color: s.done ? "var(--text-2)" : "var(--text)",
                textDecoration: s.done ? "line-through" : "none",
              }}
            >
              {s.label}
            </span>
            {!s.done && s.id === "prestations" && (
              <button type="button" className="jpill" onClick={seed} disabled={seeding}>
                {seeding && <Loader2 className="animate-spin" style={{ width: 12, height: 12 }} />}
                Charger le modèle coiffeur
              </button>
            )}
            {!s.done && (
              <Link
                href={s.href}
                style={{ fontSize: 12.5, fontWeight: 600, color: "var(--coral)", display: "inline-flex", alignItems: "center", gap: 2, textDecoration: "none" }}
              >
                {s.cta}
                <ChevronRight style={{ width: 13, height: 13 }} />
              </Link>
            )}
          </li>
        ))}
      </ul>
      {seedMsg && (
        <p role="status" style={{ fontSize: 12.5, color: "var(--text-2)", marginTop: 10 }}>
          {seedMsg}
        </p>
      )}
    </section>
  );
}
