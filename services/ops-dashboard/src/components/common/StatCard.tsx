import type { ReactNode } from "react";

interface StatCardProps {
  label: string;
  value: ReactNode;
  sublabel?: string;
  tone?: "good" | "warning" | "serious" | "critical";
}

export function StatCard({ label, value, sublabel, tone }: StatCardProps) {
  return (
    <div className="stat-card">
      <p className="stat-card__label">{label}</p>
      <p className={`stat-card__value${tone ? ` stat-card__value--${tone}` : ""}`}>{value}</p>
      {sublabel && <p className="stat-card__sublabel">{sublabel}</p>}
    </div>
  );
}
