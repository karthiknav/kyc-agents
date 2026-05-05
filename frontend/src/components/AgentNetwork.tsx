import React, { useMemo } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  BackgroundVariant,
  type Node,
  type Edge,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import networkData from '../agent-network.json' with { type: 'json' };

// ── Types ──────────────────────────────────────────────────────────────────
interface AgentRecord { id: string; label: string; role: string; tools: string[]; outputs: string[] }
interface IntegrationRecord { name: string; type: string; used_by: string[] }
interface FlowEdge { from: string; to: string; label?: string }
interface NetworkData {
  agents: AgentRecord[];
  flow: FlowEdge[];
  integrations: IntegrationRecord[];
  decision_logic: Record<string, string>;
  metadata: { framework: string; execution_model: string; entry_point: string };
}

const net = networkData as NetworkData;

// ── Layout ─────────────────────────────────────────────────────────────────
const TOOL_W      = 178;
const TOOL_X      = -270;   // right edge at -270+178 = -92, left edge of agent at 0 → 92px gap
const TOOL_STEP   = 58;
const TOOL_H_EST  = 36;

const AGENT_W     = 255;
const AGENT_X     = 0;
const AGENT_Y0    = 130;
const AGENT_STEP  = 290;
const AGENT_H_EST = 120;

const INTG_W      = 185;
const INTG_X      = 360;   // 105px gap from agent right edge
const INTG_STEP   = 128;

// Accent color per pipeline position
const ACCENT = ['#3B82F6', '#EF4444', '#F59E0B', '#10B981', '#8B5CF6'];
const accent = (i: number) => ACCENT[i % ACCENT.length] ?? '#3B82F6';

// ── Output colors ──────────────────────────────────────────────────────────
const OUTPUT_COLORS: Record<string, string> = {
  MATCH: '#10B981', APPROVED: '#10B981', OK: '#10B981', CLEAR: '#10B981', VALID: '#10B981',
  MISMATCH: '#EF4444', ESCALATED: '#EF4444', NOK: '#EF4444', HIT: '#EF4444', INVALID: '#EF4444',
  PARTIAL_MATCH: '#F59E0B', PENDING_REVIEW: '#F59E0B', ERROR: '#F59E0B',
};
const TYPE_ICON: Record<string, string> = {
  database: '🗄️', storage: '📦', api: '🌐', queue: '📨', llm: '🤖', search: '🔎',
};
const oc = (v: string) => OUTPUT_COLORS[v] ?? '#5A6580';

// ── Pipeline builder ───────────────────────────────────────────────────────
function buildPipeline(agents: AgentRecord[], flow: FlowEdge[]): AgentRecord[] {
  const byId = Object.fromEntries(agents.map(a => [a.id, a]));
  const next: Record<string, string> = {};
  let head: string | undefined;
  for (const e of flow) {
    if (e.from === 'START') head = e.to;
    else if (e.to !== 'END') next[e.from] = e.to;
  }
  if (!head) return agents;
  const order: string[] = [];
  let cur: string | undefined = head;
  while (cur && !order.includes(cur)) { order.push(cur); cur = next[cur]; }
  return order.map(id => byId[id]).filter((a): a is AgentRecord => !!a);
}

