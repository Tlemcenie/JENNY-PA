"use client";

import { useState, useEffect, useCallback, useRef, type FormEvent, type CSSProperties } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  BookOpen,
  Plus,
  Trash2,
  FileText,
  Upload,
  X,
  AlertCircle,
  Search,
  Pencil,
  Files,
  Sparkles,
  MoreHorizontal,
  Star,
} from "lucide-react";
import {
  listKnowledgeEntries,
  addKnowledgeText,
  uploadKnowledgePdf,
  uploadKnowledgeFiles,
  updateKnowledgeEntry,
  searchKnowledge,
  deleteKnowledgeEntry,
  getKnowledgeStats,
  type KnowledgeEntry,
  type KnowledgeSearchHit,
  ApiError,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { categoryLabel, sourceLabel } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SkeletonCard } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm-dialog";

const categories = ["general", "horaires", "tarifs", "faq", "politique", "services", "equipe"];

// Date courte façon design ("12 mars") — locale FR, dérivée de la vraie date.
function shortDateFr(date: string): string {
  try {
    return new Date(date).toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
  } catch {
    return "—";
  }
}

// Type affiché dans la pastille / colonne (PDF en rouge, reste en mint).
function entryTypeLabel(source: string): string {
  if (source === "pdf") return "PDF";
  if (source === "url") return "URL";
  return "TEXTE";
}

