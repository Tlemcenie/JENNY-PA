import { cn } from "@/lib/utils";

interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className }: SkeletonProps) {
  return <div className={cn("rounded-lg animate-shimmer", className)} />;
}

export function SkeletonText({ lines = 3 }: { lines?: number }) {
  return (
    <div className="flex flex-col gap-2">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={cn("h-4", i === lines - 1 ? "w-3/4" : "w-full")}
        />
      ))}
    </div>
  );
}

export function SkeletonCard() {
  return (
    <div className="bg-jenny-surface rounded-2xl border border-jenny-divider p-6 space-y-4">
      <div className="flex items-center gap-3">
        <Skeleton className="w-10 h-10 rounded-full" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-3 w-1/4" />
        </div>
      </div>
      <SkeletonText lines={2} />
    </div>
  );
}

// Ligne de tableau « fantôme » : N cellules shimmer de largeurs variées.
// Idéal pour le chargement d'une liste/journal (admin audit, conversations…).
export function SkeletonRow({ cells = 4 }: { cells?: number }) {
  // Largeurs cycliques pour un rendu naturel (pas toutes identiques).
  const widths = ["w-2/3", "w-1/2", "w-3/4", "w-1/3", "w-5/6"];
  return (
    <div className="flex items-center gap-4 py-3">
      {Array.from({ length: cells }).map((_, i) => (
        <div key={i} className="flex-1">
          <Skeleton className={cn("h-4", widths[i % widths.length])} />
        </div>
      ))}
    </div>
  );
}

// Carte compteur « fantôme » : libellé + grand nombre. Pour les grilles de KPI.
export function SkeletonStat() {
  return (
    <div className="bg-jenny-surface rounded-2xl border border-jenny-divider p-5 space-y-3">
      <Skeleton className="h-3 w-1/2" />
      <Skeleton className="h-8 w-2/3" />
    </div>
  );
}
