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
const TOOL_W      = 200;
const TOOL_X      = -320;
const TOOL_STEP   = 58;
const TOOL_H_EST  = 36;

const AGENT_W     = 300;
const AGENT_X     = 0;
const AGENT_Y0    = 130;
const AGENT_STEP  = 330;
const AGENT_H_EST = 120;

const INTG_W      = 210;
const INTG_X      = 410;
const INTG_STEP   = 128;

// Accent color per pipeline position
const ACCENT = ['#3B82F6', '#EF4444', '#F59E0B', '#10B981', '#8B5CF6'];
const accent = (i: number) => ACCENT[i % ACCENT.length] ?? '#3B82F6';

// ── Tool icon lookup ───────────────────────────────────────────────────────
const TOOL_ICONS: Record<string, string> = {
  get_case_details:               '📋',
  get_case_files:                 '📁',
  extract_document_text:          '🔬',
  verify_identity_document:       '🪪',
  compare_identity_documents:     '⚖️',
  risk_list_screening:            '🛡️',
  produce_adverse_media_analysis: '📰',
  escalate_to_human:              '🚨',
  get_case_stage_details:         '📊',
  get_case_stages:                '📊',
  analyze_override:               '🔍',
  search_internet:                '🌐',
};
const toolIcon = (name: string) => TOOL_ICONS[name] ?? '🔧';

// ── Output colors ──────────────────────────────────────────────────────────
const OUTPUT_COLORS: Record<string, string> = {
  MATCH: '#10B981', APPROVED: '#10B981', OK: '#10B981', CLEAR: '#10B981', VALID: '#10B981',
  MISMATCH: '#EF4444', ESCALATED: '#EF4444', NOK: '#EF4444', HIT: '#EF4444', INVALID: '#EF4444',
  PARTIAL_MATCH: '#F59E0B', PENDING_REVIEW: '#F59E0B', ERROR: '#F59E0B',
};
const oc = (v: string) => OUTPUT_COLORS[v] ?? '#5A6580';

