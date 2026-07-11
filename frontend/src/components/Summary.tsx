export function Summary({ text }: { text: string }) {
  return (
    <section className="summary-block">
      <h2>Executive summary</h2>
      <p>{text}</p>
    </section>
  );
}
