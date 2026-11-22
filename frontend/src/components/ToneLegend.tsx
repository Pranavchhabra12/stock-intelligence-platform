export default function ToneLegend() {
  return (
    <div className="tone-legend" aria-hidden="true">
      <span className="key"><i className="swatch" style={{ background: "var(--tone-pos)" }} />Positive</span>
      <span className="key"><i className="swatch" style={{ background: "var(--tone-mid)" }} />Neutral</span>
      <span className="key"><i className="swatch" style={{ background: "var(--tone-neg)" }} />Negative</span>
      <span className="key"><i className="swatch" style={{ boxShadow: "inset 0 0 0 1px var(--line)" }} />No news</span>
    </div>
  );
}