// ── Integration type colors & icons ───────────────────────────────────────
const INTG_TYPE_COLOR: Record<string, string> = {
  database: '#F59E0B',
  storage:  '#06B6D4',
  api:      '#10B981',
  queue:    '#EF4444',
  llm:      '#8B5CF6',
  search:   '#3B82F6',
};
const TYPE_ICON: Record<string, string> = {
  database: '🗄️', storage: '☁️', api: '🌐', queue: '📨', llm: '🤖', search: '🔎',
};
const intgColor = (type: string) => INTG_TYPE_COLOR[type] ?? '#5A6580';

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
    position: { x: AGENT_X + AGENT_W / 2 - 46, y: 0 },
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
        stepIndex: i,
      },
    });

    // ── Tool nodes ───────────────────────────────────────────────────────
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
      edges.push({
        id: `tool-${nodeId}`,
        source: nodeId,
        target: agent.id,
        targetHandle: 'left',
        type: 'smoothstep',
        style: { stroke: accent(i), strokeWidth: 1.5, strokeDasharray: '4 3', opacity: 0.7 },
        animated: false,
      });
    });
  });

  // ── END ────────────────────────────────────────────────────────────────
  const endY = agentY(pipeline.length) + 20;
  nodes.push({
    id: '__end__',
    type: 'terminalNode',
    position: { x: AGENT_X + AGENT_W / 2 - 46, y: endY },
    data: { label: 'END', isStart: false },
  });

  // ── Auxiliary agents ───────────────────────────────────────────────────
  data.agents.filter(a => !pipeIds.has(a.id)).forEach((agent, i) => {
    nodes.push({
      id: agent.id,
      type: 'agentNode',
      position: { x: AGENT_X - 430, y: AGENT_Y0 + i * AGENT_STEP },
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

  // ── Pipeline edges ─────────────────────────────────────────────────────
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
      labelBgBorderRadius: 6,
    });
  }

  // ── Integration edges ──────────────────────────────────────────────────
  sortedIntg.forEach(intg => {
    const tgt = `__intg__${intg.name}`;
    intg.used_by.filter(id => pipeIds.has(id)).forEach(agentId => {
      edges.push({
        id: `intg-${agentId}-${intg.name}`,
        source: agentId, target: tgt,
        sourceHandle: 'right',
        type: 'smoothstep',
        style: { stroke: intgColor(intg.type), strokeWidth: 1.5, strokeDasharray: '5 4', opacity: 0.45 },
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
      display: 'inline-flex', alignItems: 'center', gap: 8,
      background: color + '18',
      border: `1.5px solid ${color}`,
      boxShadow: `0 0 20px ${color}50, 0 0 40px ${color}20`,
      borderRadius: 28, padding: '8px 20px',
      fontFamily: "'JetBrains Mono', monospace",
      fontSize: 11, fontWeight: 700, color,
      letterSpacing: '1.5px', whiteSpace: 'nowrap',
    }}>
      {!isStart && (
        <Handle type="target" position={Position.Top}
          style={{ background: color, border: 'none', width: 8, height: 8 }} />
      )}
      <span style={{
        width: 9, height: 9, borderRadius: '50%',
        background: color, display: 'inline-block',
        boxShadow: `0 0 8px ${color}`,
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
  const stepIndex   = data.stepIndex   as number | undefined;

  return (
    <div style={{
      width: AGENT_W,
      background: aux
        ? 'linear-gradient(145deg, #111827 0%, #0D1323 100%)'
        : 'linear-gradient(145deg, #1E2640 0%, #151C2E 60%, #111827 100%)',
      border: `1px solid ${accentColor}40`,
      borderRadius: 16,
      boxShadow: aux
        ? 'none'
        : `0 0 32px ${accentColor}28, 0 4px 24px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.05)`,
      overflow: 'hidden',
      fontFamily: "'DM Sans', sans-serif",
      opacity: aux ? 0.7 : 1,
    }}>
      {/* Colored header bar */}
      <div style={{
        height: 6,
        background: `linear-gradient(90deg, ${accentColor}cc 0%, ${accentColor}44 100%)`,
      }} />

      <div style={{ padding: '12px 15px 14px 14px' }}>
        <Handle id="top"    type="target" position={Position.Top}
          style={{ background: accentColor, border: `2px solid #0B0F1A`, width: 10, height: 10, top: -1 }} />
        <Handle id="bottom" type="source" position={Position.Bottom}
          style={{ background: accentColor, border: `2px solid #0B0F1A`, width: 10, height: 10 }} />
        <Handle id="left"   type="target" position={Position.Left}
          style={{ background: accentColor, border: '2px solid #0B0F1A', width: 9, height: 9 }} />
        <Handle id="right"  type="source" position={Position.Right}
          style={{ background: '#3B4F8A', border: '2px solid #0B0F1A', width: 9, height: 9 }} />

        {/* Step / aux badge */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
          {!aux && stepIndex !== undefined && (
            <span style={{
              background: accentColor + '22',
              border: `1px solid ${accentColor}55`,
              color: accentColor,
              borderRadius: 6,
              padding: '1px 7px',
              fontSize: 9, fontWeight: 700,
              fontFamily: "'JetBrains Mono', monospace",
              letterSpacing: '1px',
              flexShrink: 0,
            }}>
              STEP {String(stepIndex + 1).padStart(2, '0')}
            </span>
          )}
          {aux && (
            <span style={{
              fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '1px',
              color: '#8B5CF6',
              background: '#8B5CF622',
              border: '1px solid #8B5CF644',
              borderRadius: 6, padding: '1px 7px',
            }}>
              Auxiliary
            </span>
          )}
        </div>

        {/* Label + role */}
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 10 }}>
          <div style={{
            width: 8, height: 8, borderRadius: '50%',
            background: accentColor, marginTop: 6, flexShrink: 0,
            boxShadow: `0 0 8px ${accentColor}`,
          }} />
          <div>
            <div style={{ fontWeight: 700, fontSize: 14, color: '#E8ECF4', lineHeight: 1.3 }}>
              {label}
            </div>
            <div style={{ fontSize: 11, color: '#8892A8', lineHeight: 1.5, marginTop: 3 }}>
              {role}
            </div>
          </div>
        </div>

        {/* Output badges */}
        {outputs.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, paddingLeft: 16 }}>
            {outputs.map(out => (
              <span key={out} style={{
                background: oc(out) + '18', color: oc(out),
                border: `1px solid ${oc(out)}55`,
                borderRadius: 20, padding: '3px 9px',
                fontSize: 10, fontWeight: 700,
                fontFamily: "'JetBrains Mono', monospace",
                letterSpacing: '0.3px',
                boxShadow: `0 0 8px ${oc(out)}22`,
              }}>
                {out}
              </span>
            ))}
          </div>
        )}
      </div>
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
      background: `linear-gradient(135deg, ${accentColor}0d 0%, rgba(255,255,255,0.02) 100%)`,
      border: `1px solid ${accentColor}44`,
      borderRadius: 20,
      boxShadow: `0 0 14px ${accentColor}1a, 0 2px 8px rgba(0,0,0,0.3)`,
      padding: '7px 12px',
      display: 'flex', alignItems: 'center', gap: 8,
      fontFamily: "'JetBrains Mono', monospace",
    }}>
      <Handle type="source" position={Position.Right}
        style={{ background: accentColor, border: '2px solid #0B0F1A', width: 8, height: 8 }} />
      <span style={{ fontSize: 15, flexShrink: 0 }}>{toolIcon(label)}</span>
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
  const color    = intgColor(intgType);
  return (
    <div style={{
      width: INTG_W,
      background: `linear-gradient(135deg, ${color}0d 0%, #0B1120 100%)`,
      border: `1px solid ${color}33`,
      borderLeft: `3px solid ${color}99`,
      borderRadius: 12,
      boxShadow: `0 0 16px ${color}18, 0 2px 10px rgba(0,0,0,0.35)`,
      padding: '10px 14px',
      display: 'flex', alignItems: 'center', gap: 10,
      fontFamily: "'DM Sans', sans-serif",
    }}>
      <Handle type="target" position={Position.Left}
        style={{ background: color, border: '2px solid #0B0F1A', width: 8, height: 8 }} />
      <span style={{ fontSize: 20, flexShrink: 0 }}>{TYPE_ICON[intgType] ?? '🔌'}</span>
      <div>
        <div style={{ fontSize: 12, fontWeight: 600, color: '#C4D0E8' }}>{label}</div>
        <div style={{
          fontSize: 10, fontWeight: 600, textTransform: 'capitalize', marginTop: 2,
          color: color, opacity: 0.85,
        }}>
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

// ── Legend item ────────────────────────────────────────────────────────────
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
        background: 'rgba(13, 19, 35, 0.92)',
        border: '1px solid #2A3454',
        borderRadius: 28, padding: '7px 22px',
        backdropFilter: 'blur(16px)',
        boxShadow: '0 4px 28px rgba(0,0,0,0.6)',
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
        background: 'rgba(13, 19, 35, 0.88)',
        border: '1px solid #2A3454',
        borderRadius: 24, padding: '7px 22px',
        backdropFilter: 'blur(10px)',
      }}>
        <LegendItem color="#3B82F6" label="Pipeline flow" />
        <LegendItem color="#7C3AED" label="Tool call" />
        <LegendItem color="#4B6FA8" label="Integration" />
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
        <Background variant={BackgroundVariant.Dots} color="#1A2035" gap={24} size={1.2} />
        <Controls style={{
          background: '#1A2035', border: '1px solid #2A3454',
          borderRadius: 10, bottom: 64, left: 16,
        }} />
      </ReactFlow>
    </div>
  );
};

export default AgentNetwork;
