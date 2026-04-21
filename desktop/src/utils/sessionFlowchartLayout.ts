/**
 * Layout constants for the session flowchart SVG.
 */

export const COL_SPACING = 250;
export const NODE_W = 180;
export const NODE_H = 36;
export const NODE_RX = 7;
export const EDGE_GAP = 20;
export const ROW_H = NODE_H + EDGE_GAP;
export const DIAMOND_RX = 45;
export const DIAMOND_RY = 35;
export const DOT_R = 3.5;
export const MIN_SVG_W = 750;
export const PADDING = 40;
export const FONT = "-apple-system,'Segoe UI',sans-serif";

export function stageColors(status: string) {
  switch (status) {
    case "done":
      return { stroke: "#2ea043", fill: "rgba(46,160,67,0.08)", dot: "#2ea043", marker: "arr-g" };
    case "active":
      return { stroke: "#22c55e", fill: "rgba(34,197,94,0.1)", dot: "#22c55e", marker: "arr-a" };
    case "failed":
      return { stroke: "#f85149", fill: "rgba(248,81,73,0.08)", dot: "#f85149", marker: "arr-f" };
    default:
      return { stroke: "#30363d", fill: "#161b22", dot: "#30363d", marker: "arr" };
  }
}

export function slotRowCount(s: { work: unknown; gate: unknown; merge: unknown; cleanup: unknown; retryMerge: unknown; outcome: string }): number {
  let n = 0;
  if (s.work) n++;
  if (s.gate) n++;
  if (s.merge) n++;
  if (s.cleanup) n++;
  if (s.retryMerge) n++;
  if (s.outcome !== "active") n++;
  else n += 2;
  return Math.max(n, 2);
}

export function fanOutPath(diamondCx: number, diamondCy: number, colX: number, targetY: number): string {
  if (Math.abs(colX - diamondCx) < 5) {
    return `M${diamondCx} ${diamondCy + DIAMOND_RY} L${colX} ${targetY}`;
  }
  const vertexX = colX < diamondCx ? diamondCx - DIAMOND_RX : diamondCx + DIAMOND_RX;
  return `M${vertexX} ${diamondCy} L${colX} ${diamondCy} L${colX} ${targetY}`;
}
