interface MockDataNoticeProps {
  reason: string;
}

/**
 * Visible, non-dismissable banner for every screen (or screen section)
 * backed by local fallback data rather than a live API — see
 * docs/phase-7-ops-dashboard.md "Missing API contracts / mock-data
 * requirements". Never rendered silently alongside real data without this.
 */
export function MockDataNotice({ reason }: MockDataNoticeProps) {
  return (
    <div className="mock-notice" role="note">
      <span className="mock-notice__badge">MOCK DATA</span>
      <span>{reason}</span>
    </div>
  );
}
