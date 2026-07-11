import type { RiskLevel } from "../api/client";

const LABELS: Record<RiskLevel, string> = {
  low: "Low risk",
  medium: "Medium risk",
  high: "High risk",
};

export function RiskBadge({ level }: { level: RiskLevel }) {
  return (
    <div className={`risk-badge risk-${level}`} role="status">
      <span className="risk-badge-label">Overall rating</span>
      <strong>{LABELS[level]}</strong>
    </div>
  );
}
