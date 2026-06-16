import Image from "next/image";
import { cn } from "@/lib/utils";

/**
 * Avatar Jenny réutilisable.
 *
 * La mascotte (`/jenny.png`) est un PNG **à fond transparent**. Le problème
 * récurrent venait de l'affichage : posée sur un cercle `bg-jenny-coral` et
 * mise à l'échelle (`object-cover` 120 % + décalages), elle se retrouvait
 * « corail sur corail », mal cadrée. Ici on la pose en `object-contain`,
 * centrée, sur un fond DOUX (jamais corail plein) pour qu'elle ressorte —
 * et on réutilise ce composant partout (sidebar, chat, dashboard…).
 */
export function JennyAvatar({
  size = 36,
  tone = "light",
  className,
  priority = false,
}: {
  size?: number;
  /** Fond du cercle : clair (surfaces blanches), sombre (sidebar/nuit), ou aucun. */
  tone?: "light" | "dark" | "plain";
  className?: string;
  priority?: boolean;
}) {
  const bg =
    tone === "light"
      ? "bg-gradient-to-br from-[#FFE9E1] to-[#FFD9CC]"
      : tone === "dark"
        ? "bg-white/[0.08]"
        : "";
  return (
    <span
      className={cn(
        "relative inline-flex items-center justify-center rounded-full overflow-hidden shrink-0",
        bg,
        className
      )}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <Image
        src="/jenny.png"
        alt="Jenny"
        width={size}
        height={size}
        priority={priority}
        // 82 % → léger « padding » optique pour que la mascotte respire dans le cercle.
        className="object-contain"
        style={{ width: "82%", height: "82%" }}
      />
    </span>
  );
}
