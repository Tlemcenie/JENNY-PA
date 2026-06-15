"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { CheckCircle2, Circle, Radio } from "lucide-react";
import { listChannels, type ChannelStatus } from "@/lib/api";
import { SkeletonCard } from "@/components/ui/skeleton";
import { cn, channelColor } from "@/lib/utils";
import { staggerContainer, staggerItem } from "@/lib/motion";

export default function ChannelsPage() {
  const [channels, setChannels] = useState<ChannelStatus[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listChannels()
      .then(setChannels)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const connectedCount = channels.filter((c) => c.connected).length;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto p-4 md:p-6 space-y-5">
        <div>
          <div className="font-mono text-[11px] tracking-[0.22em] uppercase text-jenny-coral mb-2">— tous vos messages, un seul endroit —</div>
          <h1 className="font-display text-[clamp(28px,4vw,36px)] leading-[1] tracking-[-0.02em] text-jenny-text">
            Vos <span className="italic text-jenny-coral">canaux.</span>
          </h1>
          <p className="text-sm text-jenny-text-secondary mt-0.5">
            {connectedCount} canal{connectedCount > 1 ? "x" : ""} connecté
            {connectedCount > 1 ? "s" : ""} · centralisez tous vos messages ici.
          </p>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        ) : (
          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate="show"
            className="grid grid-cols-1 sm:grid-cols-2 gap-3"
          >
            {channels.map((c) => (
              <motion.div
                key={c.channel}
                variants={staggerItem}
                className="bg-jenny-surface border border-jenny-divider rounded-2xl p-4 flex items-center gap-3"
              >
                <span
                  className={cn(
                    "w-10 h-10 rounded-xl flex items-center justify-center text-white shrink-0",
                    channelColor(c.channel)
                  )}
                >
                  <Radio className="w-5 h-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-jenny-text">{c.label}</p>
                  <p className="text-xs text-jenny-text-secondary truncate">
                    {c.builtin
                      ? "Intégré nativement"
                      : c.account
                      ? c.account
                      : c.connected
                      ? "Connecté"
                      : "Non connecté"}
                  </p>
                </div>
                {c.connected ? (
                  <span className="flex items-center gap-1 text-xs font-medium text-jenny-success shrink-0">
                    <CheckCircle2 className="w-4 h-4" />
                    Actif
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-xs font-medium text-jenny-text-secondary shrink-0">
                    <Circle className="w-4 h-4" />
                    Inactif
                  </span>
                )}
              </motion.div>
            ))}
          </motion.div>
        )}

        <p className="text-xs text-jenny-text-secondary">
          Les canaux WhatsApp, Instagram, Twitter et Snapchat se connectent via leurs
          webhooks respectifs. Le formulaire web et l&apos;email sont disponibles
          immédiatement.
        </p>
      </div>
    </div>
  );
}
