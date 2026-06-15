"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  X,
  Mail,
  Phone,
  AtSign,
  MessageSquare,
  ShoppingBag,
  CreditCard,
  LifeBuoy,
  Tag as TagIcon,
  Plus,
  Save,
  Wallet,
  Pencil,
  CalendarPlus,
  CalendarClock,
  Download,
  ShieldCheck,
  Eraser,
} from "lucide-react";
import { format } from "date-fns";
import { fr } from "date-fns/locale";
import {
  getCustomer360,
  updateCustomer,
  listAppointments,
  exportCustomerData,
  anonymizeCustomer,
  type Customer360,
  type Appointment,
} from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Avatar } from "@/components/ui/avatar";
import { RelativeTime } from "@/components/ui/relative-time";
import { CopyButton } from "@/components/ui/copy-button";
import { ActivityTimeline } from "@/components/customer/activity-timeline";
import { ScheduleAppointmentDialog } from "@/components/customer/schedule-appointment-dialog";
import { useFocusTrap } from "@/lib/use-focus-trap";
import {
  cn,
  channelLabel,
  formatDate,
  formatMoney,
  statusLabel,
} from "@/lib/utils";
import { easeOutExpo } from "@/lib/motion";

// Pastille de statut d'un rendez-vous (aligné sur la page Calendrier).
const APPT_STATUS_META: Record<string, { label: string; className: string }> = {
  scheduled: { label: "Planifié", className: "bg-jenny-coral/12 text-jenny-coral" },
  confirmed: { label: "Confirmé", className: "bg-jenny-success/12 text-jenny-success" },
  cancelled: { label: "Annulé", className: "bg-jenny-error/12 text-jenny-error" },
  completed: { label: "Terminé", className: "bg-jenny-slate/15 text-jenny-slate" },
};

function apptStatusMeta(status: string) {
  return (
    APPT_STATUS_META[status] ?? {
      label: status,
      className: "bg-jenny-divider/60 text-jenny-text-secondary",
    }
  );
}

