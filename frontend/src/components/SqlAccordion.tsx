import { useState } from "react";

export function SqlAccordion({ queries }: { queries: string[] }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="sql-accordion">
      <button type="button" className="sql-toggle" onClick={() => setOpen((v) => !v)}>
        {open ? "Hide queries used" : "Show queries used"}
      </button>
      {open ? (
        <div className="sql-list">
          {queries.map((sql, i) => (
            <pre key={i}>
              <code>{sql}</code>
            </pre>
          ))}
        </div>
      ) : null}
    </section>
  );
}
