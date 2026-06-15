"use client";

import { useEffect, useState } from "react";
import { Users, UserPlus } from "lucide-react";
import { listMembers, addMember, type TeamMember } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { roleLabel } from "@/lib/utils";

export function TeamSection() {
  const toast = useToast();
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("member");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try {
      setMembers(await listMembers());
    } catch {
      // silencieux
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const add = async () => {
    if (!email.trim() || password.length < 6 || saving) return;
    setSaving(true);
    try {
      await addMember({ email: email.trim(), full_name: fullName.trim() || undefined, password, role });
      setEmail("");
      setFullName("");
      setPassword("");
      setRole("member");
      await load();
      toast.success("Membre ajouté à l'équipe.");
    } catch {
      toast.error("Impossible d'ajouter ce membre.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-jenny-surface border border-jenny-divider rounded-2xl p-6">
      <h2 className="flex items-center gap-2 text-base font-semibold text-jenny-text mb-1">
        <Users className="w-4 h-4 text-jenny-coral" />
        Équipe
      </h2>
      <p className="text-sm text-jenny-text-secondary mb-4">
        Les membres peuvent se voir attribuer des conversations.
      </p>

      <div className="space-y-1.5 mb-4">
        {members.map((m) => (
          <div
            key={m.user_id}
            className="flex items-center justify-between rounded-xl border border-jenny-divider px-3 py-2"
          >
            <div className="min-w-0">
              <p className="text-sm font-medium text-jenny-text truncate">
                {m.full_name || m.email}
              </p>
              <p className="text-xs text-jenny-text-secondary truncate">{m.email}</p>
            </div>
            <span className="text-[11px] font-medium bg-jenny-divider/60 rounded-full px-2 py-0.5 text-jenny-text-secondary">
              {roleLabel(m.role)}
            </span>
          </div>
        ))}
      </div>

      <div className="border-t border-jenny-divider pt-4 space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-jenny-text-secondary">
          Ajouter un membre
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <input
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder="Nom complet"
            className="h-10 px-3 text-sm rounded-lg bg-jenny-bg border border-jenny-divider text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:border-jenny-coral/50"
          />
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            type="email"
            placeholder="Email"
            className="h-10 px-3 text-sm rounded-lg bg-jenny-bg border border-jenny-divider text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:border-jenny-coral/50"
          />
          <input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            type="password"
            placeholder="Mot de passe initial (6+ car.)"
            className="h-10 px-3 text-sm rounded-lg bg-jenny-bg border border-jenny-divider text-jenny-text placeholder:text-jenny-text-secondary/60 focus:outline-none focus:border-jenny-coral/50"
          />
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="h-10 px-3 text-sm rounded-lg bg-jenny-bg border border-jenny-divider text-jenny-text focus:outline-none focus:border-jenny-coral/50"
          >
            <option value="member">Membre</option>
            <option value="agent">Agent</option>
            <option value="admin">Administrateur</option>
          </select>
        </div>
        <button
          onClick={add}
          disabled={!email.trim() || password.length < 6 || saving}
          className="h-10 px-4 flex items-center gap-2 rounded-xl bg-jenny-coral text-white text-sm font-medium hover:bg-jenny-coral-dark disabled:opacity-50 transition-colors"
        >
          <UserPlus className="w-4 h-4" />
          {saving ? "Ajout…" : "Ajouter le membre"}
        </button>
      </div>
    </div>
  );
}
