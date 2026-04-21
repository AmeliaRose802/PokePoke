/**
 * SVG primitive components for the session flowchart.
 * Only React components are exported (react-refresh safe).
 * Constants and helpers live in utils/sessionFlowchartLayout.ts.
 */

import type { FlowchartSlot, PipelineStage } from "../utils/sessionFlowchartData";
import { DOT_R, EDGE_GAP, FONT, NODE_H, NODE_RX, NODE_W, ROW_H, stageColors } from "../utils/sessionFlowchartLayout";

export function SvgDefs() {
  const markers = [
    { id: "arr", color: "#484f58" }, { id: "arr-g", color: "#2ea043" },
    { id: "arr-a", color: "#22c55e" }, { id: "arr-f", color: "#f85149" },
    { id: "arr-w", color: "#d29922" }, { id: "arr-p", color: "#a371f7" },
    { id: "arr-m", color: "#79c0ff" },
  ];
  return (<defs>{markers.map((m) => (
    <marker key={m.id} id={m.id} viewBox="0 0 10 8" refX="9" refY="4" markerWidth="6" markerHeight="5" orient="auto-start-reverse"><path d="M0 0L10 4L0 8z" fill={m.color} /></marker>
  ))}</defs>);
}

export function Diamond({ cx, cy, label, sub, stroke, fill }: { cx: number; cy: number; label: string; sub?: string; stroke: string; fill: string }) {
  const rx = 45, ry = 35;
  const pts = `${cx},${cy - ry} ${cx + rx},${cy} ${cx},${cy + ry} ${cx - rx},${cy}`;
  return (<g>
    <polygon points={pts} fill={fill} stroke={stroke} strokeWidth={2} />
    <text x={cx} y={cy - 3} textAnchor="middle" fill={stroke} fontSize={11} fontWeight={600} fontFamily={FONT}>{label}</text>
    {sub && <text x={cx} y={cy + 10} textAnchor="middle" fill={stroke} fontSize={8} fontFamily={FONT}>{sub}</text>}
  </g>);
}

export function SlotNode({ x, y, stage, slotId, onClick }: { x: number; y: number; stage: PipelineStage; slotId?: string; onClick?: () => void }) {
  const c = stageColors(stage.status);
  const isActive = stage.status === "active";
  return (<g onClick={onClick} className={`sf-node${onClick ? " sf-node--clickable" : ""}${isActive ? " sf-node-glow" : ""}`} data-step={stage.label}>
    <rect x={x} y={y} width={NODE_W} height={NODE_H} rx={NODE_RX} fill={c.fill} stroke={c.stroke} strokeWidth={isActive ? 1.8 : 1.4} />
    <circle cx={x + 16} cy={y + NODE_H / 2} r={DOT_R} fill={c.dot}>{isActive && <animate attributeName="opacity" values="1;0.35;1" dur="1.5s" repeatCount="indefinite" />}</circle>
    <text x={x + 26} y={y + NODE_H / 2 - 5} fontSize={10.5} fill="#e6edf3" fontFamily={FONT}>{stage.label}</text>
    <text x={x + 26} y={y + NODE_H / 2 + 8} fontSize={9} fill={c.dot} fontFamily={FONT}>{stage.detail}</text>
    {slotId && <text x={x + NODE_W - 10} y={y + NODE_H / 2 + 3} textAnchor="end" fontSize={9.5} fontWeight={700} fill="#8b949e" fontFamily={FONT}>{slotId}</text>}
  </g>);
}

export function VEdge({ x, y1, y2, status }: { x: number; y1: number; y2: number; status: string }) {
  const c = stageColors(status);
  return <path d={`M${x} ${y1} L${x} ${y2}`} fill="none" stroke={c.stroke} strokeWidth={1.5} markerEnd={`url(#${c.marker})`} />;
}

function RetryArc({ x, y1, y2, label }: { x: number; y1: number; y2: number; label?: string }) {
  const cx = x + 25;
  return (<g><path d={`M${x} ${y2} C${cx} ${y2} ${cx} ${y1 + 8} ${x} ${y1}`} fill="none" stroke="#484f58" strokeWidth={1.2} strokeDasharray="4 3" markerEnd="url(#arr)" /><text x={cx + 5} y={(y1 + y2) / 2} fontSize={8} fill="#8b949e" fontFamily={FONT}>{label ?? "retry"}</text></g>);
}

