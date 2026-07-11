import type { RiskLevel } from "../api/client";
import { PlotlyChart } from "./PlotlyChart";

export function RiskCard({
  title,
  subtitle,
  about,
  howToUse,
  finding,
  riskLevel,
  plotlyJson,
  metric,
  chartCaption,
  chartKind = "bar",
}: {
  title: string;
  subtitle: string;
  about: string;
  howToUse: string;
  finding: string;
  riskLevel: RiskLevel;
  plotlyJson?: Record<string, unknown>;
  metric?: string;
  chartCaption: string;
  chartKind?: "bar" | "pie";
}) {
  return (
    <article className="risk-card risk-card-stack">
      <header className="risk-card-header">
        <div>
          <p className="risk-card-kicker">Risk lens</p>
          <h3>{title}</h3>
          <p className="risk-card-subtitle">{subtitle}</p>
        </div>
        <span className={`pill risk-${riskLevel}`}>{riskLevel}</span>
      </header>

      <div className="lens-guide">
        <p>
          <span className="lens-guide-label">About this data</span>
          {about}
        </p>
        <p>
          <span className="lens-guide-label">How to use it</span>
          {howToUse}
        </p>
      </div>

      <p className="finding">{finding}</p>
      {metric ? <p className="metric">{metric}</p> : null}

      <div className="chart-panel">
        <p className="chart-caption">{chartCaption}</p>
        {plotlyJson ? (
          <PlotlyChart plotlyJson={plotlyJson} kind={chartKind} title={title} />
        ) : (
          <p className="chart-empty">Chart unavailable for this lens.</p>
        )}
      </div>
    </article>
  );
}
