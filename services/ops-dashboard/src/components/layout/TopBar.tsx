import { useAuth } from "../../auth/useAuth";

const EXTERNAL_LINKS = [
  { href: "http://localhost:3000", label: "Grafana" },
  { href: "http://localhost:16686", label: "Jaeger" },
  { href: "http://localhost:9090", label: "Prometheus" },
  { href: "http://localhost:9001", label: "MinIO Console" },
];

interface TopBarProps {
  title: string;
}

export function TopBar({ title }: TopBarProps) {
  const { user, logout } = useAuth();

  return (
    <header className="top-bar">
      <h1 className="top-bar__title">{title}</h1>
      <nav aria-label="Observability tools" className="top-bar__links">
        {EXTERNAL_LINKS.map((link) => (
          <a key={link.href} href={link.href} target="_blank" rel="noreferrer">
            {link.label} ↗
          </a>
        ))}
      </nav>
      {user && (
        <div className="top-bar__user">
          <span>
            {user.email} <span className="text-muted">({user.role})</span>
          </span>
          <button type="button" className="btn btn--ghost" onClick={logout}>
            Sign out
          </button>
        </div>
      )}
    </header>
  );
}
