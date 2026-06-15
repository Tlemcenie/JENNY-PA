"use client";

import { ChatInterface } from "@/components/chat/chat-interface";

export default function ChatPage() {
  return (
    <div className="h-full flex flex-col">
      {/* Bandeau : ce chat SIMULE un client. Ici Jenny répond comme un membre
          humain de l'équipe (jamais comme une IA), en français. */}
      <div className="shrink-0 px-4 py-2 bg-jenny-coral/[0.06] border-b border-jenny-divider">
        <p className="text-[11px] font-mono uppercase tracking-[0.18em] text-jenny-coral">
          — Test Jenny · côté client —
        </p>
        <p className="text-xs text-jenny-text-secondary mt-0.5">
          Discute avec Jenny comme le ferait un de tes clients. Elle répond en
          français, comme un membre de ton équipe. (Pour piloter ton salon, va sur
          « Assistant Jenny ».)
        </p>
      </div>
      <div className="flex-1 min-h-0">
        <ChatInterface />
      </div>
    </div>
  );
}
