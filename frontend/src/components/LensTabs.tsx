import { useEffect, useState } from "react";
import type { RiskLevel } from "../api/client";
import { RiskCard } from "./RiskCard";

export type LensTab = {
  id: string;
  label: string;
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
};

export function LensTabs({ tabs }: { tabs: LensTab[] }) {
  const [activeId, setActiveId] = useState(tabs[0]?.id ?? "");

  useEffect(() => {
    if (!tabs.length) return;
    if (!tabs.some((t) => t.id === activeId)) {
      setActiveId(tabs[0].id);
    }
  }, [tabs, activeId]);

  const active = tabs.find((t) => t.id === activeId) ?? tabs[0];
  if (!active) return null;

  return (
    <section className="lens-tabs" aria-label="Risk lenses">
      <div className="lens-tablist" role="tablist" aria-label="Select risk lens">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={tab.id === active.id}
            className={`lens-tab${tab.id === active.id ? " is-active" : ""}`}
            onClick={() => setActiveId(tab.id)}
          >
            <span className="lens-tab-label">{tab.label}</span>
            <span className={`lens-tab-risk risk-${tab.riskLevel}`}>{tab.riskLevel}</span>
          </button>
        ))}
      </div>

      <div className="lens-tab-panel" role="tabpanel">
        <RiskCard
          title={active.title}
          subtitle={active.subtitle}
          about={active.about}
          howToUse={active.howToUse}
          finding={active.finding}
          riskLevel={active.riskLevel}
          plotlyJson={active.plotlyJson}
          chartKind={active.chartKind}
          chartCaption={active.chartCaption}
          metric={active.metric}
        />
      </div>
    </section>
  );
}
