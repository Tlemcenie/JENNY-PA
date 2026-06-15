"use client";

import { motion } from "framer-motion";
import { cn, intentLabel } from "@/lib/utils";
import { Sparkles, User } from "lucide-react";

interface MessageBubbleProps {
  content: string;
  isUser: boolean;
  timestamp?: string;
  meta?: {
    intent?: string;
    confidence?: number;
    agent?: string;
    phase?: string;
  };
}

export function MessageBubble({ content, isUser, timestamp, meta }: MessageBubbleProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: "spring", stiffness: 380, damping: 30, mass: 0.7 }}
      className={cn("flex items-start gap-3", isUser ? "justify-end" : "")}
    >
      {/* Avatar - left for Jenny */}
      {!isUser && (
        <div className="w-9 h-9 rounded-xl bg-jenny-mint flex items-center justify-center flex-shrink-0">
          <span className="text-jenny-coral font-bold text-[0.75rem]">J</span>
        </div>
      )}

      {/* Bubble */}
      <div className={cn("max-w-[75%] md:max-w-[65%] flex flex-col gap-1.5", isUser ? "items-end" : "items-start")}>
        <div
          className={cn(
            "px-4 py-3 text-[0.9375rem] leading-[1.6]",
            isUser
              ? "bg-brand-gradient text-white rounded-2xl rounded-tr-lg shadow-sm shadow-jenny-coral/20"
              : "bg-jenny-bg border border-jenny-divider rounded-2xl rounded-tl-lg text-jenny-text"
          )}
        >
          {content}
        </div>

        {/* Meta for Jenny */}
        {!isUser && meta && (meta.intent || meta.agent) && (
          <div className="flex items-center gap-2 px-1 flex-wrap">
            {meta.intent && (
              <span className="text-[0.6875rem] text-jenny-text-secondary/70 flex items-center gap-1">
                <Sparkles className="w-3 h-3 text-jenny-coral/50" />
                {intentLabel(meta.intent)}
                {meta.confidence != null && (
                  <span className="opacity-50">
                    {Math.round(meta.confidence * 100)}%
                  </span>
                )}
              </span>
            )}
            {meta.agent && (
              <span className="text-[0.6875rem] text-jenny-text-secondary/40">
                via {meta.agent}
              </span>
            )}
          </div>
        )}

        {timestamp && (
          <span className="text-[0.6875rem] text-jenny-text-secondary/40 px-1">
            {timestamp}
          </span>
        )}
      </div>

      {/* Avatar - right for user */}
      {isUser && (
        <div className="w-9 h-9 rounded-xl bg-jenny-coral/8 flex items-center justify-center flex-shrink-0">
          <User className="w-4 h-4 text-jenny-coral" />
        </div>
      )}
    </motion.div>
  );
}
