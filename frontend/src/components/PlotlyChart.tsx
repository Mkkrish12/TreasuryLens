import createPlotlyComponent from "react-plotly.js/factory";
// @ts-expect-error plotly.js-dist-min has no types bundled
import Plotly from "plotly.js-dist-min";

const Plot = createPlotlyComponent(Plotly);

const TEAL = "#0f766e";
const INK = "#0c1b1a";
const MUTED = "#3d524f";

const CHAIN_COLORS = [
  "#0f766e",
  "#0e7490",
  "#b45309",
  "#334155",
  "#be123c",
  "#047857",
  "#1d4ed8",
];

function yAxisLabel(title: string): string {
  const t = title.toLowerCase();
  if (t.includes("day") || t.includes("liquidity")) return "Days since last transaction";
  if (t.includes("drawdown")) return "Cumulative balance (index) / drawdown %";
  if (t.includes("counterparty") || t.includes("relationship"))
    return "Relationship concentration proxy";
  if (t.includes("percentile") || t.includes("peer")) return "Share of cohort (%)";
  if (t.includes("concentration") || t.includes("share")) return "Share of top-N total (%)";
  return "Value";
}

function enrichData(raw: unknown[], kind: "bar" | "pie" | "line"): object[] {
  if (!raw.length) return [];
  const multi = raw.length > 1;

  return raw.map((trace, idx) => {
    const t = { ...(trace as Record<string, unknown>) };

    if (kind === "pie" || t.type === "pie") {
      return {
        ...t,
        type: "pie",
        hole: 0.46,
        textinfo: "percent",
        textposition: "inside",
        insidetextorientation: "horizontal",
        marker: {
          colors: CHAIN_COLORS,
          line: { color: "#fffdf9", width: 2 },
          ...((t.marker as object) || {}),
        },
        hovertemplate: "<b>%{label}</b><br>%{percent}<br>Count/value: %{value:,.0f}<extra></extra>",
        showlegend: true,
      };
    }

    if (kind === "line" || t.type === "scatter") {
      return {
        ...t,
        type: "scatter",
        mode: (t.mode as string) || "lines+markers",
        showlegend: true,
        hovertemplate: "<b>%{x}</b><br>%{y:,.2f}<extra></extra>",
        line: {
          width: 2.5,
          color: idx === 0 ? TEAL : "#b45309",
          ...((t.line as object) || {}),
        },
      };
    }

    return {
      ...t,
      type: "bar",
      marker: {
        color: Array.isArray(t.x)
          ? (t.x as unknown[]).map((_, i) =>
              i === 0 ? "#be123c" : CHAIN_COLORS[(i % (CHAIN_COLORS.length - 1)) + 1]
            )
          : TEAL,
        opacity: 0.9,
        line: { width: 0 },
        ...((t.marker as object) || {}),
      },
      hovertemplate: "<b>%{x}</b><br>%{y:,.2f}<extra></extra>",
      // Single bar series: no Plotly legend (card already explains the chart)
      showlegend: multi,
      name: (t.name as string) || "Value",
    };
  });
}

function enrichLayout(
  raw: Record<string, unknown> | undefined,
  kind: "bar" | "pie" | "line",
  title: string,
  multiSeries: boolean
): object {
  const base = { ...(raw || {}) };
  // Drop layout fields that collide with our card chrome / each other
  delete base.title;
  delete base.annotations;
  delete base.legend;
  delete base.margin;

  const needsLegend = kind === "pie" || kind === "line" || multiSeries;

  return {
    ...base,
    // Title lives on the RiskCard — keep Plotly clear
    title: undefined,
    autosize: true,
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(255,253,249,0.55)",
    font: { family: "IBM Plex Sans, sans-serif", color: INK, size: 12 },
    margin:
      kind === "pie"
        ? { t: 16, r: 150, b: 16, l: 16 }
        : needsLegend
          ? { t: 20, r: 24, b: 88, l: 64 }
          : { t: 16, r: 20, b: 96, l: 64 },
    showlegend: needsLegend,
    legend:
      kind === "pie"
        ? {
            orientation: "v",
            yanchor: "middle",
            y: 0.5,
            xanchor: "left",
            x: 1.02,
            font: { size: 11, color: MUTED },
            bgcolor: "rgba(0,0,0,0)",
            borderwidth: 0,
            traceorder: "normal",
          }
        : {
            orientation: "h",
            yanchor: "top",
            y: -0.22,
            xanchor: "left",
            x: 0,
            font: { size: 11, color: MUTED },
            bgcolor: "rgba(0,0,0,0)",
            borderwidth: 0,
          },
    ...(kind === "pie"
      ? {}
      : {
          xaxis: {
            tickangle: -28,
            automargin: true,
            title: {
              text: kind === "line" ? "Time" : "Wallet / address",
              standoff: 8,
              font: { size: 11, color: MUTED },
            },
            gridcolor: "rgba(12,27,26,0.06)",
            zeroline: false,
            ...((base.xaxis as object) || {}),
          },
          yaxis: {
            automargin: true,
            title: {
              text: yAxisLabel(title),
              standoff: 8,
              font: { size: 11, color: MUTED },
            },
            gridcolor: "rgba(12,27,26,0.08)",
            zerolinecolor: "rgba(12,27,26,0.12)",
            ...((base.yaxis as object) || {}),
          },
          bargap: 0.32,
        }),
    colorway: CHAIN_COLORS,
    hoverlabel: {
      bgcolor: "#fffdf9",
      bordercolor: TEAL,
      font: { family: "IBM Plex Sans, sans-serif", size: 12, color: INK },
    },
  };
}

export function PlotlyChart({
  plotlyJson,
  kind = "bar",
  title = "",
}: {
  plotlyJson: Record<string, unknown>;
  kind?: "bar" | "pie";
  title?: string;
}) {
  const rawData = (plotlyJson.data as unknown[]) ?? [];
  const hasPie = rawData.some((t) => (t as { type?: string })?.type === "pie");
  const hasScatter = rawData.some((t) => (t as { type?: string })?.type === "scatter");
  const chartKind: "bar" | "pie" | "line" =
    kind === "pie" || hasPie ? "pie" : hasScatter ? "line" : "bar";
  const multiSeries = rawData.length > 1;
  const data = enrichData(rawData, chartKind);
  const layout = enrichLayout(
    plotlyJson.layout as Record<string, unknown> | undefined,
    chartKind,
    title,
    multiSeries
  );

  return (
    <div className={`chart-wrap chart-wrap-${chartKind}`}>
      <Plot
        data={data}
        layout={layout}
        config={{
          displayModeBar: false,
          displaylogo: false,
          responsive: true,
          staticPlot: false,
        }}
        style={{
          width: "100%",
          height: chartKind === "pie" ? "380px" : "420px",
        }}
        useResizeHandler
      />
    </div>
  );
}
