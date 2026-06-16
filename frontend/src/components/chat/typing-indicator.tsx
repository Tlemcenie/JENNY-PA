"use client";

import { JennyAvatar } from "@/components/ui/jenny-avatar";

// Indicateur « Jenny écrit… » — repris du design ScreenChat : avatar 32 à gauche
// + bulle blanche `.jbubble--them` contenant les 3 points `.jtyping` (i × 3).
export function TypingIndicator() {
  return (
    <div className="animate-fade-in" style={{ alignSelf: "flex-start", display: "flex", gap: 10, alignItems: "center" }}>
      <JennyAvatar size={32} tone="light" className="mt-0.5" />
      <div className="jbubble jbubble--them" style={{ padding: "13px 16px", display: "flex" }}>
        <span className="jtyping">
          <i />
          <i />
          <i />
        </span>
      </div>
    </div>
  );
}
