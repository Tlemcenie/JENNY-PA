"use client";

import { useState } from "react";
import { Copy, Check } from "lucide-react";
import { useToast } from "@/components/ui/toast";

export function CopyButton({ value, label }: { value: string; label?: string }) {
  const toast = useToast();
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      toast.success(label || "Copié");
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Copie impossible.");
    }
  };

  return (
    <button
      onClick={copy}
      aria-label="Copier"
      title="Copier"
      className="ml-auto p-1 rounded text-jenny-text-secondary/50 hover:text-jenny-coral opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
    >
      {copied ? <Check className="w-3.5 h-3.5 text-jenny-success" /> : <Copy className="w-3.5 h-3.5" />}
    </button>
  );
}
