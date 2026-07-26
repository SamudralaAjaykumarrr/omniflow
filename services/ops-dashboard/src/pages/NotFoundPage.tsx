import { Link } from "react-router-dom";
import { EmptyState } from "../components/common/EmptyState";

export function NotFoundPage() {
  return (
    <EmptyState
      title="Page not found"
      description="That screen doesn't exist in this dashboard."
      action={<Link to="/">Back to Overview</Link>}
    />
  );
}
