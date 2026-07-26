import { statusTone } from "./statusTone";

interface StatusBadgeProps {
  status: string;
  label?: string;
}

const ICON: Record<string, string> = {
  good: "✓",
  warning: "●",
  serious: "▲",
  critical: "✕",
  neutral: "○",
};

export function StatusBadge({ status, label }: StatusBadgeProps) {
  const tone = statusTone(status);
  return (
    <span className={`status-badge status-badge--${tone}`}>
      <span aria-hidden="true">{ICON[tone]}</span>
      {label ?? status}
    </span>
  );
}
