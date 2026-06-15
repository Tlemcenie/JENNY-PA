"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { Smile } from "lucide-react";
import type { Theme } from "emoji-picker-react";
import { cn } from "@/lib/utils";

// Lazy-load : la lib emoji est lourde, on ne la charge qu'à l'ouverture.
const EmojiPicker = dynamic(() => import("emoji-picker-react"), { ssr: false });

export function EmojiButton({ onPick }: { onPick: (emoji: string) => void }) {
  const [open, setOpen] = useState(false);
  const [dark, setDark] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const toggle = () => {
    setDark(document.documentElement.classList.contains("dark"));
    setOpen((o) => !o);
  };

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={toggle}
        title="Insérer un emoji"
        aria-label="Insérer un emoji"
        className={cn(
          "h-9 w-9 flex items-center justify-center rounded-xl border border-jenny-divider transition-colors flex-shrink-0",
          open ? "text-jenny-coral bg-jenny-coral/10" : "text-jenny-text-secondary hover:text-jenny-coral hover:bg-jenny-coral/10"
        )}
      >
        <Smile className="w-4 h-4" />
      </button>
      {open && (
        <div className="absolute bottom-11 right-0 z-30 shadow-2xl rounded-xl overflow-hidden">
          <EmojiPicker
            theme={(dark ? "dark" : "light") as Theme}
            lazyLoadEmojis
            width={320}
            height={380}
            previewConfig={{ showPreview: false }}
            onEmojiClick={(e) => {
              onPick(e.emoji);
              setOpen(false);
            }}
          />
        </div>
      )}
    </div>
  );
}