export default function KnowledgePage() {
  const { user } = useAuth();
  const businessId = user?.business_id;
  const toast = useToast();
  const confirm = useConfirm();
  const [entries, setEntries] = useState<KnowledgeEntry[]>([]);
  const [stats, setStats] = useState<{
    total_entries: number;
    total_chunks?: number;
    by_category: Record<string, number>;
    by_source?: Record<string, number>;
  } | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [formMode, setFormMode] = useState<"text" | "pdf" | "files">("text");

  // Form state
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [category, setCategory] = useState("general");
  const [file, setFile] = useState<File | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [isSaving, setIsSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);
  // Édition d'une entrée existante (#12).
  const [editingId, setEditingId] = useState<string | null>(null);
  // Recherche sémantique (#12).
  const [searchQuery, setSearchQuery] = useState("");
  const [searchHits, setSearchHits] = useState<KnowledgeSearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  // Menu ⋯ par ligne.
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  // Déclencheur d'ouverture du sélecteur de fichiers depuis la drop-zone.
  const filesInputRef = useRef<HTMLInputElement | null>(null);

  const fetchData = useCallback(async () => {
    if (!businessId) return;
    setIsLoading(true);
    setError(null);
    try {
      const [entriesData, statsData] = await Promise.all([
        listKnowledgeEntries(businessId),
        getKnowledgeStats(businessId),
      ]);
      setEntries(entriesData || []);
      setStats(statsData);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`Erreur ${err.status}: ${(err.data as { detail?: string })?.detail || err.statusText}`);
      } else {
        setError("Impossible de charger la base de connaissances.");
      }
    } finally {
      setIsLoading(false);
    }
  }, [businessId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Fermeture du menu ⋯ au clic extérieur.
  useEffect(() => {
    if (!menuOpenId) return;
    const close = () => setMenuOpenId(null);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [menuOpenId]);

  const resetForm = () => {
    setShowAddForm(false);
    setEditingId(null);
    setTitle("");
    setContent("");
    setCategory("general");
    setFile(null);
    setFiles([]);
    setFormError("");
    setFormMode("text");
  };

  const openAdd = (mode: "text" | "pdf" | "files" = "text") => {
    resetForm();
    setFormMode(mode);
    setShowAddForm(true);
  };

  // Édition d'une entrée texte existante (#12).
  const openEdit = (entry: KnowledgeEntry) => {
    setEditingId(entry.id);
    setFormMode("text");
    setTitle(entry.title || "");
    setContent(entry.content_preview || "");
    setCategory(entry.category || "general");
    setFile(null);
    setFiles([]);
    setFormError("");
    setShowAddForm(true);
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!businessId) return;
    setFormError("");
    setIsSaving(true);

    try {
      if (editingId) {
        await updateKnowledgeEntry(businessId, editingId, { title, content, category });
        toast.success("Entrée mise à jour");
      } else if (formMode === "text") {
        await addKnowledgeText(businessId, title, content, category);
        toast.success("Entrée ajoutée à la base");
      } else if (formMode === "pdf") {
        if (!file) {
          setFormError("Sélectionnez un fichier PDF");
          setIsSaving(false);
          return;
        }
        await uploadKnowledgePdf(businessId, file, title, category);
        toast.success("PDF importé");
      } else {
        // Import multi-fichiers (#13).
        if (files.length === 0) {
          setFormError("Sélectionnez au moins un fichier");
          setIsSaving(false);
          return;
        }
        const res = await uploadKnowledgeFiles(businessId, files, category);
        if (res.errors.length > 0) {
          toast.error(
            `${res.imported.length} importé(s), ${res.errors.length} en échec.`
          );
          setFormError(
            res.errors.map((er) => `${er.file} : ${er.error}`).join(" · ")
          );
          if (res.imported.length === 0) {
            setIsSaving(false);
            fetchData();
            return;
          }
        } else {
          toast.success(`${res.imported.length} fichier(s) importé(s)`);
        }
      }
      resetForm();
      fetchData();
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? (err.data as { detail?: string })?.detail || "Erreur lors de l'ajout"
          : "Impossible d'ajouter l'entrée.";
      setFormError(msg);
      toast.error(msg);
    } finally {
      setIsSaving(false);
    }
  };

  // Recherche sémantique débouncée (#12).
  useEffect(() => {
    const q = searchQuery.trim();
    if (!businessId || q.length < 2) {
      setSearchHits(null);
      return;
    }
    setSearching(true);
    const t = setTimeout(() => {
      searchKnowledge(businessId, q, 6)
        .then(setSearchHits)
        .catch(() => setSearchHits([]))
        .finally(() => setSearching(false));
    }, 350);
    return () => clearTimeout(t);
  }, [searchQuery, businessId]);

  const handleDelete = async (entryId: string) => {
    if (!businessId) return;
    setMenuOpenId(null);
    const ok = await confirm({
      title: "Supprimer cette entrée ?",
      message:
        "Jenny ne pourra plus s'appuyer sur ce contenu pour répondre. Cette action est irréversible.",
      confirmLabel: "Supprimer",
      danger: true,
    });
    if (!ok) return;
    setDeletingId(entryId);
    try {
      await deleteKnowledgeEntry(businessId, entryId);
      setEntries((prev) => prev.filter((e) => e.id !== entryId));
      toast.success("Entrée supprimée");
    } catch {
      toast.error("Impossible de supprimer l'entrée");
    } finally {
      setDeletingId(null);
    }
  };

  // ── Mapping données réelles → emplacements du design ────────────────────────
  // Comptes réels par source (le backend renvoie by_source ; repli sur les entrées).
  const sourceCounts = entries.reduce<Record<string, number>>((acc, e) => {
    acc[e.source] = (acc[e.source] || 0) + 1;
    return acc;
  }, {});
  const bySource = stats?.by_source ?? sourceCounts;
  const pdfCount = bySource["pdf"] || 0;
  const textCount = (bySource["text"] || 0) + (bySource["manual"] || 0);
  const totalSources = stats?.total_entries ?? entries.length;
  // Chunks indexés réels : total renvoyé sinon somme des chunks_count des entrées.
  const totalChunks =
    stats?.total_chunks ?? entries.reduce((s, e) => s + (e.chunks_count ?? 0), 0);
  const categoryCount = stats ? Object.keys(stats.by_category || {}).length : 0;
  // Couverture honnête : part des entrées effectivement indexées (chunks > 0).
  const indexedEntries = entries.filter((e) => (e.chunks_count ?? 0) > 0).length;
  const coverage = entries.length > 0 ? Math.round((indexedEntries / entries.length) * 100) : 0;

  const statCards: { label: string; value: string; sub: string }[] = [
    {
      label: "Sources",
      value: totalSources.toLocaleString("fr-FR"),
      sub: `${pdfCount} PDF · ${textCount} texte${textCount > 1 ? "s" : ""}`,
    },
    {
      label: "Chunks indexés",
      value: totalChunks.toLocaleString("fr-FR"),
      sub: "Vectorisés",
    },
    {
      label: "Catégories",
      value: String(categoryCount),
      sub: "Thèmes couverts",
    },
    {
      label: "Couverture",
      value: `${coverage}%`,
      sub: "Entrées indexées",
    },
  ];

  // Styles partagés de la grille de la liste (header + lignes alignés).
  const gridStyle: CSSProperties = {
    display: "grid",
    gridTemplateColumns: "2fr 110px 90px 100px 110px 52px",
    gap: 12,
    alignItems: "center",
  };

  return (
    <div className="jx h-full overflow-y-auto" style={{ background: "var(--bg)", padding: "28px 32px" }}>
      {/* Header éditorial */}
      <div style={{ display: "flex", alignItems: "flex-end", gap: 16, flexWrap: "wrap", marginBottom: 24 }}>
        <div style={{ minWidth: 0 }}>
          <h1
            className="jserif"
            style={{ fontSize: 40, lineHeight: 1, letterSpacing: "-0.02em", color: "var(--text)", margin: 0, marginBottom: 8 }}
          >
            Ce que <span style={{ fontStyle: "italic", color: "var(--coral)" }}>Jenny sait.</span>
          </h1>
          <p style={{ fontSize: 14, color: "var(--text-2)", maxWidth: 560, margin: 0 }}>
            Vos PDF, FAQ, et textes — vectorisés et utilisés en temps réel pour répondre à vos clients.
          </p>
        </div>
        <button
          type="button"
          onClick={() => openAdd("text")}
          className="jlift"
          style={{
            marginLeft: "auto",
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            height: 34,
            padding: "0 14px",
            borderRadius: "var(--r-btn)",
            fontSize: 12.5,
            fontWeight: 600,
            fontFamily: "var(--font-sans)",
            background: "var(--coral)",
            color: "#fff",
            border: "1px solid transparent",
            boxShadow: "var(--shadow-pop)",
            cursor: "pointer",
            whiteSpace: "nowrap",
          }}
        >
          <Plus style={{ width: 13, height: 13 }} />
          Ajouter une source
        </button>
      </div>

      {/* Stats row (données réelles) */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
          gap: 14,
          marginBottom: 24,
        }}
      >
        {statCards.map((s) => (
          <div key={s.label} className="jcard jlift" style={{ padding: 18 }}>
            <div
              className="jmono"
              style={{
                fontSize: 10,
                letterSpacing: "0.14em",
                textTransform: "uppercase",
                color: "var(--text-2)",
                fontWeight: 600,
                marginBottom: 8,
              }}
            >
              {s.label}
            </div>
            <div
              className="jserif"
              style={{ fontSize: 32, lineHeight: 1, marginBottom: 6, color: "var(--text)" }}
            >
              {s.value}
            </div>
            <div style={{ fontSize: 11.5, color: "var(--text-2)" }}>{s.sub}</div>
          </div>
        ))}
      </div>

      {/* Recherche sémantique (#12) */}
      <div style={{ position: "relative", marginBottom: 20 }}>
        <Search
          style={{
            position: "absolute",
            left: 14,
            top: "50%",
            transform: "translateY(-50%)",
            width: 16,
            height: 16,
            color: "var(--text-2)",
          }}
        />
        <input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Rechercher dans la base de connaissances (recherche sémantique)…"
          style={{
            width: "100%",
            height: 44,
            paddingLeft: 42,
            paddingRight: 40,
            borderRadius: "var(--r-btn)",
            background: "var(--surface)",
            border: "1px solid var(--divider)",
            fontSize: 14,
            color: "var(--text)",
            fontFamily: "var(--font-sans)",
            outline: "none",
          }}
        />
        {searchQuery && (
          <button
            type="button"
            onClick={() => setSearchQuery("")}
            aria-label="Effacer la recherche"
            style={{
              position: "absolute",
              right: 12,
              top: "50%",
              transform: "translateY(-50%)",
              background: "transparent",
              border: "none",
              color: "var(--text-2)",
              cursor: "pointer",
              display: "flex",
            }}
          >
            <X style={{ width: 16, height: 16 }} />
          </button>
        )}
      </div>

      {/* Résultats de recherche */}
      {searchHits !== null && (
        <div className="jcard" style={{ padding: 18, marginBottom: 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
            <Sparkles style={{ width: 16, height: 16, color: "var(--coral)" }} />
            <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text)" }}>
              {searching
                ? "Recherche…"
                : `${searchHits.length} résultat${searchHits.length > 1 ? "s" : ""}`}
            </span>
          </div>
          {searchHits.length === 0 && !searching ? (
            <p style={{ fontSize: 13, color: "var(--text-2)", margin: 0 }}>
              Aucun passage pertinent trouvé.
            </p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {searchHits.map((hit, i) => (
                <div
                  key={i}
                  style={{
                    padding: 12,
                    borderRadius: 12,
                    background: "var(--bg)",
                    border: "1px solid var(--divider)",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                    {hit.title && (
                      <span
                        style={{
                          fontSize: 12.5,
                          fontWeight: 600,
                          color: "var(--text)",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {hit.title}
                      </span>
                    )}
                    {hit.category && (
                      <span className="jbadge jbadge--slate">{categoryLabel(hit.category).toUpperCase()}</span>
                    )}
                    <span className="jmono" style={{ marginLeft: "auto", fontSize: 10.5, color: "var(--text-2)" }}>
                      {(hit.score * 100).toFixed(0)}%
                    </span>
                  </div>
                  <p
                    style={{
                      fontSize: 12,
                      color: "var(--text-2)",
                      margin: 0,
                      display: "-webkit-box",
                      WebkitLineClamp: 3,
                      WebkitBoxOrient: "vertical",
                      overflow: "hidden",
                    }}
                  >
                    {hit.content}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Drop zone (branchée aux vrais handlers d'import) */}
      <div
        style={{
          padding: 28,
          marginBottom: 24,
          background: "var(--surface)",
          border: "2px dashed var(--coral-light)",
          borderRadius: 16,
          display: "flex",
          alignItems: "center",
          gap: 24,
          flexWrap: "wrap",
        }}
      >
        <div
          style={{
            width: 56,
            height: 56,
            borderRadius: 14,
            background: "var(--coral-tint)",
            color: "var(--coral)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <Plus style={{ width: 24, height: 24 }} />
        </div>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 4, color: "var(--text)" }}>
            Glissez vos PDF, ou collez du texte
          </div>
          <div style={{ fontSize: 13, color: "var(--text-2)" }}>
            Jenny les lit, les découpe en chunks, et les utilise en moins de 30 secondes. Format max 50 MB par fichier.
          </div>
        </div>
        {/* Input réel multi-fichiers déclenché par « Parcourir » (#13). */}
        <input
          ref={filesInputRef}
          type="file"
          accept=".pdf,.txt,.md"
          multiple
          className="hidden"
          onChange={(e) => {
            const picked = Array.from(e.target.files || []);
            e.target.value = "";
            if (picked.length === 0) return;
            resetForm();
            setFormMode("files");
            setFiles(picked);
            setShowAddForm(true);
          }}
        />
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button
            type="button"
            onClick={() => filesInputRef.current?.click()}
            className="jlift"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              height: 36,
              padding: "0 16px",
              borderRadius: "var(--r-btn)",
              fontSize: 13,
              fontWeight: 600,
              fontFamily: "var(--font-sans)",
              background: "var(--coral)",
              color: "#fff",
              border: "1px solid transparent",
              boxShadow: "var(--shadow-pop)",
              cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            <Files style={{ width: 14, height: 14 }} />
            Parcourir mes fichiers
          </button>
          <button
            type="button"
            onClick={() => openAdd("text")}
            className="jpill"
            style={{ height: 36, fontSize: 13 }}
          >
            <FileText style={{ width: 14, height: 14 }} />
            Coller du texte
          </button>
          <button
            type="button"
            onClick={() => openAdd("pdf")}
            className="jpill"
            style={{ height: 36, fontSize: 13 }}
          >
            <Upload style={{ width: 14, height: 14 }} />
            Importer un PDF
          </button>
        </div>
      </div>

      {/* Add form modal */}
      <AnimatePresence>
        {showAddForm && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: "rgba(0,0,0,0.3)", backdropFilter: "blur(4px)" }}
            onClick={(e) => e.target === e.currentTarget && resetForm()}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="w-full max-w-lg"
              style={{
                background: "var(--surface)",
                borderRadius: 18,
                padding: 24,
                boxShadow: "var(--shadow-float)",
                border: "1px solid var(--divider)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
                <h3 style={{ fontSize: 18, fontWeight: 600, color: "var(--text)", margin: 0 }}>
                  {editingId ? "Modifier l'entrée" : "Nouvelle source"}
                </h3>
                <button
                  type="button"
                  onClick={resetForm}
                  aria-label="Fermer"
                  style={{ background: "transparent", border: "none", color: "var(--text-2)", cursor: "pointer", display: "flex" }}
                >
                  <X style={{ width: 20, height: 20 }} />
                </button>
              </div>

              {/* Mode toggle (masqué en édition : on modifie le texte) */}
              {!editingId && (
                <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
                  {([
                    { mode: "text" as const, icon: FileText, label: "Texte" },
                    { mode: "pdf" as const, icon: Upload, label: "PDF" },
                    { mode: "files" as const, icon: Files, label: "Fichiers" },
                  ]).map(({ mode, icon: Icon, label }) => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => setFormMode(mode)}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        padding: "8px 14px",
                        borderRadius: "var(--r-btn)",
                        fontSize: 13,
                        fontWeight: 600,
                        fontFamily: "var(--font-sans)",
                        cursor: "pointer",
                        border: "1px solid transparent",
                        background: formMode === mode ? "var(--coral)" : "var(--bg-tint)",
                        color: formMode === mode ? "#fff" : "var(--text-2)",
                      }}
                    >
                      <Icon style={{ width: 14, height: 14 }} />
                      {label}
                    </button>
                  ))}
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-4">
                {formMode !== "files" && (
                  <Input
                    label="Titre"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Ex: Horaires d'ouverture"
                    required
                  />
                )}

                <div className="flex flex-col gap-1.5">
                  <label className="text-sm font-medium text-jenny-text">Catégorie</label>
                  <select
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                    className="h-11 px-4 rounded-xl bg-jenny-surface border border-jenny-divider text-sm text-jenny-text focus:outline-none focus:ring-2 focus:ring-jenny-coral/30 focus:border-jenny-coral"
                  >
                    {categories.map((cat) => (
                      <option key={cat} value={cat}>{categoryLabel(cat)}</option>
                    ))}
                  </select>
                </div>

                {formMode === "text" ? (
                  <div className="flex flex-col gap-1.5">
                    <label className="text-sm font-medium text-jenny-text">Contenu</label>
                    <textarea
                      value={content}
                      onChange={(e) => setContent(e.target.value)}
                      placeholder="Le contenu que Jenny pourra utiliser..."
                      rows={5}
                      required
                      className="w-full px-4 py-3 rounded-xl bg-jenny-surface border border-jenny-divider text-sm text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:ring-2 focus:ring-jenny-coral/30 focus:border-jenny-coral resize-none"
                    />
                  </div>
                ) : formMode === "pdf" ? (
                  <div className="flex flex-col gap-1.5">
                    <label className="text-sm font-medium text-jenny-text">Fichier PDF</label>
                    <div className="border-2 border-dashed border-jenny-divider rounded-xl p-6 text-center hover:border-jenny-coral/30 transition-colors">
                      <input
                        type="file"
                        accept=".pdf"
                        onChange={(e) => setFile(e.target.files?.[0] || null)}
                        className="hidden"
                        id="pdf-upload"
                      />
                      <label htmlFor="pdf-upload" className="cursor-pointer">
                        <Upload className="w-8 h-8 text-jenny-text-secondary mx-auto mb-2" />
                        <p className="text-sm text-jenny-text-secondary">
                          {file ? file.name : "Cliquez pour sélectionner un PDF"}
                        </p>
                      </label>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col gap-1.5">
                    <label className="text-sm font-medium text-jenny-text">
                      Fichiers (PDF, .txt, .md)
                    </label>
                    <div className="border-2 border-dashed border-jenny-divider rounded-xl p-6 text-center hover:border-jenny-coral/30 transition-colors">
                      <input
                        type="file"
                        accept=".pdf,.txt,.md"
                        multiple
                        onChange={(e) => setFiles(Array.from(e.target.files || []))}
                        className="hidden"
                        id="files-upload"
                      />
                      <label htmlFor="files-upload" className="cursor-pointer">
                        <Files className="w-8 h-8 text-jenny-text-secondary mx-auto mb-2" />
                        <p className="text-sm text-jenny-text-secondary">
                          {files.length > 0
                            ? `${files.length} fichier(s) sélectionné(s)`
                            : "Cliquez pour sélectionner plusieurs fichiers"}
                        </p>
                      </label>
                    </div>
                    {files.length > 0 && (
                      <ul className="text-xs text-jenny-text-secondary space-y-0.5 max-h-24 overflow-y-auto">
                        {files.map((f) => (
                          <li key={f.name} className="truncate">
                            • {f.name}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}

                {formError && (
                  <div className="p-3 rounded-xl bg-jenny-error/10 text-jenny-error text-sm flex items-center gap-2">
                    <AlertCircle className="w-4 h-4 flex-shrink-0" />
                    {formError}
                  </div>
                )}

                <div className="flex gap-3 justify-end pt-2">
                  <Button variant="secondary" type="button" onClick={resetForm}>
                    Annuler
                  </Button>
                  <Button type="submit" isLoading={isSaving}>
                    {editingId ? "Enregistrer" : "Ajouter"}
                  </Button>
                </div>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Entries list */}
      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : error ? (
        <ErrorState message={error} onRetry={fetchData} />
      ) : entries.length === 0 ? (
        <EmptyState
          icon={<BookOpen className="w-8 h-8" />}
          title="Aucune source"
          description="Ajoutez du contenu (textes, PDFs) pour que Jenny puisse s'en servir pour répondre aux questions de vos clients."
          action={
            <Button onClick={() => openAdd("text")}>
              <Plus className="w-4 h-4" />
              Ajouter une source
            </Button>
          }
        />
      ) : (
        <div className="jcard" style={{ overflow: "visible" }}>
          {/* header row */}
          <div
            className="jmono"
            style={{
              ...gridStyle,
              padding: "14px 20px",
              borderBottom: "1px solid var(--divider)",
              fontSize: 10.5,
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: "var(--text-2)",
              fontWeight: 600,
            }}
          >
            <div>Source</div>
            <div>Catégorie</div>
            <div>Type</div>
            <div>Ajouté</div>
            <div>Chunks</div>
            <div />
          </div>

          <AnimatePresence initial={false}>
            {entries.map((entry, i) => {
              const type = entryTypeLabel(entry.source);
              const isPdf = entry.source === "pdf";
              const chunks = entry.chunks_count ?? 0;
              const isEditable = entry.source === "text" || entry.source === "manual";
              return (
                <motion.div
                  key={entry.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, x: -20 }}
                  transition={{ delay: i * 0.02 }}
                  style={{
                    ...gridStyle,
                    padding: "14px 20px",
                    borderBottom: i < entries.length - 1 ? "1px solid var(--divider-soft)" : "none",
                  }}
                >
                  {/* Source : pastille type + titre + sous-titre chunks */}
                  <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                    <div
                      className="jmono"
                      style={{
                        width: 34,
                        height: 34,
                        borderRadius: 9,
                        flexShrink: 0,
                        background: isPdf ? "#FEE2E2" : "var(--mint)",
                        color: isPdf ? "#991B1B" : "#1F6A47",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: 9.5,
                        fontWeight: 700,
                      }}
                    >
                      {type}
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <div
                        style={{
                          fontSize: 13.5,
                          fontWeight: 600,
                          color: "var(--text)",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                        title={entry.title}
                      >
                        {entry.title}
                      </div>
                      <div className="jmono" style={{ fontSize: 11, color: "var(--text-2)" }}>
                        {chunks} chunk{chunks > 1 ? "s" : ""}
                      </div>
                    </div>
                  </div>

                  {/* Catégorie */}
                  <div style={{ minWidth: 0 }}>
                    <span className="jbadge jbadge--slate">{categoryLabel(entry.category).toUpperCase()}</span>
                  </div>

                  {/* Type */}
                  <div className="jmono" style={{ fontSize: 12, color: "var(--text-2)" }}>
                    {sourceLabel(entry.source)}
                  </div>

                  {/* Ajouté */}
                  <div style={{ fontSize: 12, color: "var(--text-2)" }}>{shortDateFr(entry.created_at)}</div>

                  {/* Chunks (métrique réelle ; avertissement honnête si non indexé) */}
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span
                      className="jmono"
                      style={{
                        fontSize: 12.5,
                        fontWeight: 600,
                        color: chunks > 0 ? "var(--text)" : "var(--text-3)",
                      }}
                    >
                      {chunks}
                    </span>
                    {chunks > 20 && <Star style={{ width: 11, height: 11, color: "var(--coral)" }} fill="currentColor" />}
                    {chunks === 0 && (
                      <span
                        className="jmono"
                        style={{ fontSize: 9.5, color: "var(--warning)", letterSpacing: "0.06em" }}
                      >
                        NON INDEXÉ
                      </span>
                    )}
                  </div>

                  {/* Menu ⋯ (édition / suppression réelles) */}
                  <div style={{ display: "flex", justifyContent: "flex-end", position: "relative" }}>
                    {deletingId === entry.id ? (
                      <Trash2 className="animate-spin" style={{ width: 16, height: 16, color: "var(--text-3)" }} />
                    ) : (
                      <button
                        type="button"
                        aria-label="Actions"
                        onClick={(e) => {
                          e.stopPropagation();
                          setMenuOpenId((cur) => (cur === entry.id ? null : entry.id));
                        }}
                        style={{
                          background: "transparent",
                          border: "none",
                          color: "var(--text-3)",
                          cursor: "pointer",
                          display: "flex",
                          padding: 4,
                          borderRadius: 8,
                        }}
                      >
                        <MoreHorizontal style={{ width: 18, height: 18 }} />
                      </button>
                    )}
                    {menuOpenId === entry.id && (
                      <div
                        onClick={(e) => e.stopPropagation()}
                        style={{
                          position: "absolute",
                          top: "100%",
                          right: 0,
                          marginTop: 6,
                          minWidth: 168,
                          background: "var(--surface)",
                          border: "1px solid var(--divider)",
                          borderRadius: 12,
                          boxShadow: "var(--shadow-float)",
                          padding: 6,
                          zIndex: 20,
                        }}
                      >
                        {isEditable && (
                          <button
                            type="button"
                            onClick={() => {
                              setMenuOpenId(null);
                              openEdit(entry);
                            }}
                            style={{
                              width: "100%",
                              display: "flex",
                              alignItems: "center",
                              gap: 8,
                              padding: "8px 10px",
                              borderRadius: 8,
                              fontSize: 13,
                              color: "var(--text)",
                              background: "transparent",
                              border: "none",
                              cursor: "pointer",
                              textAlign: "left",
                            }}
                          >
                            <Pencil style={{ width: 14, height: 14 }} />
                            Modifier
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => handleDelete(entry.id)}
                          style={{
                            width: "100%",
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                            padding: "8px 10px",
                            borderRadius: 8,
                            fontSize: 13,
                            color: "var(--error)",
                            background: "transparent",
                            border: "none",
                            cursor: "pointer",
                            textAlign: "left",
                          }}
                        >
                          <Trash2 style={{ width: 14, height: 14 }} />
                          Supprimer
                        </button>
                      </div>
                    )}
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}