// ── Graph builder ──────────────────────────────────────────────────────────
function buildGraph(data: NetworkData) {
  const pipeline  = buildPipeline(data.agents, data.flow);
  const pipeIds   = new Set(pipeline.map(a => a.id));
  const idToIdx   = Object.fromEntries(pipeline.map((a, i) => [a.id, i]));
  const agentY    = (i: number) => AGENT_Y0 + i * AGENT_STEP;
  const agentCtrY = (i: number) => agentY(i) + AGENT_H_EST / 2;

  // Sort integrations by average agent-index centroid
  const sortedIntg = [...data.integrations].sort((a, b) => {
    const cent = (r: IntegrationRecord) => {
      const idxs = r.used_by.map(id => idToIdx[id] ?? 0);
      return idxs.length ? idxs.reduce((s, v) => s + v, 0) / idxs.length : 0;
    };
    return cent(a) - cent(b) || a.name.localeCompare(b.name);
  });

  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // ── START ──────────────────────────────────────────────────────────────
  nodes.push({
    id: '__start__',
    type: 'terminalNode',
    position: { x: AGENT_X + AGENT_W / 2 - 42, y: 0 },
    data: { label: 'START', isStart: true },
  });

  // ── Pipeline agents ────────────────────────────────────────────────────
  pipeline.forEach((agent, i) => {
    nodes.push({
      id: agent.id,
      type: 'agentNode',
      position: { x: AGENT_X, y: agentY(i) },
      data: {
        label: agent.label,
        role: agent.role,
        outputs: agent.outputs,
        accentColor: accent(i),
      },
    });

    // ── Tool nodes for this agent ────────────────────────────────────────
    const toolCount = agent.tools.length;
    const spread    = (toolCount - 1) * TOOL_STEP;
    const startY    = agentCtrY(i) - spread / 2 - TOOL_H_EST / 2;

    agent.tools.forEach((tool, j) => {
      const nodeId = `__tool__${agent.id}__${tool}`;
      nodes.push({
        id: nodeId,
        type: 'toolNode',
        position: { x: TOOL_X, y: startY + j * TOOL_STEP },
        data: { label: tool, accentColor: accent(i) },
      });
      // Tool → Agent edge (tool feeds into agent, left to right)
      edges.push({
        id: `tool-${nodeId}`,
        source: nodeId,
        target: agent.id,
        targetHandle: 'left',
        type: 'smoothstep',
        style: { stroke: accent(i), strokeWidth: 1.5, strokeDasharray: '4 3', opacity: 0.65 },
        animated: false,
      });
    });
  });

  // ── END ────────────────────────────────────────────────────────────────
  const endY = agentY(pipeline.length) + 20;
  nodes.push({
    id: '__end__',
    type: 'terminalNode',
    position: { x: AGENT_X + AGENT_W / 2 - 42, y: endY },
    data: { label: 'END', isStart: false },
  });

  // ── Auxiliary agents (not in flow) ─────────────────────────────────────
  data.agents.filter(a => !pipeIds.has(a.id)).forEach((agent, i) => {
    nodes.push({
      id: agent.id,
      type: 'agentNode',
      position: { x: AGENT_X - 380, y: AGENT_Y0 + i * AGENT_STEP },
      data: {
        label: agent.label,
        role: agent.role,
        outputs: agent.outputs,
        accentColor: '#8B5CF6',
        auxiliary: true,
      },
    });
  });

  // ── Integration nodes ──────────────────────────────────────────────────
  sortedIntg.forEach((intg, i) => {
    nodes.push({
      id: `__intg__${intg.name}`,
      type: 'integrationNode',
      position: { x: INTG_X, y: AGENT_Y0 + i * INTG_STEP },
      data: { label: intg.name, intgType: intg.type },
    });
  });

  // ── Pipeline edges (animated blue) ────────────────────────────────────
  const pipeNodes = ['__start__', ...pipeline.map(a => a.id), '__end__'];
  for (let i = 0; i < pipeNodes.length - 1; i++) {
    const src = pipeNodes[i]!;
    const tgt = pipeNodes[i + 1]!;
    const meta = data.flow.find(e =>
      (e.from === 'START' ? '__start__' : e.from) === src &&
      (e.to   === 'END'   ? '__end__'   : e.to)   === tgt
    );
    edges.push({
      id: `pipe-${src}-${tgt}`,
      source: src, target: tgt,
      sourceHandle: src === '__start__' ? null : 'bottom',
      targetHandle: tgt === '__end__'   ? null : 'top',
      type: 'smoothstep',
      animated: true,
      label: meta?.label,
      style: { stroke: '#3B82F6', strokeWidth: 2.5 },
      labelStyle: { fill: '#5A6580', fontSize: 9, fontFamily: "'JetBrains Mono', monospace" },
      labelBgStyle: { fill: '#0D1323', fillOpacity: 0.95 },
      labelBgPadding: [5, 3] as [number, number],
      labelBgBorderRadius: 4,
    });
  }

  // ── Integration edges (dashed slate) ──────────────────────────────────
  sortedIntg.forEach(intg => {
    const tgt = `__intg__${intg.name}`;
    intg.used_by.filter(id => pipeIds.has(id)).forEach(agentId => {
      edges.push({
        id: `intg-${agentId}-${intg.name}`,
        source: agentId, target: tgt,
        sourceHandle: 'right',
        type: 'smoothstep',
        style: { stroke: '#3B4F8A', strokeWidth: 1.5, strokeDasharray: '5 4', opacity: 0.7 },
        animated: false,
      });
    });
  });

  return { nodes, edges };
}

