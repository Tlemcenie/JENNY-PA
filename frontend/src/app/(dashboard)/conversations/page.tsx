"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { motion } from "framer-motion";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  Search,
  Filter,
  ChevronDown,
  AlertTriangle,
  Inbox,
  Hash,
  RefreshCw,
  Send,
  PauseCircle,
  RotateCcw,
  CheckCircle2,
  Archive,
  UserRound,
  Sparkles,
  MessageSquareText,
  UserCheck,
  Tag,
  Plus,
  X,
  Download,
  Clock3,
  FileText,
  Paperclip,
  Flag,
  GitMerge,
  ArrowUpDown,
  CheckSquare,
  CalendarPlus,
  Wand2,
  Loader2,
  Check,
  HelpCircle,
} from "lucide-react";
import { isToday, isYesterday, isThisWeek, isThisMonth } from "date-fns";
import {
  listConversations,
  getConversation,
  replyToConversation,
  resumeConversation,
  copilotSuggest,
  updateConversationStatus,
  updateConversationTags,
  updateConversationPriority,
  bulkConversationAction,
  mergeConversations,
  exportConversationsCsv,
  suggestReply,
  snoozeConversation,
  summarizeConversation,
  listCannedResponses,
  listMembers,
  assignConversation,
  listPendingQuestions,
  answerPendingQuestion,
  dismissPendingQuestion,
  subscribeToConversationEvents,
  type ConversationStatus,
  type ConversationSort,
  type PriorityLevel,
  type BulkAction,
  type ConversationSummary,
  type ConversationDetail,
  type RealtimeEvent,
  type CannedResponse,
  type TeamMember,
  type CopilotSuggestion,
  type PendingQuestion,
  ApiError,
} from "@/lib/api";
import { formatDate, channelLabel, statusLabel, intentLabel, cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SkeletonCard } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { RelativeTime } from "@/components/ui/relative-time";
import { useAuth } from "@/lib/auth-context";
import { CustomerPanel } from "@/components/customer/customer-panel";
import { ScheduleAppointmentDialog } from "@/components/customer/schedule-appointment-dialog";
import { CannedManager } from "@/components/canned/canned-manager";
import { EmojiButton } from "@/components/conversations/emoji-button";
import { ConversationRow } from "@/components/conversations/conversation-row";
import { fadeInUp } from "@/lib/motion";

const channels = ["all", "whatsapp", "instagram", "email", "twitter", "form"];
const statuses = ["all", "open", "closed", "archived"];
const STATUS_LABELS: Record<string, string> = {
  all: "Tous",
  open: "Ouvertes",
  closed: "Fermées",
  archived: "Archivées",
};
const PAGE = 30;

// Priorités (#4) — ordre du plus urgent au moins urgent pour le sélecteur.
const PRIORITIES: { value: PriorityLevel; label: string; cls: string }[] = [
  { value: "critical", label: "Critique", cls: "text-jenny-error" },
  { value: "high", label: "Haute", cls: "text-jenny-warning" },
  { value: "medium", label: "Normale", cls: "text-jenny-text-secondary" },
  { value: "low", label: "Basse", cls: "text-jenny-text-secondary/60" },
];

const SORTS: { value: ConversationSort; label: string }[] = [
  { value: "recent", label: "Récentes" },
  { value: "oldest", label: "Anciennes" },
  { value: "priority", label: "Priorité" },
];

// Groupe de date d'une conversation (#3) — libellé de section pour la liste.
function dateGroupLabel(dateStr: string | null): string {
  if (!dateStr) return "Plus ancien";
  const d = new Date(dateStr);
  if (isToday(d)) return "Aujourd'hui";
  if (isYesterday(d)) return "Hier";
  if (isThisWeek(d, { weekStartsOn: 1 })) return "Cette semaine";
  if (isThisMonth(d)) return "Ce mois-ci";
  return "Plus ancien";
}

// Réponses rapides proposées à l'agent (cliquables → remplissent le champ).
const QUICK_REPLIES = [
  "Bonjour ! Comment puis-je vous aider ?",
  "Je vérifie et je reviens vers vous tout de suite.",
  "Merci pour votre message !",
  "Pourriez-vous me préciser votre demande ?",
];

interface Segment {
  name: string;
  status: string;
  channel: string;
  tag: string | null;
  mineOnly: boolean;
}

function statusColor(status: string) {
  switch (status) {
    case "open":
      return "success" as const;
    case "closed":
      return "default" as const;
    default:
      return "default" as const;
  }
}

function extractError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    return `Erreur ${err.status}: ${
      (err.data as { detail?: string })?.detail || err.statusText
    }`;
  }
  return fallback;
}

