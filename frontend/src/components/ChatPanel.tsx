import { useState } from "react";
import { askQuestion, type AskResponse } from "../api/client";
import { PlotlyChart } from "./PlotlyChart";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  meta?: AskResponse;
};

const SUGGESTIONS = [
  "Which wallets hold the most ETC?",
  "How is activity split across chains?",
  "Which ETH senders look most dormant?",
];

export function ChatPanel({ addresses = [] }: { addresses?: string[] }) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      text:
        "Ask a treasury question on the CRYPTO dataset. I’ll generate SQL via CRAFT, run it, and answer from the rows.",
    },
  ]);

  async function send(question: string) {
    const q = question.trim();
    if (!q || loading) return;
    setError(null);
    setLoading(true);
    setInput("");
    setMessages((prev) => [
      ...prev,
      { id: `u-${Date.now()}`, role: "user", text: q },
    ]);
    try {
      const result = await askQuestion({ question: q, addresses });
      setMessages((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          text: result.answer,
          meta: result,
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="chat-panel" aria-label="Ask CRYPTO">
      <header className="chat-header">
        <p className="risk-card-kicker">Ask CRYPTO</p>
        <h2>Treasury Q&amp;A</h2>
        <p className="chat-lede">
          Natural-language questions → CRAFT SQL → grounded answer. Read-only, rate-limited,
          LIMIT-scoped.
        </p>
      </header>

      <div className="chat-suggestions">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            className="chip"
            disabled={loading}
            onClick={() => send(s)}
          >
            {s}
          </button>
        ))}
      </div>

      <div className="chat-thread">
        {messages.map((m) => (
          <div key={m.id} className={`chat-bubble chat-${m.role}`}>
            <p>{m.text}</p>
            {m.meta?.notes ? <p className="chat-note">{m.meta.notes}</p> : null}
            {m.meta?.source ? (
              <p className="chat-source">
                Source: {m.meta.source}
                {m.meta.demo_mode ? " (demo)" : ""} · {m.meta.row_count} rows
              </p>
            ) : null}
            {m.meta?.plotly_json ? (
              <div className="chat-chart">
                <PlotlyChart
                  plotlyJson={m.meta.plotly_json}
                  kind={m.meta.chart_kind ?? "bar"}
                  title="Ask result"
                />
              </div>
            ) : null}
            {m.meta?.sql_used ? (
              <details className="chat-sql">
                <summary>SQL used</summary>
                <pre>
                  <code>{m.meta.sql_used}</code>
                </pre>
              </details>
            ) : null}
          </div>
        ))}
        {loading ? <p className="chat-pending">Running generate_sql → execute_query…</p> : null}
      </div>

      {error ? <p className="error">{error}</p> : null}

      <form
        className="chat-form"
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="e.g. Which wallets look most concentrated?"
          disabled={loading}
          aria-label="Ask a question"
        />
        <button type="submit" className="btn primary" disabled={loading || !input.trim()}>
          {loading ? "Asking…" : "Ask"}
        </button>
      </form>
    </section>
  );
}