function OutcomeBadge({ cx, cy, outcome }: { cx: number; cy: number; outcome: string }) {
  if (outcome === "success") return <g><circle cx={cx} cy={cy} r={10} fill="rgba(46,160,67,0.1)" stroke="#2ea043" strokeWidth={1.2} /><text x={cx} y={cy + 4} textAnchor="middle" fontSize={11} fill="#3fb950" fontFamily={FONT}>✓</text></g>;
  if (outcome === "deferred") return <g><rect x={cx - 60} y={cy - 14} width={120} height={28} rx={14} fill="rgba(248,81,73,0.06)" stroke="#f85149" strokeWidth={1.2} strokeDasharray="5 2.5" /><text x={cx} y={cy + 4} textAnchor="middle" fontSize={9} fill="#f85149" fontFamily={FONT}>Deferred</text></g>;
  if (outcome === "decomposed") return <g><rect x={cx - 60} y={cy - 14} width={120} height={28} rx={14} fill="rgba(163,113,247,0.06)" stroke="#a371f7" strokeWidth={1.2} strokeDasharray="5 2.5" /><text x={cx} y={cy + 4} textAnchor="middle" fontSize={9} fill="#a371f7" fontFamily={FONT}>◇ Decomposed</text></g>;
  if (outcome === "failed") return <g><circle cx={cx} cy={cy} r={10} fill="rgba(248,81,73,0.08)" stroke="#f85149" strokeWidth={1.2} /><text x={cx} y={cy + 4} textAnchor="middle" fontSize={11} fill="#f85149" fontFamily={FONT}>✗</text></g>;
  return null;
}

function PendingPlaceholder({ x, y, label }: { x: number; y: number; label: string }) {
  return <g opacity={0.25}><rect x={x} y={y} width={130} height={24} rx={5} fill="#161b22" stroke="#30363d" strokeWidth={1} /><text x={x + 12} y={y + 15} fontSize={8.5} fill="#8b949e" fontFamily={FONT}>{label}</text></g>;
}

export function SlotColumn({ slot, centerX, startY, onStageClick }: { slot: FlowchartSlot; centerX: number; startY: number; onStageClick: (stage: PipelineStage) => void }) {
  const nodeX = centerX - NODE_W / 2;
  const elements: React.ReactElement[] = [];
  let y = startY;
  if (slot.work) {
    elements.push(<SlotNode key="w" x={nodeX} y={y} stage={slot.work} slotId={slot.shortId} onClick={() => onStageClick(slot.work!)} />);
    if (slot.gate || slot.merge) elements.push(<VEdge key="ew" x={centerX} y1={y + NODE_H} y2={y + NODE_H + EDGE_GAP - 2} status={slot.work.status === "done" ? "done" : "active"} />);
    if (slot.hasRetryArc && slot.gate) elements.push(<RetryArc key="ra" x={nodeX + NODE_W} y1={y + NODE_H / 2} y2={y + ROW_H + NODE_H / 2} label={slot.attempts > 1 ? `×${slot.attempts}` : "retry"} />);
    y += ROW_H;
  }
  if (slot.gate) {
    elements.push(<SlotNode key="g" x={nodeX} y={y} stage={slot.gate} onClick={() => onStageClick(slot.gate!)} />);
    if (slot.merge || slot.cleanup) { const es = slot.gate.status === "done" ? "done" : slot.gate.status === "failed" ? "failed" : ""; elements.push(<VEdge key="eg" x={centerX} y1={y + NODE_H} y2={y + NODE_H + EDGE_GAP - 2} status={es} />); }
    y += ROW_H;
  }
  if (slot.merge) { elements.push(<SlotNode key="m" x={nodeX} y={y} stage={slot.merge} onClick={() => onStageClick(slot.merge!)} />); y += ROW_H; }
  if (slot.cleanup) {
    elements.push(<SlotNode key="cl" x={nodeX} y={y} stage={slot.cleanup} onClick={() => onStageClick(slot.cleanup!)} />);
    if (slot.retryMerge) elements.push(<VEdge key="ecl" x={centerX} y1={y + NODE_H} y2={y + NODE_H + EDGE_GAP - 2} status="done" />);
    y += ROW_H;
  }
  if (slot.retryMerge) { elements.push(<SlotNode key="rm" x={nodeX} y={y} stage={slot.retryMerge} onClick={() => onStageClick(slot.retryMerge!)} />); y += ROW_H; }
  if (slot.outcome !== "active") {
    elements.push(<VEdge key="eo" x={centerX} y1={y - EDGE_GAP + NODE_H} y2={y + 2} status="done" />);
    elements.push(<OutcomeBadge key="ob" cx={centerX} cy={y + 12} outcome={slot.outcome} />);
  } else {
    if (!slot.gate) { elements.push(<g key="pg" opacity={0.25}><VEdge x={centerX} y1={y - EDGE_GAP + NODE_H} y2={y} status="" /><PendingPlaceholder x={nodeX + 25} y={y + 2} label="gate" /></g>); y += NODE_H + 8; }
    if (!slot.merge) { elements.push(<g key="pm" opacity={0.25}><VEdge x={centerX} y1={y - 6} y2={y + 6} status="" /><PendingPlaceholder x={nodeX + 25} y={y + 8} label="🔒 merge…" /></g>); }
  }
  return <g data-lane={slot.shortId}>{elements}</g>;
}