// ── Node: Terminal (START / END) ───────────────────────────────────────────
function TerminalNode({ data }: NodeProps) {
  const isStart = data.isStart as boolean;
  const label   = data.label   as string;
  const color   = isStart ? '#06B6D4' : '#F59E0B';
  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: 7,
      background: color + '18',
      border: `1.5px solid ${color}`,
      boxShadow: `0 0 16px ${color}44`,
      borderRadius: 24, padding: '6px 16px',
      fontFamily: "'JetBrains Mono', monospace",
      fontSize: 11, fontWeight: 700, color,
      letterSpacing: '1px', whiteSpace: 'nowrap',
    }}>
      {!isStart && (
        <Handle type="target" position={Position.Top}
          style={{ background: color, border: 'none', width: 8, height: 8 }} />
      )}
      <span style={{
        width: 7, height: 7, borderRadius: '50%',
        background: color, display: 'inline-block',
        boxShadow: `0 0 6px ${color}`,
      }} />
      {label}
      {isStart && (
        <Handle type="source" position={Position.Bottom}
          style={{ background: color, border: 'none', width: 8, height: 8 }} />
      )}
    </div>
  );
}

// ── Node: Agent card ───────────────────────────────────────────────────────
function AgentNode({ data }: NodeProps) {
  const label       = data.label       as string;
  const role        = data.role        as string;
  const outputs     = data.outputs     as string[];
  const accentColor = data.accentColor as string;
  const aux         = data.auxiliary   as boolean | undefined;

  return (
    <div style={{
      width: AGENT_W,
      background: aux
        ? 'linear-gradient(135deg, #111827 0%, #0D1323 100%)'
        : 'linear-gradient(135deg, #1A2035 0%, #151C2E 100%)',
      border: `1px solid ${accentColor}55`,
      borderLeft: `3px solid ${accentColor}`,
      borderRadius: 10,
      boxShadow: aux
        ? 'none'
        : `0 0 20px ${accentColor}18, inset 0 1px 0 rgba(255,255,255,0.04)`,
      padding: '13px 15px 13px 13px',
      fontFamily: "'DM Sans', sans-serif",
      opacity: aux ? 0.7 : 1,
    }}>
      <Handle id="top"    type="target" position={Position.Top}
        style={{ background: '#3B82F6', border: '2px solid #0B0F1A', width: 10, height: 10 }} />
      <Handle id="bottom" type="source" position={Position.Bottom}
        style={{ background: '#3B82F6', border: '2px solid #0B0F1A', width: 10, height: 10 }} />
      <Handle id="left"   type="target" position={Position.Left}
        style={{ background: accentColor, border: '2px solid #0B0F1A', width: 9, height: 9 }} />
      <Handle id="right"  type="source" position={Position.Right}
        style={{ background: '#3B4F8A', border: '2px solid #0B0F1A', width: 9, height: 9 }} />

      {aux && (
        <div style={{
          fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '1px',
          color: '#8B5CF6', marginBottom: 5,
        }}>
          Auxiliary
        </div>
      )}

      <div style={{
        display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 8,
      }}>
        <div style={{
          width: 6, height: 6, borderRadius: '50%',
          background: accentColor, marginTop: 5, flexShrink: 0,
          boxShadow: `0 0 6px ${accentColor}`,
        }} />
        <div>
          <div style={{ fontWeight: 700, fontSize: 13, color: '#E8ECF4', lineHeight: 1.3 }}>
            {label}
          </div>
          <div style={{ fontSize: 11, color: '#8892A8', lineHeight: 1.5, marginTop: 3 }}>
            {role}
          </div>
        </div>
      </div>

      {outputs.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, paddingLeft: 14 }}>
          {outputs.map(out => (
            <span key={out} style={{
              background: oc(out) + '1a', color: oc(out),
              border: `1px solid ${oc(out)}55`,
              borderRadius: 4, padding: '2px 7px',
              fontSize: 10, fontWeight: 700,
              fontFamily: "'JetBrains Mono', monospace",
              letterSpacing: '0.3px',
            }}>
              {out}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Node: Tool ─────────────────────────────────────────────────────────────
function ToolNode({ data }: NodeProps) {
  const label       = data.label       as string;
  const accentColor = data.accentColor as string;
  return (
    <div style={{
      width: TOOL_W,
      background: 'linear-gradient(135deg, #0E0B1F 0%, #130F2A 100%)',
      border: `1px solid ${accentColor}44`,
      borderRight: `2px solid ${accentColor}`,
      borderRadius: 6,
      boxShadow: `0 0 12px ${accentColor}22`,
      padding: '7px 10px',
      display: 'flex', alignItems: 'center', gap: 7,
      fontFamily: "'JetBrains Mono', monospace",
    }}>
      <Handle type="source" position={Position.Right}
        style={{ background: accentColor, border: '2px solid #0B0F1A', width: 8, height: 8 }} />
      <span style={{
        fontSize: 13, color: accentColor, flexShrink: 0, opacity: 0.8,
      }}>⚙</span>
      <span style={{
        fontSize: 10.5, color: '#A5B4FC', lineHeight: 1.4,
        wordBreak: 'break-all',
      }}>
        {label}
      </span>
    </div>
  );
}

// ── Node: Integration ──────────────────────────────────────────────────────
function IntegrationNode({ data }: NodeProps) {
  const label    = data.label    as string;
  const intgType = data.intgType as string;
  return (
    <div style={{
      width: INTG_W,
      background: 'linear-gradient(135deg, #0B1120 0%, #0D1628 100%)',
      border: '1px solid #1E3A5F',
      borderLeft: '2px solid #3B82F655',
      borderRadius: 8,
      boxShadow: '0 0 10px #3B82F610',
      padding: '9px 12px',
      display: 'flex', alignItems: 'center', gap: 9,
      fontFamily: "'DM Sans', sans-serif",
    }}>
      <Handle type="target" position={Position.Left}
        style={{ background: '#3B4F8A', border: '2px solid #0B0F1A', width: 8, height: 8 }} />
      <span style={{ fontSize: 16, flexShrink: 0 }}>{TYPE_ICON[intgType] ?? '🔌'}</span>
      <div>
        <div style={{ fontSize: 12, fontWeight: 500, color: '#C4D0E8' }}>{label}</div>
        <div style={{ fontSize: 10, color: '#3B4F8A', textTransform: 'capitalize', marginTop: 1 }}>
          {intgType}
        </div>
      </div>
    </div>
  );
}

// ── Pill badge ─────────────────────────────────────────────────────────────
function Pill({ color, children }: { color: string; children: React.ReactNode }) {
  return (
    <span style={{
      background: color + '20', color,
      border: `1px solid ${color}55`,
      borderRadius: 20, padding: '2px 10px',
      fontSize: 11, fontWeight: 500,
    }}>
      {children}
    </span>
  );
}

// ── Legend dot ─────────────────────────────────────────────────────────────
function LegendItem({ color, label }: { color: string; label: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <span style={{
        width: 20, height: 2,
        background: color,
        display: 'inline-block',
        borderRadius: 1,
      }} />
      <span style={{ fontSize: 10, color: '#5A6580' }}>{label}</span>
    </div>
  );
}

// ── Node type registry ─────────────────────────────────────────────────────
const nodeTypes = {
  terminalNode:    TerminalNode,
  agentNode:       AgentNode,
  toolNode:        ToolNode,
  integrationNode: IntegrationNode,
};

// ── Main component ─────────────────────────────────────────────────────────
const AgentNetwork: React.FC = () => {
  const { nodes, edges } = useMemo(() => buildGraph(net), []);

  return (
    <div style={{ height: 'calc(100vh - 60px)', background: '#0B0F1A', position: 'relative' }}>

      {/* Top info bar */}
      <div style={{
        position: 'absolute', top: 14, left: '50%', transform: 'translateX(-50%)',
        zIndex: 10,
        display: 'flex', alignItems: 'center', gap: 8,
        background: 'rgba(13, 19, 35, 0.9)',
        border: '1px solid #2A3454',
        borderRadius: 24, padding: '6px 20px',
        backdropFilter: 'blur(12px)',
        boxShadow: '0 4px 24px rgba(0,0,0,0.5)',
        whiteSpace: 'nowrap',
      }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: '#E8ECF4', letterSpacing: '0.3px' }}>
          Agent Network
        </span>
        <span style={{ width: 1, height: 14, background: '#2A3454', display: 'inline-block', margin: '0 2px' }} />
        <Pill color="#8B5CF6">{net.metadata.framework}</Pill>
        <Pill color="#3B82F6">{net.metadata.execution_model}</Pill>
        <span style={{ fontSize: 11, color: '#5A6580', fontFamily: "'JetBrains Mono', monospace" }}>
          {net.metadata.entry_point}
        </span>
      </div>

      {/* Bottom legend */}
      <div style={{
        position: 'absolute', bottom: 16, left: '50%', transform: 'translateX(-50%)',
        zIndex: 10,
        display: 'flex', alignItems: 'center', gap: 16,
        background: 'rgba(13, 19, 35, 0.85)',
        border: '1px solid #2A3454',
        borderRadius: 20, padding: '6px 20px',
        backdropFilter: 'blur(8px)',
      }}>
        <LegendItem color="#3B82F6" label="Pipeline flow" />
        <LegendItem color="#7C3AED" label="Tool call" />
        <LegendItem color="#3B4F8A" label="Integration" />
      </div>

      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable={false}
        style={{ background: '#0B0F1A' }}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} color="#1A2035" gap={22} size={1} />
        <Controls style={{
          background: '#1A2035', border: '1px solid #2A3454',
          borderRadius: 8, bottom: 60, left: 16,
        }} />
      </ReactFlow>
    </div>
  );
};

export default AgentNetwork;