// Capitalise la 1ʳᵉ lettre (les libellés date-fns `fr` sont en minuscules).
function cap(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

interface StatPillProps {
  icon: React.ReactNode;
  label: string;
  value: string;
}

function StatPill({ icon, label, value }: StatPillProps) {
  return (
    <div className="flex flex-col gap-1 rounded-xl bg-jenny-bg border border-jenny-divider px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-jenny-text-secondary text-[11px] font-medium">
        {icon}
        {label}
      </div>
      <div className="text-jenny-text font-semibold text-sm tabular-nums">{value}</div>
    </div>
  );
}

function Section({
  icon,
  title,
  count,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  if (count === 0) return null;
  return (
    <div>
      <div className="flex items-center gap-2 mb-2 text-jenny-text-secondary">
        {icon}
        <h3 className="text-xs font-semibold uppercase tracking-wide">{title}</h3>
        <span className="text-[11px] bg-jenny-divider/60 rounded-full px-1.5 py-0.5 tabular-nums">
          {count}
        </span>
      </div>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

interface CustomerPanelProps {
  customerId: string | null;
  onClose: () => void;
  onOpenConversation?: (conversationId: string) => void;
}

export function CustomerPanel({ customerId, onClose, onOpenConversation }: CustomerPanelProps) {
  const toast = useToast();
  const [data, setData] = useState<Customer360 | null>(null);
  const [loading, setLoading] = useState(false);
  const [notes, setNotes] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const panelRef = useRef<HTMLElement>(null);
  useFocusTrap(customerId !== null, panelRef);

  // Rendez-vous du client (#34) — chargés et filtrés côté client par customer_id.
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [apptLoading, setApptLoading] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);

  // RGPD — export & anonymisation. La confirmation se fait en deux temps (clic
  // « Anonymiser » → état « Confirmer ? » inline) car l'action est irréversible.
  const [exporting, setExporting] = useState(false);
  const [anonymizing, setAnonymizing] = useState(false);
  const [confirmAnonymize, setConfirmAnonymize] = useState(false);

  const loadAppointments = useCallback(async (id: string) => {
    setApptLoading(true);
    try {
      const { appointments: all } = await listAppointments({ limit: 500 });
      setAppointments(
        all
          .filter((a) => a.customer_id === id)
          .sort((a, b) => +new Date(a.start_at) - +new Date(b.start_at))
      );
    } catch {
      // silencieux : l'absence de RDV ne doit pas bloquer la fiche
      setAppointments([]);
    } finally {
      setApptLoading(false);
    }
  }, []);

  const load = useCallback(async (id: string) => {
    setLoading(true);
    try {
      const c = await getCustomer360(id);
      setData(c);
      setNotes(c.notes ?? "");
      setTags(c.tags);
      setFullName(c.full_name ?? "");
      setEmail(c.email ?? "");
      setPhone(c.phone ?? "");
      setEditing(false);
    } catch {
      toast.error("Impossible de charger la fiche client.");
      onClose();
    } finally {
      setLoading(false);
    }
  }, [toast, onClose]);

  useEffect(() => {
    setConfirmAnonymize(false);
    if (customerId) {
      void load(customerId);
      void loadAppointments(customerId);
    } else {
      setData(null);
      setAppointments([]);
    }
  }, [customerId, load, loadAppointments]);

  // Fermeture au clavier (Échap).
  useEffect(() => {
    if (!customerId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [customerId, onClose]);

  const dirty = data
    ? notes !== (data.notes ?? "") ||
      tags.join("|") !== data.tags.join("|") ||
      fullName !== (data.full_name ?? "") ||
      email !== (data.email ?? "") ||
      phone !== (data.phone ?? "")
    : false;

  const addTag = () => {
    const t = tagInput.trim();
    if (t && !tags.includes(t)) setTags((prev) => [...prev, t]);
    setTagInput("");
  };

  const save = async () => {
    if (!data) return;
    setSaving(true);
    try {
      await updateCustomer(data.id, {
        notes,
        tags,
        full_name: fullName.trim() || null,
        email: email.trim() || null,
        phone: phone.trim() || null,
      });
      setData((d) =>
        d
          ? { ...d, notes, tags, full_name: fullName.trim() || null, email: email.trim() || null, phone: phone.trim() || null }
          : d
      );
      setEditing(false);
      toast.success("Fiche client mise à jour.");
    } catch {
      toast.error("Échec de l'enregistrement.");
    } finally {
      setSaving(false);
    }
  };

  // ── RGPD : export des données (téléchargement JSON authentifié) ──
  const handleExport = async () => {
    if (!data || exporting) return;
    setExporting(true);
    try {
      await exportCustomerData(data.id);
      toast.success("Export des données lancé.");
    } catch {
      toast.error("Export impossible.");
    } finally {
      setExporting(false);
    }
  };

  // ── RGPD : anonymisation (irréversible, confirmée en deux temps) ──
  const handleAnonymize = async () => {
    if (!data || anonymizing) return;
    setAnonymizing(true);
    try {
      const res = await anonymizeCustomer(data.id);
      if (res.already_anonymized) {
        toast.info("Ce client est déjà anonymisé.");
      } else {
        toast.success("Données anonymisées.");
      }
      setConfirmAnonymize(false);
      onClose();
    } catch {
      toast.error("Anonymisation impossible.");
    } finally {
      setAnonymizing(false);
    }
  };

  const open = customerId !== null;

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Voile */}
          <motion.div
            className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
          />
          {/* Tiroir */}
          <motion.aside
            ref={panelRef}
            className="fixed right-0 top-0 z-50 h-full w-full max-w-[440px] bg-jenny-surface border-l border-jenny-divider shadow-2xl flex flex-col"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ duration: 0.32, ease: easeOutExpo }}
            role="dialog"
            aria-label="Fiche client"
          >
            {/* En-tête */}
            <div className="flex items-start justify-between p-5 border-b border-jenny-divider">
              <div className="flex items-center gap-3 min-w-0">
                {data ? (
                  <Avatar name={data.full_name} email={data.email} size="lg" />
                ) : (
                  <span className="w-12 h-12 rounded-2xl bg-jenny-divider/50 flex items-center justify-center text-jenny-text-secondary shrink-0">
                    …
                  </span>
                )}
                <div className="min-w-0">
                  <h2 className="text-jenny-text font-semibold truncate">
                    {data?.full_name || "Client"}
                  </h2>
                  {data?.created_at && (
                    <p className="text-jenny-text-secondary text-xs">
                      Client depuis {formatDate(data.created_at)}
                    </p>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                {data && (
                  <button
                    onClick={() => setEditing((v) => !v)}
                    aria-label="Modifier la fiche"
                    title="Modifier les coordonnées"
                    className={cn(
                      "p-1.5 rounded-lg transition-colors",
                      editing
                        ? "text-jenny-coral bg-jenny-coral/10"
                        : "text-jenny-text-secondary hover:text-jenny-text hover:bg-jenny-divider/40"
                    )}
                  >
                    <Pencil className="w-4 h-4" />
                  </button>
                )}
                <button
                  onClick={onClose}
                  aria-label="Fermer la fiche"
                  className="p-1.5 rounded-lg text-jenny-text-secondary hover:text-jenny-text hover:bg-jenny-divider/40 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-5 space-y-5">
              {loading && !data ? (
                <div className="space-y-3 animate-pulse">
                  <div className="h-20 bg-jenny-divider/50 rounded-xl" />
                  <div className="grid grid-cols-3 gap-2">
                    <div className="h-16 bg-jenny-divider/50 rounded-xl" />
                    <div className="h-16 bg-jenny-divider/50 rounded-xl" />
                    <div className="h-16 bg-jenny-divider/50 rounded-xl" />
                  </div>
                  <div className="h-24 bg-jenny-divider/50 rounded-xl" />
                </div>
              ) : data ? (
                <>
                  {/* Coordonnées */}
                  {editing ? (
                    <div className="space-y-2">
                      <input
                        value={fullName}
                        onChange={(e) => setFullName(e.target.value)}
                        placeholder="Nom complet"
                        className="w-full h-9 px-3 text-sm rounded-lg bg-jenny-bg border border-jenny-divider text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:border-jenny-coral/50"
                      />
                      <div className="flex items-center gap-2">
                        <Mail className="w-4 h-4 text-jenny-text-secondary shrink-0" />
                        <input
                          value={email}
                          onChange={(e) => setEmail(e.target.value)}
                          type="email"
                          placeholder="Email"
                          className="flex-1 h-9 px-3 text-sm rounded-lg bg-jenny-bg border border-jenny-divider text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:border-jenny-coral/50"
                        />
                      </div>
                      <div className="flex items-center gap-2">
                        <Phone className="w-4 h-4 text-jenny-text-secondary shrink-0" />
                        <input
                          value={phone}
                          onChange={(e) => setPhone(e.target.value)}
                          placeholder="Téléphone"
                          className="flex-1 h-9 px-3 text-sm rounded-lg bg-jenny-bg border border-jenny-divider text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:border-jenny-coral/50"
                        />
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {data.email && (
                        <div className="group flex items-center gap-2.5 text-sm text-jenny-text">
                          <Mail className="w-4 h-4 text-jenny-text-secondary shrink-0" />
                          <a href={`mailto:${data.email}`} className="truncate hover:text-jenny-coral transition-colors">
                            {data.email}
                          </a>
                          <CopyButton value={data.email} label="Email copié" />
                        </div>
                      )}
                      {data.phone && (
                        <div className="group flex items-center gap-2.5 text-sm text-jenny-text">
                          <Phone className="w-4 h-4 text-jenny-text-secondary shrink-0" />
                          <a href={`tel:${data.phone}`} className="hover:text-jenny-coral transition-colors">
                            {data.phone}
                          </a>
                          <CopyButton value={data.phone} label="Téléphone copié" />
                        </div>
                      )}
                      {data.instagram_handle && (
                        <div className="flex items-center gap-2.5 text-sm text-jenny-text">
                          <AtSign className="w-4 h-4 text-jenny-text-secondary shrink-0" />
                          <span>@{data.instagram_handle.replace(/^@/, "")}</span>
                        </div>
                      )}
                      {!data.email && !data.phone && !data.instagram_handle && (
                        <p className="text-sm text-jenny-text-secondary italic">
                          Aucune coordonnée enregistrée.
                        </p>
                      )}
                    </div>
                  )}

                  {/* Statistiques */}
                  <div className="grid grid-cols-2 gap-2">
                    <StatPill
                      icon={<Wallet className="w-3.5 h-3.5" />}
                      label="Total dépensé"
                      value={formatMoney(data.stats.total_spent_minor, data.stats.currency)}
                    />
                    <StatPill
                      icon={<ShoppingBag className="w-3.5 h-3.5" />}
                      label="Commandes"
                      value={String(data.stats.orders)}
                    />
                    <StatPill
                      icon={<MessageSquare className="w-3.5 h-3.5" />}
                      label="Conversations"
                      value={String(data.stats.conversations)}
                    />
                    <StatPill
                      icon={<LifeBuoy className="w-3.5 h-3.5" />}
                      label="Tickets ouverts"
                      value={String(data.stats.open_tickets)}
                    />
                  </div>

                  {/* Tags */}
                  <div>
                    <div className="flex items-center gap-2 mb-2 text-jenny-text-secondary">
                      <TagIcon className="w-3.5 h-3.5" />
                      <h3 className="text-xs font-semibold uppercase tracking-wide">Tags</h3>
                    </div>
                    <div className="flex flex-wrap gap-1.5 mb-2">
                      {tags.map((t) => (
                        <span
                          key={t}
                          className="inline-flex items-center gap-1 bg-jenny-coral/10 text-jenny-coral text-xs font-medium rounded-full pl-2.5 pr-1.5 py-1"
                        >
                          {t}
                          <button
                            onClick={() => setTags((prev) => prev.filter((x) => x !== t))}
                            aria-label={`Retirer ${t}`}
                            className="hover:bg-jenny-coral/20 rounded-full p-0.5"
                          >
                            <X className="w-3 h-3" />
                          </button>
                        </span>
                      ))}
                      {tags.length === 0 && (
                        <span className="text-xs text-jenny-text-secondary italic">Aucun tag</span>
                      )}
                    </div>
                    <div className="flex gap-1.5">
                      <input
                        value={tagInput}
                        onChange={(e) => setTagInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            addTag();
                          }
                        }}
                        placeholder="Ajouter un tag…"
                        className="flex-1 h-9 px-3 text-sm rounded-lg bg-jenny-bg border border-jenny-divider text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:border-jenny-coral/50"
                      />
                      <button
                        onClick={addTag}
                        aria-label="Ajouter le tag"
                        className="h-9 w-9 flex items-center justify-center rounded-lg bg-jenny-divider/50 text-jenny-text-secondary hover:text-jenny-coral hover:bg-jenny-coral/10 transition-colors"
                      >
                        <Plus className="w-4 h-4" />
                      </button>
                    </div>
                  </div>

                  {/* Notes internes */}
                  <div>
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-jenny-text-secondary mb-2">
                      Notes internes
                    </h3>
                    <textarea
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                      placeholder="Préférences, contexte, informations utiles à l'équipe…"
                      rows={3}
                      className="w-full px-3 py-2.5 text-sm rounded-xl bg-jenny-bg border border-jenny-divider text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:border-jenny-coral/50 resize-none"
                    />
                  </div>

                  {/* Rendez-vous (#34) */}
                  <div>
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <div className="flex items-center gap-2 text-jenny-text-secondary">
                        <CalendarClock className="w-3.5 h-3.5" />
                        <h3 className="text-xs font-semibold uppercase tracking-wide">
                          Rendez-vous
                        </h3>
                        {appointments.length > 0 && (
                          <span className="text-[11px] bg-jenny-divider/60 rounded-full px-1.5 py-0.5 tabular-nums">
                            {appointments.length}
                          </span>
                        )}
                      </div>
                      <button
                        onClick={() => setScheduleOpen(true)}
                        className="flex items-center gap-1 text-[11px] font-semibold text-jenny-coral hover:text-jenny-coral-dark transition-colors"
                      >
                        <CalendarPlus className="w-3.5 h-3.5" />
                        Planifier un RDV
                      </button>
                    </div>

                    {apptLoading && appointments.length === 0 ? (
                      <div className="space-y-1.5 animate-pulse">
                        <div className="h-12 bg-jenny-divider/50 rounded-lg" />
                        <div className="h-12 bg-jenny-divider/50 rounded-lg" />
                      </div>
                    ) : appointments.length === 0 ? (
                      <p className="text-sm text-jenny-text-secondary italic">
                        Aucun rendez-vous.
                      </p>
                    ) : (
                      <div className="space-y-1.5">
                        {appointments.map((a) => {
                          const meta = apptStatusMeta(a.status);
                          return (
                            <div
                              key={a.id}
                              className="flex items-center justify-between gap-2 rounded-lg border border-jenny-divider px-3 py-2"
                            >
                              <span className="min-w-0">
                                <span className="block text-sm text-jenny-text truncate">
                                  {a.title}
                                </span>
                                <span className="flex items-center gap-1.5 text-[11px] text-jenny-text-secondary">
                                  <CalendarClock className="w-3 h-3 shrink-0" />
                                  {cap(format(new Date(a.start_at), "EEE d MMM, HH:mm", { locale: fr }))}
                                </span>
                              </span>
                              <span
                                className={cn(
                                  "text-[10px] font-semibold rounded-full px-2 py-0.5 shrink-0",
                                  meta.className
                                )}
                              >
                                {meta.label}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>

                  {/* Timeline d'activité unifiée (#9) */}
                  <ActivityTimeline data={data} onOpenConversation={onOpenConversation} />

                  {/* Conversations */}
                  <Section
                    icon={<MessageSquare className="w-3.5 h-3.5" />}
                    title="Conversations"
                    count={data.conversations.length}
                  >
                    {data.conversations.map((c) => (
                      <button
                        key={c.id}
                        onClick={() => onOpenConversation?.(c.id)}
                        className="w-full flex items-center justify-between gap-2 text-left rounded-lg border border-jenny-divider px-3 py-2 hover:border-jenny-coral/40 hover:bg-jenny-bg transition-colors"
                      >
                        <span className="flex items-center gap-2 min-w-0">
                          <span className="text-sm text-jenny-text">{channelLabel(c.channel)}</span>
                          <span className="text-xs text-jenny-text-secondary">
                            · {statusLabel(c.status)}
                          </span>
                        </span>
                        <span className="text-[11px] text-jenny-text-secondary shrink-0">
                          {c.last_message_at ? <RelativeTime date={c.last_message_at} /> : ""}
                        </span>
                      </button>
                    ))}
                  </Section>

                  {/* Commandes */}
                  <Section
                    icon={<ShoppingBag className="w-3.5 h-3.5" />}
                    title="Commandes"
                    count={data.orders.length}
                  >
                    {data.orders.map((o) => (
                      <div
                        key={o.id}
                        className="flex items-center justify-between gap-2 rounded-lg border border-jenny-divider px-3 py-2"
                      >
                        <span className="text-sm text-jenny-text truncate">
                          {o.reference || "Commande"}
                          <span className="text-xs text-jenny-text-secondary ml-1.5">
                            {statusLabel(o.status)}
                          </span>
                        </span>
                        <span className="text-sm font-medium text-jenny-text tabular-nums shrink-0">
                          {formatMoney(o.total_amount_minor, o.currency)}
                        </span>
                      </div>
                    ))}
                  </Section>

                  {/* Transactions */}
                  <Section
                    icon={<CreditCard className="w-3.5 h-3.5" />}
                    title="Transactions"
                    count={data.transactions.length}
                  >
                    {data.transactions.map((t) => (
                      <div
                        key={t.id}
                        className="flex items-center justify-between gap-2 rounded-lg border border-jenny-divider px-3 py-2"
                      >
                        <span className="min-w-0">
                          <span className="text-sm text-jenny-text">{t.label}</span>
                          <span className="block text-[11px] text-jenny-text-secondary">
                            {formatDate(t.occurred_at)} · {statusLabel(t.status)}
                          </span>
                        </span>
                        <span className="text-sm font-medium text-jenny-text tabular-nums shrink-0">
                          {formatMoney(t.amount_minor, t.currency)}
                        </span>
                      </div>
                    ))}
                  </Section>

                  {/* Tickets */}
                  <Section
                    icon={<LifeBuoy className="w-3.5 h-3.5" />}
                    title="Tickets"
                    count={data.tickets.length}
                  >
                    {data.tickets.map((t) => (
                      <div
                        key={t.id}
                        className="flex items-center justify-between gap-2 rounded-lg border border-jenny-divider px-3 py-2"
                      >
                        <span className="text-sm text-jenny-text truncate">
                          {t.subject || t.reference || "Ticket"}
                        </span>
                        <span className="text-xs text-jenny-text-secondary shrink-0">
                          {statusLabel(t.status)}
                        </span>
                      </div>
                    ))}
                  </Section>

                  {/* Données & RGPD — export + anonymisation (irréversible) */}
                  <div className="pt-2 border-t border-jenny-divider">
                    <div className="flex items-center gap-2 mb-2 text-jenny-text-secondary">
                      <ShieldCheck className="w-3.5 h-3.5" />
                      <h3 className="text-xs font-semibold uppercase tracking-wide">
                        Données &amp; RGPD
                      </h3>
                    </div>
                    <div className="space-y-1.5">
                      <button
                        onClick={handleExport}
                        disabled={exporting}
                        className="w-full flex items-center gap-2 rounded-lg border border-jenny-divider px-3 py-2 text-sm text-jenny-text hover:border-jenny-coral/40 hover:bg-jenny-bg transition-colors disabled:opacity-50"
                      >
                        {exporting ? (
                          <svg className="animate-spin h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                          </svg>
                        ) : (
                          <Download className="w-4 h-4 shrink-0 text-jenny-text-secondary" />
                        )}
                        Exporter les données
                      </button>

                      {confirmAnonymize ? (
                        <div className="rounded-lg border border-jenny-error/40 bg-jenny-error/5 px-3 py-2.5">
                          <p className="text-xs text-jenny-text-secondary mb-2.5">
                            Cette action est irréversible. Les données personnelles seront effacées.
                          </p>
                          <div className="flex items-center gap-1.5">
                            <button
                              onClick={handleAnonymize}
                              disabled={anonymizing}
                              className="flex-1 flex items-center justify-center gap-1.5 rounded-lg bg-jenny-error px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90 transition-opacity disabled:opacity-50"
                            >
                              {anonymizing ? (
                                <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24" fill="none">
                                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                                </svg>
                              ) : (
                                <Eraser className="w-3.5 h-3.5" />
                              )}
                              {anonymizing ? "Anonymisation…" : "Confirmer l'anonymisation"}
                            </button>
                            <button
                              onClick={() => setConfirmAnonymize(false)}
                              disabled={anonymizing}
                              className="rounded-lg border border-jenny-divider px-3 py-1.5 text-xs font-medium text-jenny-text-secondary hover:text-jenny-text hover:bg-jenny-bg transition-colors disabled:opacity-50"
                            >
                              Annuler
                            </button>
                          </div>
                        </div>
                      ) : (
                        <button
                          onClick={() => setConfirmAnonymize(true)}
                          className="w-full flex items-center gap-2 rounded-lg border border-jenny-error/30 px-3 py-2 text-sm text-jenny-error hover:bg-jenny-error/5 transition-colors"
                        >
                          <Eraser className="w-4 h-4 shrink-0" />
                          Anonymiser le client
                        </button>
                      )}
                    </div>
                  </div>
                </>
              ) : null}
            </div>

            {/* Barre d'enregistrement (notes + tags) */}
            <AnimatePresence>
              {dirty && (
                <motion.div
                  initial={{ y: 60, opacity: 0 }}
                  animate={{ y: 0, opacity: 1 }}
                  exit={{ y: 60, opacity: 0 }}
                  transition={{ duration: 0.2 }}
                  className="border-t border-jenny-divider p-4 bg-jenny-surface"
                >
                  <button
                    onClick={save}
                    disabled={saving}
                    className="w-full h-10 flex items-center justify-center gap-2 rounded-xl bg-jenny-coral text-white font-semibold text-sm hover:bg-jenny-coral-dark transition-colors disabled:opacity-50"
                  >
                    <Save className="w-4 h-4" />
                    {saving ? "Enregistrement…" : "Enregistrer les modifications"}
                  </button>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.aside>

          {/* Planification d'un rendez-vous depuis la fiche (#34) */}
          <ScheduleAppointmentDialog
            open={scheduleOpen}
            onClose={() => setScheduleOpen(false)}
            context={{
              customerId: data?.id ?? customerId,
              customerName: data?.full_name ?? null,
            }}
            onCreated={() => {
              if (customerId) void loadAppointments(customerId);
            }}
          />
        </>
      )}
    </AnimatePresence>
  );
}
