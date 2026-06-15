"use client";

import { useEffect, useState } from "react";
import { Bell, BellOff } from "lucide-react";
import { isSoundEnabled, setSoundEnabled, playNotificationSound } from "@/lib/sound";
import { cn } from "@/lib/utils";

export function SoundToggle({ className }: { className?: string }) {
  const [on, setOn] = useState(true);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOn(isSoundEnabled());
  }, []);

  const toggle = () => {
    const next = !on;
    setOn(next);
    setSoundEnabled(next);
    if (next) playNotificationSound(); // aperçu sonore à l'activation
  };

  return (
    <button
      onClick={toggle}
      aria-label={on ? "Couper le son des notifications" : "Activer le son des notifications"}
      title={on ? "Son activé" : "Son coupé"}
      className={cn(
        "relative w-9 h-9 rounded-xl flex items-center justify-center",
        "text-jenny-text-secondary hover:text-jenny-coral hover:bg-jenny-coral/10 transition-colors",
        className
      )}
    >
      {on ? <Bell className="w-[18px] h-[18px]" /> : <BellOff className="w-[18px] h-[18px]" />}
    </button>
  );
}
