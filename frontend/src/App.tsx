import { useEffect, useState } from "react";
import {
  createReport,
  fetchDemoWallets,
  fetchHealth,
  type ReportResponse,
} from "./api/client";
import { RiskBadge } from "./components/RiskBadge";
import { RiskCard } from "./components/RiskCard";
import { SqlAccordion } from "./components/SqlAccordion";
import { Summary } from "./components/Summary";

type Progress = string | null;

export default function App() {
  const [walletText, setWalletText] = useState("");
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<Progress>(null);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [health, setHealth] = useState<{
    craft_configured?: boolean;
    nebius_configured?: boolean;
  } | null>(null);

  useEffect(() => {
    fetchHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
    fetchDemoWallets().then((addrs) => {
      if (addrs.length && addrs[0] && !addrs[0].startsWith("0x0000")) {
        setWalletText(addrs.join("\n"));
      }
    });
  }, []);

  async function runScan(mode: "population" | "wallets") {
    setLoading(true);
    setError(null);
    setProgress(
      mode === "population"
        ? "Running population scan across six risk lenses…"
        : "Scanning wallets across six risk lenses…"
    );
    try {
      const addresses = walletText
        .split(/[\n,]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      if (mode === "wallets" && addresses.length === 0) {
        throw new Error("Enter at least one wallet address, or run a population scan.");
      }
      const result = await createReport({
        mode,
        addresses: mode === "wallets" ? addresses : [],
      });
      setReport(result);
      setProgress(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setProgress(null);
    } finally {
      setLoading(false);
    }
  }

  const chartsByLens = Object.fromEntries(
    (report?.charts ?? []).map((c) => [c.lens, c.plotly_json])
  );

  return (
    <div className="page">
      <div className="atmosphere" aria-hidden="true" />
      <header className="hero">
        <p className="brand">TreasuryLens</p>
        <h1>Corporate Crypto Treasury Risk Report</h1>
        <p className="lede">
          Concentration, diversification, liquidity, drawdown, peer percentile, and
          counterparty risk — grounded in the CRAFT CRYPTO dataset.
        </p>
      </header>

      <section className="controls">
        <div className="control-primary">
          <button
            type="button"
            className="btn primary"
            disabled={loading}
            onClick={() => runScan("population")}
          >
            {loading ? "Scanning…" : "Run population-level scan"}
          </button>
          <p className="hint">
            Recommended demo path — no wallet list required. Respects CRAFT&apos;s 10
            queries/min limit.
          </p>
        </div>
        <div className="control-secondary">
          <label htmlFor="wallets">Optional wallet addresses (one per line)</label>
          <textarea
            id="wallets"
            rows={4}
            value={walletText}
            onChange={(e) => setWalletText(e.target.value)}
            placeholder={"0xabc…\nbc1q…"}
          />
          <button
            type="button"
            className="btn secondary"
            disabled={loading}
            onClick={() => runScan("wallets")}
          >
            Scan wallets
          </button>
        </div>
      </section>

      {health ? (
        <p className="status-line">
          CRAFT: {health.craft_configured ? "connected" : "demo fallback"} · Nebius:{" "}
          {health.nebius_configured ? "ready" : "heuristic synthesis"}
        </p>
      ) : null}

      {progress ? <p className="progress">{progress}</p> : null}
      {error ? <p className="error">{error}</p> : null}

      {report ? (
        <main className="report">
          {report.demo_mode ? (
            <div className="demo-banner">
              Demo mode — CRAFT credentials not configured. Figures are labeled synthetic
              population data for UI rehearsal. Add CRAFT_PROJECT_ID + token and re-run
              schema recon for live CRYPTO queries.
            </div>
          ) : null}

          <RiskBadge level={report.report_json.overall_risk_rating} />

          <div className="lens-stack">
            <RiskCard
              title="Concentration"
              subtitle="How much of scanned treasury value sits in the largest wallets"
              about="Wallet-level share of top-N native balances from the CRYPTO BALANCES table (ETC in the live scan)."
              howToUse="If one bar dominates, split custody across wallets / policies — a single key compromise or freeze would hit a large share of holdings."
              finding={report.report_json.concentration.finding}
              riskLevel={report.report_json.concentration.risk_level}
              plotlyJson={chartsByLens.concentration}
              chartKind="bar"
              chartCaption="Tallest bar = largest wallet share (%) of the scanned top-N total."
              metric={
                report.report_json.concentration.top_wallet_share_pct != null
                  ? `Top wallet share: ${report.report_json.concentration.top_wallet_share_pct}%`
                  : undefined
              }
            />
            <RiskCard
              title="Diversification"
              subtitle="How treasury activity is spread across blockchain networks"
              about="Transaction volume share by chain schema (Bitcoin, Ethereum, etc.) from the CRYPTO dataset."
              howToUse="A dominant slice means operational and protocol risk is concentrated on one network — plan failover and caps for that chain."
              finding={report.report_json.diversification.finding}
              riskLevel={report.report_json.diversification.risk_level}
              plotlyJson={chartsByLens.diversification}
              chartKind="pie"
              chartCaption="Each slice = one chain’s share of scanned transaction volume."
            />
            <RiskCard
              title="Liquidity"
              subtitle="How recently and actively the busiest wallets have moved funds"
              about="Days since last outbound activity for high-volume senders. Snapshot age can inflate dormancy vs wall-clock time."
              howToUse="Prioritize operational review for high bars (key ceremony, multisig readiness). Treat as mobilization friction, not market liquidity."
              finding={report.report_json.liquidity.finding}
              riskLevel={report.report_json.liquidity.risk_level}
              plotlyJson={chartsByLens.liquidity}
              chartKind="bar"
              chartCaption="Bar height = days since last on-chain transaction (higher = more dormant)."
              metric={
                report.report_json.liquidity.dormant_wallet_count != null
                  ? `Dormant wallets: ${report.report_json.liquidity.dormant_wallet_count}`
                  : undefined
              }
            />
            {report.report_json.percentile ? (
              <RiskCard
                title="Peer percentile"
                subtitle="Where this treasury’s concentration sits vs the scanned cohort"
                about="Relative rank of the top wallet’s share within the scanned top-N balance cohort (full-population PERCENT_RANK when Craft returns it)."
                howToUse="Use for peer framing with CFOs: “worse than X% of observed wallets” is clearer than an absolute % alone."
                finding={report.report_json.percentile.finding}
                riskLevel={report.report_json.percentile.risk_level}
                plotlyJson={chartsByLens.percentile}
                chartKind="bar"
                chartCaption="Bars = each wallet’s share (%) within the scanned cohort, ranked."
                metric={
                  report.report_json.percentile.worse_than_pct_of_peers != null
                    ? `Worse than ${report.report_json.percentile.worse_than_pct_of_peers}% of peers`
                    : undefined
                }
              />
            ) : null}
            {report.report_json.drawdown ? (
              <RiskCard
                title="Max drawdown"
                subtitle="Largest peak-to-trough decline in cumulative native balance"
                about="Peak-to-trough drop on a cumulative net-flow path (SUM + running MAX window functions). Classic portfolio drawdown in native units."
                howToUse="Treat as treasury stress capacity: large drawdowns warrant outflow limits, alerts, and hot-wallet policy review."
                finding={report.report_json.drawdown.finding}
                riskLevel={report.report_json.drawdown.risk_level}
                plotlyJson={chartsByLens.drawdown}
                chartKind="bar"
                chartCaption="Gap between running peak and trough = max drawdown (live series when Craft returns rows)."
                metric={
                  report.report_json.drawdown.max_drawdown_pct != null
                    ? `Max drawdown: ${report.report_json.drawdown.max_drawdown_pct}%`
                    : "Awaiting live window query"
                }
              />
            ) : null}
            {report.report_json.counterparty ? (
              <RiskCard
                title="Counterparty concentration"
                subtitle="Relationship risk — who you transact with, not just what you hold"
                about="How concentrated flows are toward counterparties (proxy from unique CPs / density until Craft returns true top-CP volume share)."
                howToUse="High bars mean relationship exposure: one counterparty freeze, hack, or insolvency could stall a large share of flow."
                finding={report.report_json.counterparty.finding}
                riskLevel={report.report_json.counterparty.risk_level}
                plotlyJson={chartsByLens.counterparty}
                chartKind="bar"
                chartCaption="Higher bars = stronger relationship-concentration proxy (distinct from asset concentration)."
                metric={
                  report.report_json.counterparty.top_counterparty_share_pct != null
                    ? `Top relationship proxy: ${report.report_json.counterparty.top_counterparty_share_pct}`
                    : undefined
                }
              />
            ) : null}
          </div>

          <Summary text={report.report_json.summary} />

          <section className="recommendations">
            <h2>Recommendations</h2>
            <ul>
              {report.report_json.recommendations.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </section>

          <SqlAccordion queries={report.sql_used} />
        </main>
      ) : null}

      <footer className="footer">
        Values reported in native token units; no USD valuation unless a price column exists
        in the CRYPTO dataset. Emergence / Nebius CRAFT hackathon.
      </footer>
    </div>
  );
}
