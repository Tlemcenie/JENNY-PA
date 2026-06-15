import { cn, channelColor } from "@/lib/utils";

interface BadgeProps {
  children: React.ReactNode;
  variant?: "default" | "success" | "warning" | "error" | "channel";
  channel?: string;
  className?: string;
}

export function Badge({ children, variant = "default", channel, className }: BadgeProps) {
  const variants = {
    default: "bg-jenny-divider text-jenny-text",
    success: "bg-jenny-success/10 text-jenny-success",
    warning: "bg-jenny-warning/10 text-jenny-warning",
    error: "bg-jenny-error/10 text-jenny-error",
    channel: "",
  };

  if (variant === "channel" && channel) {
    return (
      <span className={cn("inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium", className)}>
        <span className={cn("w-2 h-2 rounded-full", channelColor(channel))} />
        {children}
      </span>
    );
  }

  return (
    <span
      className={cn(
        "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium",
        variants[variant],
        className
      )}
    >
      {children}
    </span>
  );
}
