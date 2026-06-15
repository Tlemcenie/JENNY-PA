"use client";

import { useState, useEffect, useCallback, type FormEvent } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  BookOpen,
  Plus,
  Trash2,
  FileText,
  Upload,
  X,
  Tag,
  BarChart3,
  AlertCircle,
  Search,
  Pencil,
  Files,
  Sparkles,
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
import { formatRelativeTime, categoryLabel, sourceLabel, cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SkeletonCard } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/error-state";
import { useToast } from "@/components/ui/toast";
import { staggerContainer, staggerItem, fadeInUp, springSnappy } from "@/lib/motion";

const categories = ["general", "horaires", "tarifs", "faq", "politique", "services", "equipe"];

export default function KnowledgePage() {
  const { user } = useAuth();
  const businessId = user?.business_id;
  const toast = useToast();
  const [entries, setEntries] = useState<KnowledgeEntry[]>([]);
  const [stats, setStats] = useState<{ total_entries: number; by_category: Record<string, number> } | null>(null);
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

  const openAdd = () => {
    resetForm();
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

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto p-6 space-y-6">
        {/* Stats cards */}
        {stats && (
          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate="show"
            className="grid grid-cols-2 md:grid-cols-4 gap-3"
          >
            <motion.div variants={staggerItem} whileHover={{ y: -3 }} transition={springSnappy}>
              <Card className="p-4 h-full hover:shadow-md hover:shadow-black/[0.04] hover:border-jenny-coral/20">
                <div className="flex items-center gap-2 text-jenny-text-secondary mb-1">
                  <BarChart3 className="w-4 h-4" />
                  <span className="text-xs">Total entrées</span>
                </div>
                <p className="font-display text-2xl font-bold text-jenny-text tabular-nums">{stats.total_entries}</p>
              </Card>
            </motion.div>
            {Object.entries(stats.by_category || {}).slice(0, 3).map(([cat, count]) => (
              <motion.div key={cat} variants={staggerItem} whileHover={{ y: -3 }} transition={springSnappy}>
                <Card className="p-4 h-full hover:shadow-md hover:shadow-black/[0.04] hover:border-jenny-coral/20">
                  <div className="flex items-center gap-2 text-jenny-text-secondary mb-1">
                    <Tag className="w-4 h-4" />
                    <span className="text-xs">{categoryLabel(cat)}</span>
                  </div>
                  <p className="font-display text-2xl font-bold text-jenny-text tabular-nums">{count}</p>
                </Card>
              </motion.div>
            ))}
          </motion.div>
        )}

        {/* Header */}
        <motion.div
          variants={fadeInUp}
          initial="hidden"
          animate="show"
          className="flex items-center justify-between"
        >
          <div>
            <div className="font-mono text-[11px] tracking-[0.22em] uppercase text-jenny-coral mb-2">— le cerveau de jenny —</div>
            <h2 className="font-display text-[clamp(28px,4vw,36px)] leading-[1] tracking-[-0.02em] text-jenny-text">
              Base de <span className="italic text-jenny-coral">connaissances.</span>
            </h2>
            <p className="text-sm text-jenny-text-secondary mt-0.5">
              Gérez le contenu que Jenny utilise pour répondre aux questions
            </p>
          </div>
          <Button onClick={openAdd}>
            <Plus className="w-4 h-4" />
            Ajouter
          </Button>
        </motion.div>

        {/* Recherche sémantique (#12) */}
        <motion.div variants={fadeInUp} initial="hidden" animate="show" className="relative">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-jenny-text-secondary" />
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Rechercher dans la base de connaissances (recherche sémantique)…"
            className="w-full h-11 pl-11 pr-10 rounded-xl bg-jenny-surface border border-jenny-divider text-sm text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:ring-2 focus:ring-jenny-coral/30 focus:border-jenny-coral transition-all"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery("")}
              aria-label="Effacer la recherche"
              className="absolute right-3 top-1/2 -translate-y-1/2 text-jenny-text-secondary hover:text-jenny-coral"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </motion.div>

        {/* Résultats de recherche */}
        {searchHits !== null && (
          <Card className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <Sparkles className="w-4 h-4 text-jenny-coral" />
              <h3 className="text-sm font-semibold text-jenny-text">
                {searching
                  ? "Recherche…"
                  : `${searchHits.length} résultat${searchHits.length > 1 ? "s" : ""}`}
              </h3>
            </div>
            {searchHits.length === 0 && !searching ? (
              <p className="text-sm text-jenny-text-secondary">
                Aucun passage pertinent trouvé.
              </p>
            ) : (
              <div className="space-y-2.5">
                {searchHits.map((hit, i) => (
                  <div
                    key={i}
                    className="p-3 rounded-xl bg-jenny-bg border border-jenny-divider"
                  >
                    <div className="flex items-center gap-2 mb-1">
                      {hit.title && (
                        <span className="text-xs font-medium text-jenny-text truncate">
                          {hit.title}
                        </span>
                      )}
                      {hit.category && <Badge>{categoryLabel(hit.category)}</Badge>}
                      <span className="ml-auto text-[10px] font-mono text-jenny-text-secondary">
                        {(hit.score * 100).toFixed(0)}%
                      </span>
                    </div>
                    <p className="text-xs text-jenny-text-secondary line-clamp-3">
                      {hit.content}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </Card>
        )}

        {/* Add form modal */}
        <AnimatePresence>
          {showAddForm && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black/30 backdrop-blur-sm z-50 flex items-center justify-center p-4"
              onClick={(e) => e.target === e.currentTarget && resetForm()}
            >
              <motion.div
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.95, opacity: 0 }}
                className="bg-jenny-surface rounded-2xl p-6 w-full max-w-lg shadow-xl"
              >
                <div className="flex items-center justify-between mb-6">
                  <h3 className="text-lg font-semibold text-jenny-text">
                    {editingId ? "Modifier l'entrée" : "Nouvelle entrée"}
                  </h3>
                  <button onClick={resetForm} className="text-jenny-text-secondary hover:text-jenny-text">
                    <X className="w-5 h-5" />
                  </button>
                </div>

                {/* Mode toggle (masqué en édition : on modifie le texte) */}
                {!editingId && (
                  <div className="flex gap-2 mb-4">
                    <button
                      onClick={() => setFormMode("text")}
                      className={cn(
                        "flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all",
                        formMode === "text" ? "bg-jenny-coral text-white" : "bg-jenny-divider/50 text-jenny-text-secondary"
                      )}
                    >
                      <FileText className="w-4 h-4" />
                      Texte
                    </button>
                    <button
                      onClick={() => setFormMode("pdf")}
                      className={cn(
                        "flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all",
                        formMode === "pdf" ? "bg-jenny-coral text-white" : "bg-jenny-divider/50 text-jenny-text-secondary"
                      )}
                    >
                      <Upload className="w-4 h-4" />
                      PDF
                    </button>
                    <button
                      onClick={() => setFormMode("files")}
                      className={cn(
                        "flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all",
                        formMode === "files" ? "bg-jenny-coral text-white" : "bg-jenny-divider/50 text-jenny-text-secondary"
                      )}
                    >
                      <Files className="w-4 h-4" />
                      Fichiers
                    </button>
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
            title="Aucune entrée"
            description="Ajoutez du contenu (textes, PDFs) pour que Jenny puisse s'en servir pour répondre aux questions de vos clients."
            action={
              <Button onClick={openAdd}>
                <Plus className="w-4 h-4" />
                Ajouter une entrée
              </Button>
            }
          />
        ) : (
          <div className="grid gap-3">
            <AnimatePresence>
              {entries.map((entry, i) => (
                <motion.div
                  key={entry.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, x: -20 }}
                  transition={{ delay: i * 0.03 }}
                >
                  <Card className="flex items-start gap-4 p-4">
                    <div className="w-10 h-10 rounded-xl bg-jenny-mint flex items-center justify-center flex-shrink-0">
                      <FileText className="w-5 h-5 text-jenny-coral" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <h4 className="font-medium text-sm text-jenny-text truncate">{entry.title}</h4>
                        <Badge>{categoryLabel(entry.category)}</Badge>
                        <Badge variant="default">{sourceLabel(entry.source)}</Badge>
                      </div>
                      {entry.content_preview && (
                        <p className="text-xs text-jenny-text-secondary line-clamp-2">{entry.content_preview}</p>
                      )}
                      <span className="text-[10px] text-jenny-text-secondary/60 mt-1 block">
                        {formatRelativeTime(entry.created_at)}
                      </span>
                    </div>
                    <div className="flex items-center gap-1 flex-shrink-0">
                      {entry.source === "text" && (
                        <button
                          onClick={() => openEdit(entry)}
                          aria-label="Modifier l'entrée"
                          title="Modifier"
                          className="p-2 rounded-lg text-jenny-text-secondary hover:text-jenny-coral hover:bg-jenny-coral/10 transition-all"
                        >
                          <Pencil className="w-4 h-4" />
                        </button>
                      )}
                      <button
                        onClick={() => handleDelete(entry.id)}
                        disabled={deletingId === entry.id}
                        aria-label="Supprimer l'entrée"
                        title="Supprimer"
                        className="p-2 rounded-lg text-jenny-text-secondary hover:text-jenny-error hover:bg-jenny-error/10 transition-all"
                      >
                        <Trash2 className={cn("w-4 h-4", deletingId === entry.id && "animate-spin")} />
                      </button>
                    </div>
                  </Card>
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        )}
      </div>
    </div>
  );
}
