// Board curves are [day, % since that line's own start]. Lines start on different days (the real accounts on
// 9 Nov, the league on 19 Nov, Markus's account when he opens it), so two lines are only compared over the
// days they share (front-end audit, 21 Nov 2026). One place for that arithmetic.

export type Curve = [string, number][];

/** Return in % from the first point on or after `day` to the last point; null if no point that late. */
export function returnSince(curve: Curve, day: string): number | null {
  const i = curve.findIndex(([d]) => d >= day);
  if (i < 0 || !curve.length) return null;
  const from = 1 + curve[i][1] / 100, to = 1 + curve[curve.length - 1][1] / 100;
  return from > 0 ? 100 * (to / from - 1) : null;
}

/** The first day every given curve has reached (the start of their shared window); null if any is empty. */
export function sharedStart(...curves: Curve[]): string | null {
  if (!curves.length || curves.some((c) => !c.length)) return null;
  return curves.map((c) => c[0][0]).sort().at(-1)!;
}

/** The curve re-based to 0% on `day` (points before it dropped). */
export function rebase(curve: Curve, day: string): Curve {
  const i = curve.findIndex(([d]) => d >= day);
  if (i < 0) return [];
  const from = 1 + curve[i][1] / 100;
  return curve.slice(i).map(([d, v]) => [d, 100 * ((1 + v / 100) / from - 1)]);
}
