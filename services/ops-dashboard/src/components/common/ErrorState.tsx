import { ApiError, NetworkError } from "../../api/client";

interface ErrorStateProps {
  error: Error;
  onRetry?: () => void;
  context?: string;
}

function describeError(error: Error): string {
  if (error instanceof NetworkError) {
    return "Could not reach the backend. It may be starting up, unhealthy, or unreachable from this network.";
  }
  if (error instanceof ApiError) {
    return `Backend returned an error (HTTP ${error.status}): ${error.message}`;
  }
  return error.message || "An unexpected error occurred.";
}

export function ErrorState({ error, onRetry, context }: ErrorStateProps) {
  return (
    <div className="state-panel state-panel--error" role="alert">
      <p className="state-panel__title">
        {context ? `Couldn't load ${context}` : "Something went wrong"}
      </p>
      <p className="state-panel__description">{describeError(error)}</p>
      {onRetry && (
        <button type="button" className="btn btn--secondary" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
