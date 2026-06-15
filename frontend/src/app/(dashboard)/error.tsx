"use client";

import { useEffect } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // En prod, on enverrait ça à un service de suivi des erreurs.
    console.error("dashboard.error", error);
  }, [error]);

  return (
    <div className="h-full flex items-center justify-center p-6">
      <div className="text-center max-w-sm">
        <div className="w-16 h-16 rounded-2xl bg-jenny-error/10 text-jenny-error flex items-center justify-center mx-auto mb-4">
          <AlertTriangle className="w-8 h-8" />
        </div>
        <h2 className="text-lg font-semibold text-jenny-text mb-1">
          Une erreur est survenue
        </h2>
        <p className="text-sm text-jenny-text-secondary mb-5">
          Quelque chose s&apos;est mal passé sur cette page. Vous pouvez réessayer.
        </p>
        <button
          onClick={reset}
          className="inline-flex items-center gap-2 h-10 px-4 rounded-xl bg-jenny-coral text-white text-sm font-semibold hover:bg-jenny-coral-dark transition-colors"
        >
          <RotateCcw className="w-4 h-4" />
          Réessayer
        </button>
      </div>
    </div>
  );
}
