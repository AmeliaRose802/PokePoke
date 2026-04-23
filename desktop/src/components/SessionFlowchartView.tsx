/**
 * SessionFlowchartView - session-wide pipeline flowchart.
 * SVG primitive components are in SessionFlowchartSvg.tsx.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { AgentInfo, SessionStats } from "../types";
import { useBridge } from "../useBridge";
import { buildSessionFlowchart, type PipelineStage } from "../utils/sessionFlowchartData";
import { COL_SPACING, EDGE_GAP, fanOutPath, FONT, MIN_SVG_W, PADDING, ROW_H, slotRowCount } from "../utils/sessionFlowchartLayout";
import { Diamond, SlotColumn, SvgDefs } from "./SessionFlowchartSvg";

interface Props {
  agents: AgentInfo[];
  stats: SessionStats | null;
  agentName: string;
  currentSessionId: string | null;
  activeModel: string | null;
}

export function SessionFlowchartView({ agents, stats, agentName, currentSessionId, activeModel }: Props) {
  const { getAgentDetail } = useBridge();
  const canvasRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef({ x: 0, y: 0, sl: 0, st: 0 });
  const [selectedStage, setSelectedStage] = useState<PipelineStage | null>(null);
  const [selectedStageDetail, setSelectedStageDetail] = useState<AgentInfo | null>(null);
  const data = useMemo(() => buildSessionFlowchart(agents, currentSessionId), [agents, currentSessionId]);
  const { DIAMOND_RY } = { DIAMOND_RY: 35 };

  const layout = useMemo(() => {
    const cc = data.completed.length, ac = data.active.length;
    const svgW = Math.max(MIN_SVG_W, Math.max(cc, ac, 1) * COL_SPACING + PADDING * 2);
    const cx = svgW / 2, orchY = 55;
    const cStartY = orchY + DIAMOND_RY + EDGE_GAP + 18;
    const cColXs = data.completed.map((_, i) => cx - cc * COL_SPACING / 2 + COL_SPACING / 2 + i * COL_SPACING);
    const cHeight = data.completed.reduce((m, s) => Math.max(m, slotRowCount(s)), 0) * ROW_H + 30;
    const sepY = cc > 0 ? cStartY + cHeight + 30 : orchY + DIAMOND_RY + 60;
    const aOrchY = sepY + 50;
    const aStartY = aOrchY + DIAMOND_RY + EDGE_GAP + 18;
    const aColXs = data.active.map((_, i) => cx - ac * COL_SPACING / 2 + COL_SPACING / 2 + i * COL_SPACING);
    const aHeight = data.active.reduce((m, s) => Math.max(m, slotRowCount(s)), 0) * ROW_H + 40;
    const svgH = ac > 0 ? aStartY + aHeight : sepY + 80;
    return { svgW, svgH, cx, orchY, cStartY, cColXs, sepY, aOrchY, aStartY, aColXs };
  }, [data, DIAMOND_RY]);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest("[data-step]")) return;
    setDragging(true);
    const el = canvasRef.current!;
    dragRef.current = { x: e.pageX, y: e.pageY, sl: el.scrollLeft, st: el.scrollTop };
  }, []);
  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging) return;
    const el = canvasRef.current!;
    const d = dragRef.current;
    el.scrollLeft = d.sl - (e.pageX - d.x);
    el.scrollTop = d.st - (e.pageY - d.y);
  }, [dragging]);
  const onMouseUp = useCallback(() => setDragging(false), []);
  const handleStageClick = useCallback((stage: PipelineStage) => {
    if (!stage.agentId) return;
    setSelectedStage((prev) => (prev?.agentId === stage.agentId ? null : stage));
  }, []);
  const closeLog = useCallback(() => setSelectedStage(null), []);

  useEffect(() => {
    let cancelled = false;
    const agentId = selectedStage?.agentId ?? "";
    if (!agentId) {
      return () => {
        cancelled = true;
      };
    }

    async function loadStageDetail() {
      const detail = await getAgentDetail(agentId);
      if (!cancelled) {
        setSelectedStageDetail(detail);
      }
    }

    loadStageDetail().catch(() => {
      if (!cancelled) {
        setSelectedStageDetail(null);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [getAgentDetail, selectedStage?.agentId]);

  const selectedLogs = useMemo(() => {
    if (selectedStageDetail && selectedStageDetail.agent_id === selectedStage?.agentId) {
      if (selectedStageDetail.log_lines?.length) return selectedStageDetail.log_lines;
      if (selectedStageDetail.recent_logs?.length) return selectedStageDetail.recent_logs;
    }
    return selectedStage?.logs ?? [];
  }, [selectedStage, selectedStageDetail]);

  const elapsed = stats?.elapsed_time ?? 0;
  const elapsedStr = [Math.floor(elapsed / 3600), Math.floor((elapsed % 3600) / 60), Math.floor(elapsed % 60)].map((n) => n.toString().padStart(2, "0")).join(":");
  const totalTokens = stats?.agent_stats ? ((stats.agent_stats.input_tokens + stats.agent_stats.output_tokens) / 1000).toFixed(1) + "k" : "0";

  return (
    <div className="sf-shell">
      <div className={`sf-log-backdrop${selectedStage ? " open" : ""}`} onClick={closeLog} />
      <div className={`sf-log-panel${selectedStage ? " open" : ""}`}>
        <div className="sf-log-header">
          <span className="sf-log-title">{selectedStage?.label ?? "Logs"}</span>
          <span className="sf-log-step">{selectedStage?.agentId ?? ""}</span>
          <button className="sf-log-close" onClick={closeLog}>✕</button>
        </div>
        <div className="sf-log-body">
          {selectedStage && !selectedStage.agentId ? (
            <span className="sf-log-empty-msg">No logs available for this step.</span>
          ) : selectedLogs.length === 0 ? (
            <span className="sf-log-empty-msg">No logs available for this step.</span>
          ) : (
            selectedLogs.map((line, i) => <div key={i}>{line}</div>)
          )}
        </div>
      </div>
      <div className="sf-info-bar">
        <span>Agent: {agentName}</span><span>Elapsed: {elapsedStr}</span><span>Model: {activeModel ?? "—"}</span>
        <span>Items: {data.merged} merged{data.deferred > 0 ? ` · ${data.deferred} deferred` : ""}{data.decomposed > 0 ? ` · ${data.decomposed} decomposed` : ""}{` · ${data.activeCount} active`}</span>
      </div>
      <div className="sf-legend-bar">
        <div className="sf-legend-item"><div className="sf-legend-sw sf-sw-done" />Done</div>
        <div className="sf-legend-item"><div className="sf-legend-sw sf-sw-active" />Active</div>
        <div className="sf-legend-item"><div className="sf-legend-sw sf-sw-pending" />Pending</div>
        <div className="sf-legend-item"><div className="sf-legend-sw sf-sw-failed" />Failed</div>
        <div className="sf-legend-item"><div className="sf-legend-sw sf-sw-warn" />Dirty merge</div>
        <div className="sf-legend-item"><div className="sf-legend-sw sf-sw-decomposed" />Decomposed</div>
        <div className="sf-legend-item"><div className="sf-legend-sw sf-sw-maint" />Maintenance</div>
        <span className="sf-legend-hint">drag to pan</span>
      </div>
      <div className={`sf-canvas${dragging ? " sf-canvas--dragging" : ""}`} ref={canvasRef} onMouseDown={onMouseDown} onMouseMove={onMouseMove} onMouseUp={onMouseUp} onMouseLeave={onMouseUp}>
        <div className="sf-canvas-inner">
          <svg className="sf-svg" width={layout.svgW} height={layout.svgH} xmlns="http://www.w3.org/2000/svg">
            <SvgDefs />
            {data.completed.length > 0 && <g opacity={0.4}>
              <Diamond cx={layout.cx} cy={layout.orchY} label="Orchestrator" sub="schedule / drain / maintain" stroke="#58a6ff" fill="rgba(88,166,255,0.08)" />
              {layout.cColXs.map((colX, i) => <path key={`cf-${i}`} d={fanOutPath(layout.cx, layout.orchY, colX, layout.cStartY)} fill="none" stroke="#2ea043" strokeWidth={1.8} markerEnd="url(#arr-g)" />)}
              {data.completed.map((slot, i) => <SlotColumn key={slot.id} slot={slot} centerX={layout.cColXs[i]} startY={layout.cStartY} onStageClick={handleStageClick} />)}
            </g>}
            {data.active.length > 0 && <>
              <line x1={20} y1={layout.sepY} x2={layout.svgW - 20} y2={layout.sepY} stroke="#30363d" strokeWidth={1} strokeDasharray="6 4" />
              <text x={30} y={layout.sepY + 18} fontSize={11} fill="#3fb950" fontWeight={600} letterSpacing={1.5} fontFamily={FONT}>ACTIVE</text>
              <Diamond cx={layout.cx} cy={layout.aOrchY} label="Orchestrator" sub={`${data.activeCount} slots active`} stroke="#22c55e" fill="rgba(34,197,94,0.08)" />
              {layout.aColXs.map((colX, i) => <path key={`af-${i}`} d={fanOutPath(layout.cx, layout.aOrchY, colX, layout.aStartY)} fill="none" stroke="#2ea043" strokeWidth={1.8} markerEnd="url(#arr-g)" />)}
              {data.active.map((slot, i) => <SlotColumn key={slot.id} slot={slot} centerX={layout.aColXs[i]} startY={layout.aStartY} onStageClick={handleStageClick} />)}
            </>}
            {data.completed.length === 0 && data.active.length === 0 && <>
              <Diamond cx={layout.cx} cy={layout.orchY} label="Orchestrator" sub="waiting for work items…" stroke="#58a6ff" fill="rgba(88,166,255,0.08)" />
              <text x={layout.cx} y={200} textAnchor="middle" fontSize={13} fill="#8b949e" fontFamily={FONT}>No pipeline activity yet.</text>
            </>}
          </svg>
        </div>
      </div>
      <div className="sf-footer">
        <div><span className="sf-footer-label">Uptime</span><span className="sf-footer-value">{elapsedStr}</span></div>
        <div><span className="sf-footer-label">Merged</span><span className="sf-footer-value">{data.merged}</span></div>
        <div><span className="sf-footer-label">Active</span><span className="sf-footer-value">{data.activeCount}</span></div>
        {data.deferred > 0 && <div><span className="sf-footer-label">Deferred</span><span className="sf-footer-value">{data.deferred}</span></div>}
        {data.decomposed > 0 && <div><span className="sf-footer-label">Decomposed</span><span className="sf-footer-value">{data.decomposed}</span></div>}
        <div><span className="sf-footer-label">Model</span><span className="sf-footer-value sf-footer-mono">{activeModel ?? "—"}</span></div>
        <div><span className="sf-footer-label">Tokens</span><span className="sf-footer-value">{totalTokens}</span></div>
        <div><span className="sf-footer-label">Workers</span><span className="sf-footer-value">{data.activeCount || data.completed.length}</span></div>
      </div>
    </div>
  );
}
