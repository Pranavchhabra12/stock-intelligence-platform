// News-tone helpers shared by server and client components.

/** Diverging fill: grey at zero, deeper blue or orange the stronger the tone. */
export function toneFill(score: number): string {
  if (Math.abs(score) < 0.05) return "var(--tone-mid)";
  const strength = Math.round(35 + 65 * Math.min(1, Math.abs(score) / 0.8));
  const pole = score > 0 ? "var(--tone-pos)" : "var(--tone-neg)";
  return `color-mix(in oklab, ${pole} ${strength}%, var(--tone-mid))`;
}

export function toneWord(score: number): string {
  if (score > 0.15) return "positive";
  if (score < -0.15) return "negative";
  return "neutral";
}
