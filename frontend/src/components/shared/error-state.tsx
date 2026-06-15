"use client";

import { AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorState({
  title = "Une erreur est survenue",
  message = "Impossible de charger les données. Vérifiez votre connexion et réessayez.",
  onRetry,
  className,
}: ErrorStateProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center py-16 px-4 text-center", className)}>
      <div className="w-16 h-16 rounded-2xl bg-jenny-error/10 flex items-center justify-center mb-4">
        <AlertCircle className="w-8 h-8 text-jenny-error" />
      </div>
      <h3 className="text-lg font-semibold text-jenny-text mb-1">{title}</h3>
      <p className="text-sm text-jenny-text-secondary max-w-sm mb-4">{message}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Réessayer
        </Button>
      )}
    </div>
  );
}
