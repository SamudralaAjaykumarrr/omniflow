export interface NavItem {
  to: string;
  label: string;
  icon: string;
}

/** The dashboard's 10 screens (see docs/phase-7-ops-dashboard.md for how
 * this list was derived from docs/architecture.md and
 * docs/product-requirements.md — the roadmap names "10 screens" without
 * enumerating them). */
export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Overview", icon: "◆" },
  { to: "/orders", label: "Orders", icon: "▤" },
  { to: "/inventory", label: "Inventory & Nodes", icon: "▣" },
  { to: "/saga-monitor", label: "Saga Monitor", icon: "⇄" },
  { to: "/dead-letters", label: "Dead Letter Queue", icon: "⚠" },
  { to: "/observability", label: "Observability", icon: "◔" },
  { to: "/data-quality", label: "Data Quality", icon: "✓" },
  { to: "/data-platform", label: "Data Platform", icon: "▥" },
  { to: "/forecasting", label: "Demand Forecasting", icon: "∿" },
  { to: "/failure-lab", label: "Failure Laboratory", icon: "✕" },
];
