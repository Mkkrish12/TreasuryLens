export type RiskLevel = "low" | "medium" | "high";

export interface LensFinding {
  finding: string;
  risk_level: RiskLevel;
}

export interface RiskReport {
  overall_risk_rating: RiskLevel;
  concentration: LensFinding & {
    top_wallet_share_pct: number | null;
  };
  diversification: LensFinding & {
    chain_distribution: Record<string, number>;
  };
  liquidity: LensFinding & {
    dormant_wallet_count: number | null;
  };
  drawdown?: LensFinding & {
    max_drawdown_pct: number | null;
  } | null;
  percentile?: LensFinding & {
    worse_than_pct_of_peers: number | null;
    top_share_pct: number | null;
    cohort: string | null;
  } | null;
  counterparty?: LensFinding & {
    top_counterparty_share_pct: number | null;
  } | null;
  summary: string;
  recommendations: string[];
  units_note?: string;
}

export type LensName =
  | "concentration"
  | "diversification"
  | "liquidity"
  | "drawdown"
  | "percentile"
  | "counterparty";

export interface ChartPayload {
  lens: LensName;
  plotly_json: Record<string, unknown>;
}

export interface ReportResponse {
  report_json: RiskReport;
  charts: ChartPayload[];
  sql_used: string[];
  demo_mode: boolean;
  schema_notes?: string | null;
}

export async function fetchHealth() {
  const res = await fetch("/api/health");
  if (!res.ok) throw new Error("Health check failed");
  return res.json();
}

export async function fetchDemoWallets(): Promise<string[]> {
  const res = await fetch("/api/demo-wallets");
  if (!res.ok) return [];
  const data = await res.json();
  return data.addresses ?? [];
}

export async function createReport(body: {
  mode: "population" | "wallets";
  addresses?: string[];
}): Promise<ReportResponse> {
  const res = await fetch("/api/report", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text();
    let message = detail || `Report failed (${res.status})`;
    try {
      const parsed = JSON.parse(detail) as { detail?: string };
      if (parsed.detail) message = parsed.detail;
    } catch {
      /* plain text body */
    }
    throw new Error(message);
  }
  return res.json();
}

export interface AskResponse {
  answer: string;
  sql_used?: string | null;
  rows: Record<string, unknown>[];
  row_count: number;
  plotly_json?: Record<string, unknown> | null;
  chart_kind?: "bar" | "pie" | null;
  demo_mode: boolean;
  source: "craft_live" | "live_cache" | "demo";
  notes?: string | null;
}

export async function askQuestion(body: {
  question: string;
  addresses?: string[];
}): Promise<AskResponse> {
  const res = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text();
    let message = detail || `Ask failed (${res.status})`;
    try {
      const parsed = JSON.parse(detail) as { detail?: string };
      if (parsed.detail) message = parsed.detail;
    } catch {
      /* plain text */
    }
    throw new Error(message);
  }
  return res.json();
}