export default function ConversationsPage() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedChannel, setSelectedChannel] = useState("all");
  const [selectedStatus, setSelectedStatus] = useState("all");
  const [search, setSearch] = useState("");

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [replyText, setReplyText] = useState("");
  const [sending, setSending] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [suggestVariants, setSuggestVariants] = useState<string[]>([]);
  // Co-pilote (#43) : brouillon proposé par Jenny au dernier message client.
  const [copilotBusy, setCopilotBusy] = useState(false);
  const [copilot, setCopilot] = useState<CopilotSuggestion | null>(null);
  const [typingConvId, setTypingConvId] = useState<string | null>(null);
  const [snoozeMenuOpen, setSnoozeMenuOpen] = useState(false);
  const [threadSearch, setThreadSearch] = useState("");
  const [threadSearchOpen, setThreadSearchOpen] = useState(false);
  const replyRef = useRef<HTMLTextAreaElement>(null);
  const [customerPanelId, setCustomerPanelId] = useState<string | null>(null);
  // Planification d'un RDV depuis la conversation ouverte (#27).
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [live, setLive] = useState(false);
  const { user } = useAuth();
  const confirm = useConfirm();
  const [canned, setCanned] = useState<CannedResponse[]>([]);
  const [cannedManagerOpen, setCannedManagerOpen] = useState(false);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [mineOnly, setMineOnly] = useState(false);
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [tagInput, setTagInput] = useState("");
  const [segments, setSegments] = useState<Segment[]>([]);
  // Tri + filtre priorité (#4).
  const [sortBy, setSortBy] = useState<ConversationSort>("recent");
  const [priorityFilter, setPriorityFilter] = useState<PriorityLevel | null>(null);
  // Sélection multiple (#1).
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  // Fusion (#10).
  const [mergeOpen, setMergeOpen] = useState(false);
  // Réponse rapide depuis la liste (#2).
  const [quickReplyId, setQuickReplyId] = useState<string | null>(null);
  const [quickReplyText, setQuickReplyText] = useState("");
  const [quickReplySending, setQuickReplySending] = useState(false);
  // Questions en attente de la conversation ouverte (#56) — mises de côté par
  // Jenny faute de réponse ; le coiffeur y répond ou les ignore.
  const [pendingQuestions, setPendingQuestions] = useState<PendingQuestion[]>([]);
  const [pqAnswerOpenId, setPqAnswerOpenId] = useState<string | null>(null);
  const [pqAnswerText, setPqAnswerText] = useState("");
  const [pqBusyId, setPqBusyId] = useState<string | null>(null);
  const toast = useToast();

  useEffect(() => {
    try {
      setSegments(JSON.parse(localStorage.getItem("jenny-segments") || "[]"));
    } catch {
      // ignore
    }
  }, []);

  const persistSegments = (next: Segment[]) => {
    setSegments(next);
    try {
      localStorage.setItem("jenny-segments", JSON.stringify(next));
    } catch {
      // mode privé
    }
  };

  const saveSegment = () => {
    const name = window.prompt("Nom du segment (filtre enregistré) ?")?.trim();
    if (!name) return;
    const seg: Segment = {
      name,
      status: selectedStatus,
      channel: selectedChannel,
      tag: tagFilter,
      mineOnly,
    };
    persistSegments([...segments.filter((s) => s.name !== name), seg]);
    toast.success("Segment enregistré.");
  };

  const applySegment = (s: Segment) => {
    setSelectedStatus(s.status);
    setSelectedChannel(s.channel);
    setTagFilter(s.tag);
    setMineOnly(s.mineOnly);
  };

  useEffect(() => {
    listMembers().then(setMembers).catch(() => {});
  }, []);

  const loadCanned = useCallback(async () => {
    try {
      setCanned(await listCannedResponses());
    } catch {
      // silencieux : les réponses enregistrées sont un confort, pas un bloquant
    }
  }, []);

  useEffect(() => {
    void loadCanned();
  }, [loadCanned]);

  // Rafraîchissement silencieux de la liste (sans skeleton ni perte de focus),
  // déclenché par les événements temps réel ou le poll de secours.
  const silentRefresh = useCallback(async () => {
    try {
      const params: {
        status?: string;
        channel?: string;
        search?: string;
        assigned_to?: string;
        tag?: string;
        priority?: string;
        sort_by?: ConversationSort;
        limit: number;
        offset: number;
      } = { limit: PAGE, offset: 0 };
      if (selectedStatus !== "all") params.status = selectedStatus;
      if (selectedChannel !== "all") params.channel = selectedChannel;
      if (search.trim()) params.search = search.trim();
      if (mineOnly) params.assigned_to = "me";
      if (tagFilter) params.tag = tagFilter;
      if (priorityFilter) params.priority = priorityFilter;
      if (sortBy !== "recent") params.sort_by = sortBy;
      const data = await listConversations(params);
      setTotal(data.total);
      setConversations(data.conversations);
    } catch {
      // silencieux : un échec ne doit pas perturber l'écran
    }
  }, [selectedStatus, selectedChannel, search, mineOnly, tagFilter, priorityFilter, sortBy]);

  const fetchConversations = useCallback(
    async (reset = true) => {
      setIsLoading(true);
      setError(null);
      try {
        const nextOffset = reset ? 0 : offset;
        const params: {
          status?: string;
          channel?: string;
          search?: string;
          assigned_to?: string;
          tag?: string;
          priority?: string;
          sort_by?: ConversationSort;
          limit: number;
          offset: number;
        } = { limit: PAGE, offset: nextOffset };
        if (selectedStatus !== "all") params.status = selectedStatus;
        if (selectedChannel !== "all") params.channel = selectedChannel;
        if (search.trim()) params.search = search.trim();
        if (mineOnly) params.assigned_to = "me";
        if (tagFilter) params.tag = tagFilter;
        if (priorityFilter) params.priority = priorityFilter;
        if (sortBy !== "recent") params.sort_by = sortBy;

        const data = await listConversations(params);
        setTotal(data.total);
        setConversations((prev) =>
          reset ? data.conversations : [...prev, ...data.conversations]
        );
        setOffset(nextOffset + data.conversations.length);
      } catch (err) {
        setError(extractError(err, "Impossible de charger les conversations."));
      } finally {
        setIsLoading(false);
      }
    },
    [selectedStatus, selectedChannel, search, mineOnly, tagFilter, priorityFilter, sortBy, offset]
  );

  useEffect(() => {
    fetchConversations(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedStatus, selectedChannel, mineOnly, tagFilter, priorityFilter, sortBy]);

  // Recherche serveur (debounce 350 ms) : cherche dans TOUTES les conversations.
  useEffect(() => {
    const t = setTimeout(() => fetchConversations(true), 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  // Handler temps réel gardé dans une ref : capture les valeurs fraîches
  // (filtres, conversation ouverte) sans reconnecter le flux SSE à chaque rendu.
  const realtimeHandlerRef = useRef<(event: RealtimeEvent) => void>(() => {});
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  realtimeHandlerRef.current = (event: RealtimeEvent) => {
    // « processing » = Jenny génère une réponse → indicateur de frappe, pas de refetch.
    if (event.kind === "processing") {
      if (event.conversation_id && event.conversation_id === selectedId) {
        setTypingConvId(event.conversation_id);
      }
      return;
    }
    // Coalesce les rafales d'événements en un seul rafraîchissement (400 ms).
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    refreshTimerRef.current = setTimeout(() => void silentRefresh(), 400);
    // Si l'événement concerne la conversation ouverte, rafraîchir son détail
    // (et lever l'indicateur de frappe : la réponse est arrivée).
    if (event.conversation_id && event.conversation_id === selectedId) {
      setTypingConvId(null);
      getConversation(selectedId).then(setDetail).catch(() => {});
    }
  };

  // Flux temps réel (SSE) : abonnement unique au montage. Les nouveaux messages,
  // réponses et changements de statut remontent instantanément, sans polling.
  useEffect(() => {
    const unsubscribe = subscribeToConversationEvents(
      (event) => realtimeHandlerRef.current(event),
      (connected) => setLive(connected)
    );
    return () => {
      unsubscribe();
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    };
  }, []);

  // Filet de sécurité : un rafraîchissement lent (60 s) couvre une éventuelle
  // coupure du flux SSE. Bien plus léger que l'ancien poll à 15 s. On évite de
  // solliciter l'API quand l'onglet est en arrière-plan.
  useEffect(() => {
    const interval = setInterval(() => {
      if (typeof document !== "undefined" && document.hidden) return;
      void silentRefresh();
    }, 60000);
    return () => clearInterval(interval);
  }, [silentRefresh]);

  // Au retour sur l'onglet, on rattrape ce qui a pu être manqué pendant l'absence.
  useEffect(() => {
    const onVisible = () => {
      if (!document.hidden) void silentRefresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [silentRefresh]);

  const handleSelect = async (id: string) => {
    setSelectedId(id);
    setDetail(null);
    setDetailError(null);
    setSuggestVariants([]);
    setCopilot(null);
    setTypingConvId(null);
    setThreadSearch("");
    setThreadSearchOpen(false);
    // Questions en attente (#56) : on repart de zéro puis on (re)charge pour ce fil.
    setPendingQuestions([]);
    setPqAnswerOpenId(null);
    setPqAnswerText("");
    void loadPendingQuestions(id);
    // Restaure un éventuel brouillon sauvegardé pour cette conversation.
    let draft = "";
    try {
      draft = localStorage.getItem(`jenny-draft-${id}`) || "";
    } catch {
      // mode privé
    }
    setReplyText(draft);
    setDetailLoading(true);
    try {
      setDetail(await getConversation(id));
    } catch (err) {
      setDetailError(extractError(err, "Impossible de charger la conversation."));
    } finally {
      setDetailLoading(false);
    }
  };

  // Ouverture directe via ?open=<id> (depuis la fiche client, par exemple).
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("open");
    if (id) {
      handleSelect(id);
      window.history.replaceState({}, "", "/conversations"); // évite la ré-ouverture au refresh
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Ouverture depuis le centre de notifications quand on est déjà sur la page
  // (pas de remontage → on écoute un événement window dispatché par la cloche).
  useEffect(() => {
    const onOpen = (e: Event) => {
      const id = (e as CustomEvent<string>).detail;
      if (id) void handleSelect(id);
    };
    window.addEventListener("jenny:open-conversation", onOpen as EventListener);
    return () =>
      window.removeEventListener("jenny:open-conversation", onOpen as EventListener);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleReply = async () => {
    const text = replyText.trim();
    if (!detail || !text || sending) return;
    setSending(true);
    try {
      const res = await replyToConversation(detail.id, text);
      setDetail((d) =>
        d
          ? {
              ...d,
              assigned_to: res.assigned_to,
              message_count: d.message_count + 1,
              messages: [...d.messages, res.message],
            }
          : d
      );
      setReplyText("");
      setSuggestVariants([]);
      setCopilot(null);
      fetchConversations(true); // rafraîchit l'aperçu dans la liste
      toast.success(
        res.delivered ? "Réponse envoyée au client" : "Réponse enregistrée (non livrée)"
      );
    } catch (err) {
      const msg = extractError(err, "Impossible d'envoyer la réponse.");
      setDetailError(msg);
      toast.error(msg);
    } finally {
      setSending(false);
    }
  };

  const handleSuggest = async () => {
    if (!detail || suggesting) return;
    setSuggesting(true);
    try {
      const { suggestion, variants } = await suggestReply(detail.id);
      setReplyText(suggestion);
      setSuggestVariants(variants && variants.length > 1 ? variants : []);
    } catch (err) {
      toast.error(extractError(err, "Impossible de générer une suggestion."));
    } finally {
      setSuggesting(false);
    }
  };

  // Co-pilote (#43) : Jenny propose un BROUILLON de réponse au dernier message
  // ENTRANT du client. Le brouillon n'est jamais envoyé automatiquement —
  // l'agent l'insère dans le champ de réponse (« Utiliser ») puis l'édite.
  const handleCopilot = async () => {
    if (!detail || copilotBusy) return;
    // Dernier message client (direction "inbound") avec du texte.
    const lastInbound = [...detail.messages]
      .reverse()
      .find((m) => m.direction === "inbound" && (m.content || "").trim());
    if (!lastInbound) {
      toast.info("Aucun message client à qui répondre pour l'instant.");
      return;
    }
    setCopilotBusy(true);
    setCopilot(null);
    try {
      const res = await copilotSuggest({
        message: lastInbound.content,
        customer_id: detail.customer_id,
        conversation_id: detail.id,
      });
      setCopilot(res);
    } catch (err) {
      toast.error(extractError(err, "Impossible de générer un brouillon."));
    } finally {
      setCopilotBusy(false);
    }
  };

  // Insère le brouillon du co-pilote dans le champ de réponse (éditable avant envoi).
  const useCopilotDraft = () => {
    if (!copilot) return;
    setReplyText(copilot.suggestion);
    setCopilot(null);
    replyRef.current?.focus();
  };

  // Questions en attente (#56) : charge les questions ouvertes de la conversation.
  const loadPendingQuestions = useCallback(async (conversationId: string) => {
    try {
      const { questions } = await listPendingQuestions({
        conversation_id: conversationId,
        status: "open",
      });
      setPendingQuestions(questions);
    } catch {
      // silencieux : l'absence de questions en attente ne doit pas gêner l'écran
      setPendingQuestions([]);
    }
  }, []);

  // Ouvre/ferme le mini-formulaire de réponse pour une question en attente.
  const togglePendingAnswer = (id: string) => {
    setPqAnswerOpenId((cur) => (cur === id ? null : id));
    setPqAnswerText("");
  };

  // Répond à une question en attente → la retire de la liste après succès.
  const handleAnswerPending = async (id: string) => {
    const answer = pqAnswerText.trim();
    if (!answer || pqBusyId) return;
    setPqBusyId(id);
    try {
      await answerPendingQuestion(id, answer);
      setPendingQuestions((qs) => qs.filter((q) => q.id !== id));
      setPqAnswerOpenId(null);
      setPqAnswerText("");
      toast.success("Réponse enregistrée.");
    } catch (err) {
      toast.error(extractError(err, "Impossible d'enregistrer la réponse."));
    } finally {
      setPqBusyId(null);
    }
  };

  // Ignore une question en attente → la retire de la liste après succès.
  const handleDismissPending = async (id: string) => {
    if (pqBusyId) return;
    setPqBusyId(id);
    try {
      await dismissPendingQuestion(id);
      setPendingQuestions((qs) => qs.filter((q) => q.id !== id));
      if (pqAnswerOpenId === id) setPqAnswerOpenId(null);
      toast.success("Question ignorée.");
    } catch (err) {
      toast.error(extractError(err, "Impossible d'ignorer la question."));
    } finally {
      setPqBusyId(null);
    }
  };

  // Raccourcis clavier : j/k naviguent la liste, r répond, Échap ferme le détail.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || el?.isContentEditable) {
        if (e.key === "Escape") el?.blur();
        return;
      }
      if (e.key === "j" || e.key === "k") {
        if (conversations.length === 0) return;
        e.preventDefault();
        const idx = conversations.findIndex((c) => c.id === selectedId);
        const next =
          e.key === "j"
            ? Math.min(idx < 0 ? 0 : idx + 1, conversations.length - 1)
            : Math.max(idx <= 0 ? 0 : idx - 1, 0);
        const target = conversations[next];
        if (target) void handleSelect(target.id);
      } else if (e.key === "r" && selectedId) {
        e.preventDefault();
        replyRef.current?.focus();
      } else if (e.key === "Escape" && selectedId) {
        setSelectedId(null);
        setDetail(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversations, selectedId]);

  // Sauvegarde automatique du brouillon par conversation (localStorage).
  useEffect(() => {
    if (!selectedId) return;
    try {
      if (replyText) localStorage.setItem(`jenny-draft-${selectedId}`, replyText);
      else localStorage.removeItem(`jenny-draft-${selectedId}`);
    } catch {
      // mode privé
    }
  }, [replyText, selectedId]);

  const handleSnooze = async (minutes: number | null) => {
    if (!detail) return;
    try {
      await snoozeConversation(detail.id, minutes);
      fetchConversations(true);
      if (minutes) {
        toast.success("Conversation reportée.");
        setSelectedId(null);
        setDetail(null);
      } else {
        toast.success("Report annulé.");
        setDetail((d) => (d ? { ...d, snoozed_until: null } : d));
      }
    } catch (err) {
      toast.error(extractError(err, "Impossible de reporter la conversation."));
    }
  };

  const handleSummarize = async () => {
    if (!detail || summarizing) return;
    setSummarizing(true);
    try {
      const { summary } = await summarizeConversation(detail.id);
      setDetail((d) => (d ? { ...d, summary } : d));
      toast.success("Résumé généré.");
    } catch (err) {
      toast.error(extractError(err, "Impossible de générer le résumé."));
    } finally {
      setSummarizing(false);
    }
  };

  const handleResume = async () => {
    if (!detail) return;
    try {
      await resumeConversation(detail.id);
      setDetail((d) => (d ? { ...d, assigned_to: null } : d));
      toast.info("Jenny a repris la main sur ce fil");
    } catch (err) {
      const msg = extractError(err, "Impossible de rendre la main à Jenny.");
      setDetailError(msg);
      toast.error(msg);
    }
  };

  const handleStatus = async (status: ConversationStatus) => {
    if (!detail) return;
    if (status === "archived") {
      const ok = await confirm({
        title: "Archiver cette conversation ?",
        message: "Elle disparaîtra de la vue active (consultable via le filtre « Archivées »).",
        confirmLabel: "Archiver",
      });
      if (!ok) return;
    }
    const previous = detail.status;
    setDetail((d) => (d ? { ...d, status } : d)); // optimiste
    try {
      await updateConversationStatus(detail.id, status);
      fetchConversations(true);
      toast.success(
        status === "closed"
          ? "Conversation résolue"
          : status === "archived"
          ? "Conversation archivée"
          : "Conversation rouverte"
      );
    } catch (err) {
      setDetail((d) => (d ? { ...d, status: previous } : d)); // rollback
      toast.error(extractError(err, "Impossible de changer le statut."));
    }
  };

  const handleAssign = async (assignee: string | null) => {
    if (!detail) return;
    try {
      const res = await assignConversation(detail.id, assignee);
      setDetail((d) => (d ? { ...d, assigned_to: res.assigned_to } : d));
      fetchConversations(true);
      toast.success(res.assigned_to ? "Conversation attribuée" : "Conversation libérée");
    } catch (err) {
      toast.error(extractError(err, "Impossible d'attribuer la conversation."));
    }
  };

  const handleTags = async (tags: string[]) => {
    if (!detail) return;
    const previous = detail.tags;
    // Mise à jour optimiste : l'UI réagit instantanément, rollback si erreur.
    setDetail((d) => (d ? { ...d, tags } : d));
    try {
      const res = await updateConversationTags(detail.id, tags);
      setDetail((d) => (d ? { ...d, tags: res.tags } : d));
      fetchConversations(true);
    } catch (err) {
      setDetail((d) => (d ? { ...d, tags: previous } : d));
      toast.error(extractError(err, "Impossible de mettre à jour les étiquettes."));
    }
  };

  // Priorité (#4) : mise à jour optimiste avec rollback.
  const handlePriority = async (priority: PriorityLevel) => {
    if (!detail) return;
    const previous = detail.priority_level;
    setDetail((d) => (d ? { ...d, priority_level: priority } : d));
    try {
      await updateConversationPriority(detail.id, priority);
      void silentRefresh();
    } catch (err) {
      setDetail((d) => (d ? { ...d, priority_level: previous } : d));
      toast.error(extractError(err, "Impossible de changer la priorité."));
    }
  };

  // Fusion (#10) : fusionne `sourceId` dans la conversation ouverte (cible).
  const handleMerge = async (sourceId: string) => {
    if (!detail || sourceId === detail.id) return;
    try {
      const res = await mergeConversations(detail.id, sourceId);
      setMergeOpen(false);
      toast.success(`${res.merged_messages} message(s) fusionné(s) dans ce fil.`);
      setDetail(await getConversation(detail.id));
      void silentRefresh();
    } catch (err) {
      toast.error(extractError(err, "Impossible de fusionner les conversations."));
    }
  };

  // Sélection multiple (#1).
  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const clearSelection = () => {
    setSelectedIds(new Set());
    setSelectMode(false);
  };

  const applyBulk = async (action: BulkAction, value: string | null) => {
    if (selectedIds.size === 0) return;
    setBulkBusy(true);
    try {
      const { updated } = await bulkConversationAction([...selectedIds], action, value);
      toast.success(`${updated} conversation${updated > 1 ? "s" : ""} mise${updated > 1 ? "s" : ""} à jour.`);
      clearSelection();
      await fetchConversations(true);
    } catch (err) {
      toast.error(extractError(err, "Action groupée impossible."));
    } finally {
      setBulkBusy(false);
    }
  };

  const addTag = () => {
    const t = tagInput.trim();
    if (!detail || !t) return;
    if (!detail.tags.some((x) => x.toLowerCase() === t.toLowerCase())) {
      void handleTags([...detail.tags, t]);
    }
    setTagInput("");
  };

  // Substitue les variables des réponses enregistrées ({{client}}, {{boutique}}…).
  const applyVars = (text: string): string =>
    text
      .replace(/\{\{\s*client\s*\}\}/gi, detail?.customer_name?.split(" ")[0] || "")
      .replace(/\{\{\s*nom\s*\}\}/gi, detail?.customer_name || "")
      .replace(/\{\{\s*boutique\s*\}\}/gi, user?.business_name || "");

  // La recherche est faite côté serveur (debounce) → on affiche la liste telle quelle.
  const filtered = conversations;

  // Candidats à la fusion (#10) : on privilégie les autres fils du même client,
  // sinon les autres conversations chargées (l'agent choisit lequel fusionner).
  const mergeCandidates = detail
    ? (() => {
        const same = conversations.filter(
          (c) =>
            c.id !== detail.id &&
            detail.customer_id &&
            c.customer_id === detail.customer_id
        );
        const pool =
          same.length > 0
            ? same
            : conversations.filter((c) => c.id !== detail.id);
        return pool.slice(0, 30);
      })()
    : [];

  // Callbacks stables pour la liste mémoïsée (#2) : évite de re-rendre toutes
  // les lignes quand un état sans rapport change (ex. frappe dans le composer).
  const handleSelectRef = useRef<(id: string) => void>(() => {});
  handleSelectRef.current = handleSelect;
  const onSelectRow = useCallback((id: string) => handleSelectRef.current(id), []);
  const onTagRow = useCallback((t: string) => setTagFilter(t), []);
  // Ouvre/ferme le mini-composer de réponse rapide pour une ligne (#2).
  const onQuickReplyRow = useCallback((id: string) => {
    setQuickReplyId((cur) => (cur === id ? null : id));
    setQuickReplyText("");
  }, []);

  const sendQuickReply = async (id: string) => {
    const text = quickReplyText.trim();
    if (!text || quickReplySending) return;
    setQuickReplySending(true);
    try {
      await replyToConversation(id, text);
      setQuickReplyId(null);
      setQuickReplyText("");
      toast.success("Réponse envoyée au client.");
      if (selectedId === id) {
        getConversation(id).then(setDetail).catch(() => {});
      }
      void silentRefresh();
    } catch (err) {
      toast.error(extractError(err, "Impossible d'envoyer la réponse."));
    } finally {
      setQuickReplySending(false);
    }
  };

  // Virtualisation de la liste (#14) : seules les lignes visibles sont rendues.
  const listScrollRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => listScrollRef.current,
    estimateSize: () => 104,
    overscan: 8,
  });

  // Recherche locale dans le fil de la conversation ouverte (#16).
  const threadMessages = detail
    ? threadSearch.trim()
      ? detail.messages.filter((m) =>
          (m.content || "").toLowerCase().includes(threadSearch.trim().toLowerCase())
        )
      : detail.messages
    : [];

  const hasMore = conversations.length < total;
  const awaitingCount = conversations.filter((c) => c.awaiting_reply).length;
  const overdueCount = conversations.filter((c) => c.overdue).length;

  return (
    <div className="h-full flex">
      {/* Liste */}
      <div
        className={cn(
          "relative flex-col border-r border-jenny-divider bg-jenny-surface min-w-0",
          // Mobile : on n'affiche jamais la liste et le détail côte à côte.
          // Quand une conversation est ouverte, la liste cède la place au détail.
          selectedId ? "hidden md:flex md:w-[420px]" : "flex flex-1"
        )}
      >
        {/* Filtres */}
        <motion.div
          variants={fadeInUp}
          initial="hidden"
          animate="show"
          className="p-4 border-b border-jenny-divider space-y-3"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-jenny-text-secondary">
              {total} conversation{total > 1 ? "s" : ""}
              {awaitingCount > 0 && (
                <span className="ml-2 text-jenny-coral font-semibold">
                  · {awaitingCount} à traiter
                </span>
              )}
              {overdueCount > 0 && (
                <span className="ml-1.5 text-jenny-error font-semibold">
                  · {overdueCount} en retard
                </span>
              )}
            </span>
            <div className="flex items-center gap-2">
              <span
                className="flex items-center gap-1.5 text-[11px] font-medium"
                title={live ? "Temps réel actif" : "Reconnexion au flux…"}
              >
                <span className="relative flex w-2 h-2">
                  {live && (
                    <span className="absolute inline-flex h-full w-full rounded-full bg-jenny-success opacity-60 animate-ping" />
                  )}
                  <span
                    className={cn(
                      "relative inline-flex w-2 h-2 rounded-full",
                      live ? "bg-jenny-success" : "bg-jenny-warning animate-pulse"
                    )}
                  />
                </span>
                <span
                  className={cn(
                    "hidden sm:inline",
                    live ? "text-jenny-success" : "text-jenny-text-secondary"
                  )}
                >
                  {live ? "En direct" : "Hors ligne"}
                </span>
              </span>
              <button
                onClick={() =>
                  exportConversationsCsv().catch(() => toast.error("Export impossible."))
                }
                title="Exporter en CSV"
                aria-label="Exporter les conversations en CSV"
                className="p-1.5 rounded-lg text-jenny-text-secondary hover:text-jenny-coral hover:bg-jenny-coral/10 transition-colors"
              >
                <Download className="w-4 h-4" />
              </button>
              <button
                onClick={() => fetchConversations(true)}
                disabled={isLoading}
                title="Rafraîchir"
                aria-label="Rafraîchir la liste"
                className="p-1.5 rounded-lg text-jenny-text-secondary hover:text-jenny-coral hover:bg-jenny-coral/10 disabled:opacity-50 transition-colors"
              >
                <RefreshCw className={cn("w-4 h-4", isLoading && "animate-spin")} />
              </button>
            </div>
          </div>

          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-jenny-text-secondary" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Rechercher une conversation..."
              className="w-full h-10 pl-10 pr-4 rounded-xl bg-jenny-bg border border-jenny-divider text-sm focus:outline-none focus:ring-2 focus:ring-jenny-coral/30 focus:border-jenny-coral transition-all"
            />
          </div>

          <div className="flex items-center gap-2 overflow-x-auto pb-1">
            <Filter className="w-4 h-4 text-jenny-text-secondary flex-shrink-0" />
            {channels.map((ch) => (
              <button
                key={ch}
                onClick={() => setSelectedChannel(ch)}
                className={cn(
                  "px-3 py-1 rounded-full text-xs font-medium transition-all whitespace-nowrap",
                  selectedChannel === ch
                    ? "bg-jenny-coral text-white"
                    : "bg-jenny-divider/50 text-jenny-text-secondary hover:bg-jenny-divider"
                )}
              >
                {ch === "all" ? "Tous" : channelLabel(ch)}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <ChevronDown className="w-3.5 h-3.5 text-jenny-text-secondary" />
            {statuses.map((st) => (
              <button
                key={st}
                onClick={() => setSelectedStatus(st)}
                className={cn(
                  "px-2.5 py-0.5 rounded-full text-[11px] font-medium transition-all",
                  selectedStatus === st
                    ? "bg-jenny-text text-white"
                    : "bg-jenny-divider/30 text-jenny-text-secondary hover:bg-jenny-divider"
                )}
              >
                {STATUS_LABELS[st] ?? st}
              </button>
            ))}
            <span className="w-px h-3.5 bg-jenny-divider mx-0.5" />
            <button
              onClick={() => setMineOnly((v) => !v)}
              title="Conversations qui me sont attribuées"
              className={cn(
                "flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-medium transition-all",
                mineOnly
                  ? "bg-jenny-coral text-white"
                  : "bg-jenny-divider/30 text-jenny-text-secondary hover:bg-jenny-divider"
              )}
            >
              <UserCheck className="w-3 h-3" />
              Mes conversations
            </button>
          </div>

          {/* Tri + priorité + sélection multiple (#1/#4) */}
          <div className="flex items-center gap-2 flex-wrap">
            <ArrowUpDown className="w-3.5 h-3.5 text-jenny-text-secondary flex-shrink-0" />
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as ConversationSort)}
              aria-label="Trier les conversations"
              className="text-[11px] bg-jenny-bg border border-jenny-divider rounded-lg px-2 py-0.5 text-jenny-text focus:outline-none focus:border-jenny-coral/50"
            >
              {SORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
            <span className="w-px h-3.5 bg-jenny-divider mx-0.5" />
            <Flag className="w-3.5 h-3.5 text-jenny-text-secondary flex-shrink-0" />
            <button
              onClick={() => setPriorityFilter(null)}
              className={cn(
                "px-2.5 py-0.5 rounded-full text-[11px] font-medium transition-all",
                !priorityFilter
                  ? "bg-jenny-text text-white"
                  : "bg-jenny-divider/30 text-jenny-text-secondary hover:bg-jenny-divider"
              )}
            >
              Toutes
            </button>
            {PRIORITIES.map((p) => (
              <button
                key={p.value}
                onClick={() =>
                  setPriorityFilter(priorityFilter === p.value ? null : p.value)
                }
                className={cn(
                  "px-2.5 py-0.5 rounded-full text-[11px] font-medium transition-all",
                  priorityFilter === p.value
                    ? "bg-jenny-text text-white"
                    : "bg-jenny-divider/30 text-jenny-text-secondary hover:bg-jenny-divider"
                )}
              >
                {p.label}
              </button>
            ))}
            <span className="w-px h-3.5 bg-jenny-divider mx-0.5" />
            <button
              onClick={() => {
                setSelectMode((m) => !m);
                if (selectMode) setSelectedIds(new Set());
              }}
              title="Sélection multiple"
              className={cn(
                "flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-medium transition-all",
                selectMode
                  ? "bg-jenny-coral text-white"
                  : "bg-jenny-divider/30 text-jenny-text-secondary hover:bg-jenny-divider"
              )}
            >
              <CheckSquare className="w-3 h-3" />
              Sélection
            </button>
          </div>

          {/* Segments (filtres enregistrés) */}
          <div className="flex items-center gap-1.5 flex-wrap">
            {segments.map((s) => (
              <span
                key={s.name}
                className="inline-flex items-center gap-1 bg-jenny-bg border border-jenny-divider rounded-full pl-2.5 pr-1 py-0.5 text-[11px]"
              >
                <button
                  onClick={() => applySegment(s)}
                  className="text-jenny-text-secondary hover:text-jenny-coral transition-colors"
                >
                  {s.name}
                </button>
                <button
                  onClick={() => persistSegments(segments.filter((x) => x.name !== s.name))}
                  aria-label={`Supprimer le segment ${s.name}`}
                  className="text-jenny-text-secondary/60 hover:text-jenny-error"
                >
                  <X className="w-3 h-3" />
                </button>
              </span>
            ))}
            <button
              onClick={saveSegment}
              title="Enregistrer le filtre actuel comme segment"
              className="inline-flex items-center gap-1 text-[11px] text-jenny-text-secondary hover:text-jenny-coral transition-colors"
            >
              <Plus className="w-3 h-3" />
              Segment
            </button>
          </div>
        </motion.div>

        {/* Bandeau de filtre par étiquette */}
        {tagFilter && (
          <div className="flex items-center justify-between gap-2 px-4 py-2 bg-jenny-coral/5 border-b border-jenny-divider">
            <span className="flex items-center gap-1.5 text-[11px] text-jenny-text-secondary min-w-0">
              <Tag className="w-3.5 h-3.5 text-jenny-coral flex-shrink-0" />
              Filtré par étiquette
              <span className="font-semibold text-jenny-coral truncate">{tagFilter}</span>
            </span>
            <button
              onClick={() => setTagFilter(null)}
              className="flex items-center gap-1 text-[11px] font-medium text-jenny-text-secondary hover:text-jenny-coral flex-shrink-0"
            >
              <X className="w-3 h-3" />
              Effacer
            </button>
          </div>
        )}

        {/* Liste */}
        <div ref={listScrollRef} className="flex-1 overflow-y-auto">
          {isLoading && conversations.length === 0 ? (
            <div className="p-4 space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <SkeletonCard key={i} />
              ))}
            </div>
          ) : error ? (
            <ErrorState message={error} onRetry={() => fetchConversations(true)} />
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={<Inbox className="w-8 h-8" />}
              title="Aucune conversation"
              description="Aucune conversation ne correspond aux filtres. Les échanges avec vos clients apparaîtront ici."
            />
          ) : (
            <>
              <div style={{ height: rowVirtualizer.getTotalSize(), position: "relative" }}>
                {rowVirtualizer.getVirtualItems().map((vi) => {
                  const conv = filtered[vi.index];
                  const prev = vi.index > 0 ? filtered[vi.index - 1] : null;
                  // En-tête de groupe de date (#3) — uniquement en tri
                  // chronologique (en tri par priorité, la date n'est pas l'axe).
                  const group = dateGroupLabel(conv.last_message_at || conv.created_at);
                  const showHeader =
                    sortBy !== "priority" &&
                    (vi.index === 0 ||
                      group !==
                        dateGroupLabel(prev!.last_message_at || prev!.created_at));
                  return (
                    <div
                      key={conv.id}
                      data-index={vi.index}
                      ref={rowVirtualizer.measureElement}
                      style={{
                        position: "absolute",
                        top: 0,
                        left: 0,
                        width: "100%",
                        transform: `translateY(${vi.start}px)`,
                      }}
                    >
                      {showHeader && (
                        <div className="px-4 pt-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-jenny-text-secondary/70 bg-jenny-surface">
                          {group}
                        </div>
                      )}
                      <ConversationRow
                        conv={conv}
                        selected={selectedId === conv.id}
                        onSelect={onSelectRow}
                        onTagClick={onTagRow}
                        selectable={selectMode}
                        checked={selectedIds.has(conv.id)}
                        onToggle={toggleSelect}
                        onQuickReply={selectMode ? undefined : onQuickReplyRow}
                      />
                      {quickReplyId === conv.id && (
                        <div className="px-4 pb-3 bg-jenny-coral/[0.03] border-b border-jenny-divider">
                          <textarea
                            autoFocus
                            value={quickReplyText}
                            onChange={(e) => setQuickReplyText(e.target.value)}
                            onKeyDown={(e) => {
                              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                                e.preventDefault();
                                void sendQuickReply(conv.id);
                              }
                              if (e.key === "Escape") setQuickReplyId(null);
                            }}
                            placeholder="Réponse rapide… (⌘/Ctrl + ↵ pour envoyer)"
                            rows={2}
                            className="w-full text-sm bg-jenny-surface border border-jenny-divider rounded-xl px-3 py-2 text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:border-jenny-coral/50 resize-none"
                          />
                          <div className="flex items-center justify-end gap-2 mt-1.5">
                            <button
                              onClick={() => setQuickReplyId(null)}
                              className="text-xs text-jenny-text-secondary hover:text-jenny-text"
                            >
                              Annuler
                            </button>
                            <Button
                              size="sm"
                              onClick={() => void sendQuickReply(conv.id)}
                              isLoading={quickReplySending}
                              disabled={!quickReplyText.trim()}
                            >
                              <Send className="w-3.5 h-3.5 mr-1" />
                              Envoyer
                            </Button>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>

              {hasMore && !search && (
                <div className="p-4 flex justify-center">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => fetchConversations(false)}
                    isLoading={isLoading}
                  >
                    Charger plus
                  </Button>
                </div>
              )}
            </>
          )}
        </div>

        {/* Barre d'actions groupées (#1) */}
        {selectMode && selectedIds.size > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="absolute bottom-4 left-1/2 -translate-x-1/2 z-30 flex items-center gap-2 bg-jenny-text text-white rounded-2xl shadow-xl px-3 py-2 max-w-[calc(100%-1.5rem)] overflow-x-auto"
          >
            <span className="text-xs font-semibold whitespace-nowrap">
              {selectedIds.size} sélectionnée{selectedIds.size > 1 ? "s" : ""}
            </span>
            <span className="w-px h-4 bg-white/20 flex-shrink-0" />
            <select
              disabled={bulkBusy}
              defaultValue=""
              onChange={(e) => {
                if (e.target.value) void applyBulk("priority", e.target.value);
                e.currentTarget.value = "";
              }}
              aria-label="Priorité groupée"
              className="bg-white/10 text-white text-xs rounded-lg px-2 py-1 focus:outline-none cursor-pointer"
            >
              <option value="" className="text-jenny-text">
                Priorité…
              </option>
              {PRIORITIES.map((p) => (
                <option key={p.value} value={p.value} className="text-jenny-text">
                  {p.label}
                </option>
              ))}
            </select>
            <select
              disabled={bulkBusy}
              defaultValue=""
              onChange={(e) => {
                if (e.target.value) void applyBulk("assign", e.target.value);
                e.currentTarget.value = "";
              }}
              aria-label="Attribuer en groupe"
              className="bg-white/10 text-white text-xs rounded-lg px-2 py-1 focus:outline-none cursor-pointer max-w-[120px]"
            >
              <option value="" className="text-jenny-text">
                Attribuer…
              </option>
              {members.map((m) => (
                <option key={m.user_id} value={m.email} className="text-jenny-text">
                  {m.full_name || m.email}
                </option>
              ))}
            </select>
            <button
              disabled={bulkBusy}
              onClick={() => {
                const t = window.prompt("Étiquette à ajouter aux conversations ?")?.trim();
                if (t) void applyBulk("tag_add", t);
              }}
              className="flex items-center gap-1 text-xs hover:text-jenny-coral-light transition-colors whitespace-nowrap"
            >
              <Tag className="w-3.5 h-3.5" />
              Étiqueter
            </button>
            <button
              disabled={bulkBusy}
              onClick={() => void applyBulk("status", "closed")}
              className="flex items-center gap-1 text-xs hover:text-jenny-coral-light transition-colors whitespace-nowrap"
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              Résoudre
            </button>
            <button
              disabled={bulkBusy}
              onClick={() => void applyBulk("status", "archived")}
              className="flex items-center gap-1 text-xs hover:text-jenny-coral-light transition-colors whitespace-nowrap"
            >
              <Archive className="w-3.5 h-3.5" />
              Archiver
            </button>
            <button
              onClick={clearSelection}
              aria-label="Annuler la sélection"
              className="text-white/60 hover:text-white flex-shrink-0"
            >
              <X className="w-4 h-4" />
            </button>
          </motion.div>
        )}
      </div>

      {/* Détail */}
      {selectedId && (
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          className="flex-1 flex flex-col min-w-0"
        >
          {detailLoading ? (
            <div className="p-6 space-y-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <SkeletonCard key={i} />
              ))}
            </div>
          ) : detailError ? (
            <ErrorState
              message={detailError}
              onRetry={() => handleSelect(selectedId)}
            />
          ) : detail ? (
            <>
              {/* En-tête */}
              <div className="p-5 border-b border-jenny-divider flex items-start justify-between gap-3">
                <div className="min-w-0">
                  {detail.customer_id ? (
                    <button
                      onClick={() => setCustomerPanelId(detail.customer_id)}
                      className="group flex items-center gap-1.5 text-lg font-semibold text-jenny-text hover:text-jenny-coral transition-colors max-w-full"
                      title="Voir la fiche client"
                    >
                      <span className="truncate">{detail.customer_name || "Client"}</span>
                      <UserRound className="w-4 h-4 text-jenny-text-secondary group-hover:text-jenny-coral transition-colors shrink-0" />
                    </button>
                  ) : (
                    <h2 className="text-lg font-semibold text-jenny-text truncate">
                      {detail.customer_name || "Client inconnu"}
                    </h2>
                  )}
                  <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                    <Badge variant="channel" channel={detail.channel}>
                      {channelLabel(detail.channel)}
                    </Badge>
                    <Badge variant={statusColor(detail.status)}>{statusLabel(detail.status)}</Badge>
                    {detail.is_escalated && (
                      <Badge variant="error">
                        <AlertTriangle className="w-3 h-3 mr-1" />
                        Escaladée
                      </Badge>
                    )}
                    {detail.current_intent && (
                      <Badge>
                        <Hash className="w-3 h-3 mr-1" />
                        {intentLabel(detail.current_intent)}
                      </Badge>
                    )}
                  </div>
                  <p className="text-xs text-jenny-text-secondary mt-1.5">
                    Créée le {formatDate(detail.created_at)} · {detail.message_count}{" "}
                    message{detail.message_count > 1 ? "s" : ""}
                  </p>
                  <div className="flex items-center gap-1.5 mt-2">
                    <UserCheck className="w-3.5 h-3.5 text-jenny-text-secondary flex-shrink-0" />
                    <select
                      value={detail.assigned_to ?? ""}
                      onChange={(e) => handleAssign(e.target.value || null)}
                      aria-label="Attribuer la conversation"
                      className="text-xs bg-jenny-bg border border-jenny-divider rounded-lg px-2 py-1 text-jenny-text focus:outline-none focus:border-jenny-coral/50 max-w-[200px]"
                    >
                      <option value="">Non attribuée</option>
                      {members.map((m) => (
                        <option key={m.user_id} value={m.email}>
                          {m.full_name || m.email}
                        </option>
                      ))}
                      {detail.assigned_to &&
                        !members.some((m) => m.email === detail.assigned_to) && (
                          <option value={detail.assigned_to}>{detail.assigned_to}</option>
                        )}
                    </select>
                    <Flag className="w-3.5 h-3.5 text-jenny-text-secondary flex-shrink-0 ml-1" />
                    <select
                      value={detail.priority_level}
                      onChange={(e) => void handlePriority(e.target.value as PriorityLevel)}
                      aria-label="Priorité de la conversation"
                      className="text-xs bg-jenny-bg border border-jenny-divider rounded-lg px-2 py-1 text-jenny-text focus:outline-none focus:border-jenny-coral/50"
                    >
                      {PRIORITIES.map((p) => (
                        <option key={p.value} value={p.value}>
                          {p.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  {/* Étiquettes */}
                  <div className="flex items-center gap-1.5 flex-wrap mt-2">
                    <Tag className="w-3.5 h-3.5 text-jenny-text-secondary flex-shrink-0" />
                    {detail.tags.map((t) => (
                      <span
                        key={t}
                        className="inline-flex items-center gap-1 bg-jenny-coral/10 text-jenny-coral text-[11px] font-medium rounded-full pl-2 pr-1 py-0.5"
                      >
                        {t}
                        <button
                          onClick={() => void handleTags(detail.tags.filter((x) => x !== t))}
                          aria-label={`Retirer ${t}`}
                          className="hover:bg-jenny-coral/20 rounded-full p-0.5"
                        >
                          <X className="w-2.5 h-2.5" />
                        </button>
                      </span>
                    ))}
                    <span className="inline-flex items-center">
                      <input
                        value={tagInput}
                        onChange={(e) => setTagInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            addTag();
                          }
                        }}
                        placeholder="Ajouter…"
                        className="w-20 text-[11px] bg-jenny-bg border border-jenny-divider rounded-full px-2 py-0.5 text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:border-jenny-coral/50 focus:w-28 transition-all"
                      />
                      {tagInput.trim() && (
                        <button
                          onClick={addTag}
                          aria-label="Ajouter l'étiquette"
                          className="ml-0.5 text-jenny-coral"
                        >
                          <Plus className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  {detail.status === "open" ? (
                    <>
                      <button
                        onClick={() => handleStatus("closed")}
                        className="flex items-center gap-1 text-xs font-medium text-jenny-success hover:underline underline-offset-2"
                      >
                        <CheckCircle2 className="w-4 h-4" />
                        Résoudre
                      </button>
                      <button
                        onClick={() => handleStatus("archived")}
                        title="Archiver"
                        aria-label="Archiver"
                        className="text-jenny-text-secondary hover:text-jenny-text transition-colors"
                      >
                        <Archive className="w-4 h-4" />
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => handleStatus("open")}
                      className="flex items-center gap-1 text-xs font-medium text-jenny-coral hover:underline underline-offset-2"
                    >
                      <RotateCcw className="w-4 h-4" />
                      Rouvrir
                    </button>
                  )}
                  <button
                    onClick={() => {
                      setThreadSearchOpen((o) => !o);
                      if (threadSearchOpen) setThreadSearch("");
                    }}
                    title="Rechercher dans la conversation"
                    aria-label="Rechercher dans la conversation"
                    className={cn(
                      "transition-colors",
                      threadSearchOpen
                        ? "text-jenny-coral"
                        : "text-jenny-text-secondary hover:text-jenny-coral"
                    )}
                  >
                    <Search className="w-4 h-4" />
                  </button>
                  <button
                    onClick={handleSummarize}
                    disabled={summarizing}
                    title="Résumer la conversation"
                    aria-label="Résumer la conversation"
                    className="text-jenny-text-secondary hover:text-jenny-coral transition-colors disabled:opacity-50"
                  >
                    <FileText className={cn("w-4 h-4", summarizing && "animate-pulse")} />
                  </button>
                  <button
                    onClick={() => setScheduleOpen(true)}
                    title="Planifier un rendez-vous"
                    aria-label="Planifier un rendez-vous"
                    className="text-jenny-text-secondary hover:text-jenny-coral transition-colors flex items-center"
                  >
                    <CalendarPlus className="w-4 h-4" />
                  </button>
                  <div className="relative">
                    <button
                      onClick={() => setSnoozeMenuOpen((o) => !o)}
                      title="Reporter (snooze)"
                      aria-label="Reporter la conversation"
                      className="text-jenny-text-secondary hover:text-jenny-coral transition-colors flex items-center"
                    >
                      <Clock3 className="w-4 h-4" />
                    </button>
                    {snoozeMenuOpen && (
                      <div className="absolute right-0 top-full mt-1 z-20 bg-jenny-surface border border-jenny-divider rounded-xl shadow-lg py-1 w-36">
                        {[
                          { lbl: "Dans 1 heure", min: 60 },
                          { lbl: "Dans 4 heures", min: 240 },
                          { lbl: "Demain", min: 60 * 24 },
                        ].map((opt) => (
                          <button
                            key={opt.lbl}
                            onClick={() => {
                              setSnoozeMenuOpen(false);
                              void handleSnooze(opt.min);
                            }}
                            className="w-full text-left px-3 py-1.5 text-xs text-jenny-text hover:bg-jenny-bg"
                          >
                            {opt.lbl}
                          </button>
                        ))}
                        {detail.snoozed_until && (
                          <button
                            onClick={() => {
                              setSnoozeMenuOpen(false);
                              void handleSnooze(null);
                            }}
                            className="w-full text-left px-3 py-1.5 text-xs text-jenny-coral hover:bg-jenny-bg border-t border-jenny-divider"
                          >
                            Annuler le report
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="relative">
                    <button
                      onClick={() => setMergeOpen((o) => !o)}
                      title="Fusionner une autre conversation dans celle-ci"
                      aria-label="Fusionner des conversations"
                      className="text-jenny-text-secondary hover:text-jenny-coral transition-colors flex items-center"
                    >
                      <GitMerge className="w-4 h-4" />
                    </button>
                    {mergeOpen && (
                      <div className="absolute right-0 top-full mt-1 z-20 bg-jenny-surface border border-jenny-divider rounded-xl shadow-lg py-1 w-64 max-h-72 overflow-y-auto">
                        <p className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wide text-jenny-text-secondary">
                          Fusionner dans ce fil
                        </p>
                        {mergeCandidates.length === 0 ? (
                          <p className="px-3 py-2 text-xs text-jenny-text-secondary">
                            Aucune autre conversation à fusionner.
                          </p>
                        ) : (
                          mergeCandidates.map((c) => (
                            <button
                              key={c.id}
                              onClick={() => void handleMerge(c.id)}
                              className="w-full text-left px-3 py-1.5 text-xs text-jenny-text hover:bg-jenny-bg"
                            >
                              <span className="font-medium">
                                {c.customer_name || "Client"}
                              </span>{" "}
                              <span className="text-jenny-text-secondary">
                                · {channelLabel(c.channel)} · {c.message_count} msg
                              </span>
                            </button>
                          ))
                        )}
                      </div>
                    )}
                  </div>
                  <button
                    onClick={() => {
                      setSelectedId(null);
                      setDetail(null);
                    }}
                    className="text-jenny-text-secondary hover:text-jenny-text text-sm"
                  >
                    Fermer
                  </button>
                </div>
              </div>

              {/* Barre de recherche dans le fil */}
              {threadSearchOpen && (
                <div className="px-4 py-2 border-b border-jenny-divider bg-jenny-bg/50">
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-jenny-text-secondary" />
                    <input
                      autoFocus
                      value={threadSearch}
                      onChange={(e) => setThreadSearch(e.target.value)}
                      placeholder="Rechercher dans cette conversation…"
                      className="w-full h-8 pl-9 pr-16 rounded-lg bg-jenny-surface border border-jenny-divider text-xs text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:border-jenny-coral/50"
                    />
                    {threadSearch.trim() && (
                      <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-jenny-text-secondary">
                        {threadMessages.length} résultat{threadMessages.length > 1 ? "s" : ""}
                      </span>
                    )}
                  </div>
                </div>
              )}

              {/* Fil de messages */}
              <div className="flex-1 overflow-y-auto p-6 space-y-4">
                {/* Questions en attente (#56) — Jenny les a mises de côté faute de
                    savoir répondre. Affiché uniquement s'il y en a, sans gêner le fil. */}
                {pendingQuestions.length > 0 && !threadSearch && (
                  <Card className="border-jenny-warning/30 bg-jenny-warning/[0.06] p-4">
                    <div className="flex items-center gap-2 mb-3">
                      <HelpCircle className="w-4 h-4 text-jenny-warning flex-shrink-0" />
                      <h3 className="text-xs font-semibold text-jenny-text">
                        Questions en attente
                      </h3>
                      <span className="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full bg-jenny-warning/20 text-jenny-warning text-[11px] font-semibold tabular-nums">
                        {pendingQuestions.length}
                      </span>
                    </div>
                    <ul className="space-y-2.5">
                      {pendingQuestions.map((q) => {
                        const busy = pqBusyId === q.id;
                        const answering = pqAnswerOpenId === q.id;
                        return (
                          <li
                            key={q.id}
                            className="rounded-xl border border-jenny-divider bg-jenny-surface p-3"
                          >
                            <p className="text-sm text-jenny-text whitespace-pre-wrap break-words leading-relaxed">
                              {q.question}
                            </p>
                            {answering ? (
                              <div className="mt-2">
                                <textarea
                                  autoFocus
                                  value={pqAnswerText}
                                  onChange={(e) => setPqAnswerText(e.target.value)}
                                  onKeyDown={(e) => {
                                    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                                      e.preventDefault();
                                      void handleAnswerPending(q.id);
                                    }
                                    if (e.key === "Escape") togglePendingAnswer(q.id);
                                  }}
                                  placeholder="Votre réponse… (⌘/Ctrl + ↵ pour envoyer)"
                                  rows={2}
                                  className="w-full text-sm bg-jenny-bg border border-jenny-divider rounded-lg px-3 py-2 text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:border-jenny-coral/50 resize-none"
                                />
                                <div className="flex items-center justify-end gap-2 mt-1.5">
                                  <button
                                    type="button"
                                    onClick={() => togglePendingAnswer(q.id)}
                                    className="text-xs text-jenny-text-secondary hover:text-jenny-text"
                                  >
                                    Annuler
                                  </button>
                                  <Button
                                    size="sm"
                                    onClick={() => void handleAnswerPending(q.id)}
                                    isLoading={busy}
                                    disabled={!pqAnswerText.trim()}
                                  >
                                    <Send className="w-3.5 h-3.5 mr-1" />
                                    Envoyer
                                  </Button>
                                </div>
                              </div>
                            ) : (
                              <div className="flex items-center justify-end gap-3 mt-2">
                                <button
                                  type="button"
                                  onClick={() => void handleDismissPending(q.id)}
                                  disabled={busy}
                                  className="flex items-center gap-1 text-xs font-medium text-jenny-text-secondary hover:text-jenny-text disabled:opacity-50 transition-colors"
                                >
                                  <X className="w-3.5 h-3.5" />
                                  Ignorer
                                </button>
                                <button
                                  type="button"
                                  onClick={() => togglePendingAnswer(q.id)}
                                  disabled={busy}
                                  className="flex items-center gap-1 text-xs font-medium text-jenny-coral hover:underline underline-offset-2 disabled:opacity-50 transition-colors"
                                >
                                  <MessageSquareText className="w-3.5 h-3.5" />
                                  Répondre
                                </button>
                              </div>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  </Card>
                )}

                {detail.summary && !threadSearch && (
                  <Card className="bg-jenny-mint/30 border-jenny-mint-dark/20 p-4">
                    <h3 className="text-xs font-semibold text-jenny-text-secondary mb-1">
                      Résumé
                    </h3>
                    <p className="text-sm text-jenny-text leading-relaxed">
                      {detail.summary}
                    </p>
                  </Card>
                )}

                {threadMessages.length === 0 ? (
                  <p className="text-sm text-jenny-text-secondary text-center py-8">
                    {threadSearch ? "Aucun message ne correspond." : "Aucun message dans cette conversation."}
                  </p>
                ) : (
                  threadMessages.map((m) => {
                    const outbound = m.direction === "outbound";
                    return (
                      <div
                        key={m.id}
                        className={cn("flex", outbound ? "justify-end" : "justify-start")}
                      >
                        <div
                          className={cn(
                            "max-w-[75%] rounded-2xl px-4 py-2.5",
                            outbound
                              ? "bg-brand-gradient text-white rounded-br-sm shadow-sm shadow-jenny-coral/15"
                              : "bg-jenny-surface border border-jenny-divider text-jenny-text rounded-bl-sm"
                          )}
                        >
                          <p className="text-sm whitespace-pre-wrap break-words">
                            {m.content || "(Pas de contenu)"}
                          </p>
                          {!!m.attachment_count && m.attachment_count > 0 && (
                            <span
                              className={cn(
                                "mt-1 inline-flex items-center gap-1 text-[11px]",
                                outbound ? "text-white/80" : "text-jenny-text-secondary"
                              )}
                            >
                              <Paperclip className="w-3 h-3" />
                              {m.attachment_count} pièce{m.attachment_count > 1 ? "s" : ""} jointe
                              {m.attachment_count > 1 ? "s" : ""}
                            </span>
                          )}
                          <span
                            className={cn(
                              "text-[10px] mt-1 block",
                              outbound ? "text-white/70" : "text-jenny-text-secondary"
                            )}
                          >
                            {m.sender_name ? `${m.sender_name} · ` : ""}
                            <RelativeTime date={m.created_at} />
                          </span>
                        </div>
                      </div>
                    );
                  })
                )}
                {(typingConvId === detail.id || suggesting) && (
                  <div className="flex items-center gap-2 text-xs text-jenny-text-secondary">
                    <span className="flex gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-jenny-coral animate-bounce [animation-delay:-0.2s]" />
                      <span className="w-1.5 h-1.5 rounded-full bg-jenny-coral animate-bounce [animation-delay:-0.1s]" />
                      <span className="w-1.5 h-1.5 rounded-full bg-jenny-coral animate-bounce" />
                    </span>
                    Jenny rédige…
                  </div>
                )}
              </div>

              {/* Composer de réponse (reprise humaine) */}
              <div className="border-t border-jenny-divider p-4 bg-jenny-surface">
                {detail.assigned_to && (
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <span className="flex items-center gap-1.5 text-[11px] text-jenny-text-secondary min-w-0">
                      <PauseCircle className="w-3.5 h-3.5 text-jenny-warning flex-shrink-0" />
                      <span className="truncate">
                        Repris par {detail.assigned_to} · Jenny est en pause
                      </span>
                    </span>
                    <button
                      onClick={handleResume}
                      className="flex items-center gap-1 text-[11px] font-medium text-jenny-coral hover:underline underline-offset-2 flex-shrink-0"
                    >
                      <RotateCcw className="w-3 h-3" />
                      Rendre la main à Jenny
                    </button>
                  </div>
                )}
                {suggestVariants.length > 1 && (
                  <div className="mb-2">
                    <p className="flex items-center gap-1 text-[10px] font-medium text-jenny-text-secondary mb-1">
                      <Sparkles className="w-3 h-3 text-jenny-coral" />
                      Propositions — cliquez pour choisir
                    </p>
                    <div className="flex flex-col gap-1">
                      {suggestVariants.map((v, idx) => (
                        <button
                          key={idx}
                          onClick={() => setReplyText(v)}
                          className={cn(
                            "text-left text-xs rounded-lg border px-2.5 py-1.5 transition-colors line-clamp-2",
                            replyText === v
                              ? "border-jenny-coral/50 bg-jenny-coral/5 text-jenny-text"
                              : "border-jenny-divider text-jenny-text-secondary hover:border-jenny-coral/40 hover:text-jenny-text"
                          )}
                        >
                          {v}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {copilot && (
                  <motion.div
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="mb-2 rounded-xl border border-jenny-coral/30 bg-jenny-coral/[0.04] p-3"
                  >
                    <div className="flex items-center justify-between gap-2 mb-1.5">
                      <span className="flex items-center gap-1.5 text-[11px] font-semibold text-jenny-coral">
                        <Wand2 className="w-3.5 h-3.5" />
                        Suggestion de Jenny
                      </span>
                      <button
                        type="button"
                        onClick={() => setCopilot(null)}
                        aria-label="Masquer la suggestion"
                        className="text-jenny-text-secondary/70 hover:text-jenny-text"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                    <p className="text-sm text-jenny-text whitespace-pre-wrap break-words leading-relaxed">
                      {copilot.suggestion}
                    </p>
                    {(copilot.requires_human || copilot.knowledge_gap) && (
                      <div className="flex items-center gap-1.5 flex-wrap mt-2">
                        {copilot.requires_human && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-jenny-warning/15 text-jenny-warning text-[10px] font-medium px-2 py-0.5">
                            <AlertTriangle className="w-3 h-3" />
                            à vérifier
                          </span>
                        )}
                        {copilot.knowledge_gap && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-jenny-warning/15 text-jenny-warning text-[10px] font-medium px-2 py-0.5">
                            <AlertTriangle className="w-3 h-3" />
                            info à confirmer
                          </span>
                        )}
                      </div>
                    )}
                    <div className="flex items-center justify-end gap-2 mt-2">
                      <button
                        type="button"
                        onClick={() => setCopilot(null)}
                        className="text-xs text-jenny-text-secondary hover:text-jenny-text"
                      >
                        Ignorer
                      </button>
                      <Button size="sm" onClick={useCopilotDraft}>
                        <Check className="w-3.5 h-3.5 mr-1" />
                        Utiliser
                      </Button>
                    </div>
                  </motion.div>
                )}
                {!replyText && (
                  <div className="flex items-center gap-1.5 mb-2 overflow-x-auto pb-0.5 -mx-0.5 px-0.5">
                    {(canned.length > 0
                      ? canned.map((c) => ({ key: c.id, label: c.title, value: c.content }))
                      : QUICK_REPLIES.map((q) => ({ key: q, label: q, value: q }))
                    ).map((chip) => (
                      <button
                        key={chip.key}
                        type="button"
                        onClick={() => setReplyText(applyVars(chip.value))}
                        className="px-2.5 py-1 rounded-full text-[11px] whitespace-nowrap bg-jenny-bg border border-jenny-divider text-jenny-text-secondary hover:border-jenny-coral/40 hover:text-jenny-coral transition-colors flex-shrink-0"
                      >
                        {chip.label}
                      </button>
                    ))}
                    <button
                      type="button"
                      onClick={() => setCannedManagerOpen(true)}
                      title="Gérer les réponses enregistrées"
                      className="flex items-center gap-1 px-2 py-1 rounded-full text-[11px] whitespace-nowrap bg-jenny-bg border border-dashed border-jenny-divider text-jenny-text-secondary hover:border-jenny-coral/40 hover:text-jenny-coral transition-colors flex-shrink-0"
                    >
                      <MessageSquareText className="w-3 h-3" />
                      Gérer
                    </button>
                  </div>
                )}
                <div className="flex items-end gap-2">
                  <div className="flex-1 relative">
                    <textarea
                      ref={replyRef}
                      value={replyText}
                      onChange={(e) => setReplyText(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          handleReply();
                        }
                      }}
                      placeholder="Répondre au client…"
                      rows={1}
                      maxLength={5000}
                      className="w-full resize-none px-4 py-2.5 rounded-xl bg-jenny-bg border border-jenny-divider text-sm text-jenny-text placeholder:text-jenny-text-secondary/50 focus:outline-none focus:ring-2 focus:ring-jenny-coral/30 focus:border-jenny-coral transition-all max-h-32"
                    />
                    {replyText.length > 0 && (
                      <span
                        className={cn(
                          "absolute bottom-1.5 right-3 text-[10px] tabular-nums pointer-events-none",
                          replyText.length > 4800 ? "text-jenny-error" : "text-jenny-text-secondary/50"
                        )}
                      >
                        {replyText.length}/5000
                      </span>
                    )}
                  </div>
                  <EmojiButton onPick={(emoji) => setReplyText((t) => t + emoji)} />
                  <button
                    type="button"
                    onClick={handleCopilot}
                    disabled={copilotBusy}
                    title="Demander un brouillon de réponse à Jenny (co-pilote)"
                    aria-label="Suggérer une réponse (co-pilote)"
                    className="h-9 w-9 flex items-center justify-center rounded-xl border border-jenny-divider text-jenny-coral hover:bg-jenny-coral/10 hover:border-jenny-coral/40 disabled:opacity-50 transition-colors flex-shrink-0"
                  >
                    {copilotBusy ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Wand2 className="w-4 h-4" />
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={handleSuggest}
                    disabled={suggesting}
                    title="Suggérer une réponse"
                    aria-label="Suggérer une réponse"
                    className="h-9 w-9 flex items-center justify-center rounded-xl border border-jenny-divider text-jenny-coral hover:bg-jenny-coral/10 hover:border-jenny-coral/40 disabled:opacity-50 transition-colors flex-shrink-0"
                  >
                    <Sparkles className={cn("w-4 h-4", suggesting && "animate-pulse")} />
                  </button>
                  <Button
                    onClick={handleReply}
                    isLoading={sending}
                    disabled={!replyText.trim()}
                    size="sm"
                  >
                    <Send className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            </>
          ) : null}
        </motion.div>
      )}

      {/* Fiche client 360° (tiroir) */}
      <CustomerPanel
        customerId={customerPanelId}
        onClose={() => setCustomerPanelId(null)}
        onOpenConversation={(id) => {
          setCustomerPanelId(null);
          setSelectedId(id);
        }}
      />

      {/* Gestion des réponses enregistrées */}
      <CannedManager
        open={cannedManagerOpen}
        onClose={() => setCannedManagerOpen(false)}
        onChanged={loadCanned}
      />

      {/* Planifier un RDV depuis la conversation ouverte (#27) */}
      <ScheduleAppointmentDialog
        open={scheduleOpen}
        onClose={() => setScheduleOpen(false)}
        context={{
          customerId: detail?.customer_id ?? undefined,
          conversationId: detail?.id ?? undefined,
          customerName: detail?.customer_name ?? undefined,
          defaultChannel: detail?.channel ?? undefined,
        }}
      />
    </div>
  );
}
