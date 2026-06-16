"use client";

import { ChatInterface } from "@/components/chat/chat-interface";

export default function ChatPage() {
  return (
    <div className="jx h-full flex flex-col" style={{ background: "var(--surface)" }}>
      {/* Bandeau : ce chat SIMULE un client. Ici Jenny répond comme un membre
          humain de l'équipe (jamais comme une IA), en français. */}
      <div
        className="shrink-0"
        style={{
          padding: "8px 32px",
          background: "var(--coral-tint)",
          borderBottom: "1px solid var(--divider)",
        }}
      >
        <p
          className="jmono"
          style={{
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: "0.18em",
            color: "var(--coral-dark)",
            margin: 0,
          }}
        >
          — Test Jenny · côté client —
        </p>
        <p style={{ fontSize: 12, color: "var(--text-2)", marginTop: 2 }}>
          Discutez avec Jenny comme le ferait un de vos clients. Elle répond en français,
          comme un membre de votre équipe. (Pour piloter votre salon, allez sur «&nbsp;Assistant Jenny&nbsp;».)
        </p>
      </div>
      <div className="flex-1 min-h-0">
        <ChatInterface />
      </div>
    </div>
  );
}
