import { cn } from "@/lib/utils";

interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center py-16 px-4 text-center", className)}>
      {icon && (
        <div className="w-16 h-16 rounded-2xl bg-jenny-divider/50 flex items-center justify-center text-jenny-text-secondary mb-4">
          {icon}
        </div>
      )}
      <h3 className="text-lg font-semibold text-jenny-text mb-1">{title}</h3>
      {description && (
        <p className="text-sm text-jenny-text-secondary max-w-sm">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
