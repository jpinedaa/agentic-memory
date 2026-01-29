import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import { useAgentStore } from '../../stores/agentStore';
import type { AgentStatus, SystemStats } from '../../types';

const AGENT_COLORS: Record<string, string> = {
  inference: '#58a6ff',
  validation: '#3fb950',
  store: '#bc8cff',
  cli: '#d29922',
  unknown: '#8b949e',
};

const STATUS_COLORS: Record<string, string> = {
  running: '#3fb950',
  idle: '#d29922',
  error: '#f85149',
  stale: '#6e7681',
  dead: '#484f58',
  stopping: '#d29922',
};

const TYPE_LABELS: Record<string, string> = {
  store: 'Store',
  inference: 'Inference',
  validation: 'Validator',
  cli: 'CLI',
};

interface NodeDatum extends d3.SimulationNodeDatum {
  id: string;
  type: string;
  status?: AgentStatus;
}

interface LinkDatum extends d3.SimulationLinkDatum<NodeDatum> {
  id: string;
}

interface Props {
  maximized?: boolean;
  onToggleMaximize?: () => void;
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}m ${s}s`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

function NodeStatusSidebar({ agents, stats }: { agents: AgentStatus[]; stats: SystemStats | null }) {
  // Group agents by type
  const groups: Record<string, AgentStatus[]> = {};
  for (const a of agents) {
    const t = a.agent_type;
    if (!groups[t]) groups[t] = [];
    groups[t].push(a);
  }

  // Sort groups by priority
  const typeOrder = ['store', 'inference', 'validation', 'cli'];
  const sortedTypes = Object.keys(groups).sort(
    (a, b) => (typeOrder.indexOf(a) === -1 ? 99 : typeOrder.indexOf(a)) -
              (typeOrder.indexOf(b) === -1 ? 99 : typeOrder.indexOf(b))
  );

  return (
    <div
      style={{
        width: '210px',
        flexShrink: 0,
        borderLeft: '1px solid var(--border)',
        overflowY: 'auto',
        fontSize: '11px',
        background: 'var(--bg-secondary)',
      }}
    >
      {/* General section */}
      <SectionHeader title="Network" />
      <div style={{ padding: '6px 10px 10px' }}>
        <StatRow label="Total nodes" value={agents.length.toString()} />
        <StatRow
          label="Active"
          value={agents.filter((a) => a.status === 'running').length.toString()}
          color="var(--status-running)"
        />
        {stats?.network && (
          <StatRow label="WS clients" value={stats.network.websocket_clients.toString()} />
        )}
      </div>

      {/* Knowledge section */}
      {stats?.knowledge && (
        <>
          <SectionHeader title="Knowledge" />
          <div style={{ padding: '6px 10px 10px' }}>
            <StatRow label="Observations" value={stats.knowledge.observations.toString()} />
            <StatRow label="Claims" value={stats.knowledge.claims.toString()} />
            <StatRow label="Entities" value={stats.knowledge.entities.toString()} />
            <StatRow label="Triples" value={stats.knowledge.triples.toString()} />
            <StatRow label="Relationships" value={stats.knowledge.relationships.toString()} />
          </div>
        </>
      )}

      {/* Per-type sections */}
      {sortedTypes.map((type) => {
        const typeAgents = groups[type];
        const color = AGENT_COLORS[type] || AGENT_COLORS.unknown;
        const label = TYPE_LABELS[type] || type;

        return (
          <div key={type}>
            <SectionHeader title={label} color={color} count={typeAgents.length} />
            <div style={{ padding: '4px 10px 8px' }}>
              {typeAgents.map((a) => (
                <NodeCard key={a.agent_id} agent={a} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function SectionHeader({ title, color, count }: { title: string; color?: string; count?: number }) {
  return (
    <div
      style={{
        padding: '6px 10px 4px',
        fontSize: '9px',
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.5px',
        color: 'var(--text-muted)',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
      }}
    >
      {color && (
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0 }} />
      )}
      {title}
      {count !== undefined && (
        <span style={{ marginLeft: 'auto', color: 'var(--text-secondary)', fontWeight: 400 }}>{count}</span>
      )}
    </div>
  );
}

function NodeCard({ agent }: { agent: AgentStatus }) {
  const statusColor = STATUS_COLORS[agent.status] || STATUS_COLORS.running;
  const shortId = agent.agent_id.split('-').pop() || agent.agent_id;

  return (
    <div
      style={{
        padding: '5px 0',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        gap: '2px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
        <span
          style={{
            width: 5,
            height: 5,
            borderRadius: '50%',
            background: statusColor,
            boxShadow: agent.status === 'running' ? `0 0 4px ${statusColor}` : 'none',
            flexShrink: 0,
          }}
        />
        <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '10px' }}>
          {shortId}
        </span>
        <span
          style={{
            marginLeft: 'auto',
            fontSize: '9px',
            color: statusColor,
            fontWeight: 500,
          }}
        >
          {agent.status}
        </span>
      </div>
      <div style={{ paddingLeft: '10px', color: 'var(--text-secondary)', fontSize: '10px' }}>
        <span>up {formatUptime(agent.uptime_seconds)}</span>
        {agent.tags && agent.tags.length > 1 && (
          <span style={{ marginLeft: '8px', color: 'var(--text-muted)' }}>
            [{agent.tags.join(', ')}]
          </span>
        )}
      </div>
    </div>
  );
}

function StatRow({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '1px 0' }}>
      <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
      <span style={{ fontWeight: 600, color: color || 'var(--text-primary)' }}>{value}</span>
    </div>
  );
}

export function AgentTopology({ maximized, onToggleMaximize }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const agents = useAgentStore((s) => Array.from(s.agents.values()));
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [stats, setStats] = useState<SystemStats | null>(null);

  // Persistent refs for D3 objects that survive re-renders
  const simulationRef = useRef<d3.Simulation<NodeDatum, LinkDatum> | null>(null);
  const gRef = useRef<d3.Selection<SVGGElement, unknown, null, undefined> | null>(null);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const zoomTransformRef = useRef<d3.ZoomTransform>(d3.zoomIdentity);
  const tooltipRef = useRef<d3.Selection<HTMLDivElement, unknown, null, undefined> | null>(null);
  const nodesRef = useRef<NodeDatum[]>([]);
  const linksRef = useRef<LinkDatum[]>([]);
  const initializedRef = useRef(false);

  // Fetch stats for sidebar
  useEffect(() => {
    const fetchStats = async () => {
      try {
        const res = await fetch('/v1/stats');
        if (res.ok) setStats(await res.json());
      } catch {
        // API not available
      }
    };
    fetchStats();
    const interval = setInterval(fetchStats, 10000);
    return () => clearInterval(interval);
  }, []);

  // Track container size
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        setDimensions({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  // One-time D3 setup
  useEffect(() => {
    if (!svgRef.current || dimensions.width === 0 || dimensions.height === 0) return;
    if (initializedRef.current) return;

    const { width, height } = dimensions;
    const svg = d3.select(svgRef.current);

    svg.selectAll('*').remove();
    svg.attr('width', width).attr('height', height);

    const defs = svg.append('defs');
    const filter = defs.append('filter').attr('id', 'glow');
    filter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'coloredBlur');
    const feMerge = filter.append('feMerge');
    feMerge.append('feMergeNode').attr('in', 'coloredBlur');
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic');

    const g = svg.append('g');
    gRef.current = g;

    g.append('g').attr('class', 'links-group');
    g.append('g').attr('class', 'nodes-group');

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 5])
      .on('zoom', (event) => {
        zoomTransformRef.current = event.transform;
        g.attr('transform', event.transform);
      });
    zoomRef.current = zoom;
    svg.call(zoom);

    tooltipRef.current = d3
      .select(containerRef.current!)
      .append('div')
      .attr('class', 'tooltip')
      .style('display', 'none');

    const simulation = d3
      .forceSimulation<NodeDatum>([])
      .force('link', d3.forceLink<NodeDatum, LinkDatum>([]).id((d) => d.id).distance(120))
      .force('charge', d3.forceManyBody().strength(-300))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(30));

    simulationRef.current = simulation;
    initializedRef.current = true;

    return () => {
      simulation.stop();
      tooltipRef.current?.remove();
      initializedRef.current = false;
      simulationRef.current = null;
      gRef.current = null;
    };
  }, [dimensions]);

  // Update data when agents change
  useEffect(() => {
    const simulation = simulationRef.current;
    const g = gRef.current;
    const tooltip = tooltipRef.current;
    if (!simulation || !g || !tooltip || dimensions.width === 0) return;

    const existingPositions = new Map<string, { x: number; y: number; fx?: number | null; fy?: number | null }>();
    for (const n of nodesRef.current) {
      if (n.x != null && n.y != null) {
        existingPositions.set(n.id, { x: n.x, y: n.y, fx: n.fx, fy: n.fy });
      }
    }

    const newNodes: NodeDatum[] = agents.map((a) => {
      const existing = existingPositions.get(a.agent_id);
      return {
        id: a.agent_id,
        type: a.agent_type,
        status: a,
        ...(existing || {}),
      };
    });

    const newLinks: LinkDatum[] = [];
    for (let i = 0; i < newNodes.length; i++) {
      for (let j = i + 1; j < newNodes.length; j++) {
        newLinks.push({
          id: `link-${newNodes[i].id}-${newNodes[j].id}`,
          source: newNodes[i].id,
          target: newNodes[j].id,
        });
      }
    }

    nodesRef.current = newNodes;
    linksRef.current = newLinks;

    simulation.nodes(newNodes);
    const linkForce = simulation.force('link') as d3.ForceLink<NodeDatum, LinkDatum>;
    linkForce.links(newLinks);

    const linksGroup = g.select<SVGGElement>('.links-group');
    const link = linksGroup
      .selectAll<SVGLineElement, LinkDatum>('line')
      .data(newLinks, (d) => d.id);

    link.exit().remove();
    const linkEnter = link.enter()
      .append('line')
      .attr('stroke', '#30363d')
      .attr('stroke-width', 1)
      .attr('stroke-opacity', 0.4);
    const linkMerged = linkEnter.merge(link);

    const nodesGroup = g.select<SVGGElement>('.nodes-group');
    const node = nodesGroup
      .selectAll<SVGGElement, NodeDatum>('g.node')
      .data(newNodes, (d) => d.id);

    node.exit().remove();

    const nodeEnter = node.enter()
      .append('g')
      .attr('class', 'node')
      .attr('cursor', 'grab');

    nodeEnter.append('circle')
      .attr('class', 'main-circle')
      .attr('r', 18);

    nodeEnter.append('circle')
      .attr('class', 'status-ring')
      .attr('r', 22)
      .attr('fill', 'none')
      .attr('stroke-width', 1)
      .attr('opacity', 0.3);

    nodeEnter.append('text')
      .attr('class', 'node-label')
      .attr('text-anchor', 'middle')
      .attr('dy', 4)
      .attr('fill', '#c9d1d9')
      .attr('font-size', '9px')
      .attr('font-weight', '600')
      .attr('pointer-events', 'none');

    nodeEnter.append('text')
      .attr('class', 'node-id')
      .attr('text-anchor', 'middle')
      .attr('dy', 34)
      .attr('fill', '#8b949e')
      .attr('font-size', '8px')
      .attr('pointer-events', 'none');

    const nodeMerged = nodeEnter.merge(node);

    nodeMerged.select('.main-circle')
      .attr('fill', (d) => AGENT_COLORS[d.type] || AGENT_COLORS.unknown)
      .attr('stroke', (d) => {
        const status = d.status?.status || 'running';
        return STATUS_COLORS[status] || STATUS_COLORS.running;
      })
      .attr('stroke-width', 2)
      .style('filter', (d) => {
        const status = d.status?.status;
        if (status === 'running') return 'url(#glow)';
        return 'none';
      });

    nodeMerged.select('.status-ring')
      .attr('stroke', (d) => {
        const status = d.status?.status || 'running';
        return STATUS_COLORS[status] || STATUS_COLORS.running;
      });

    nodeMerged.select('.node-label')
      .text((d) => {
        const label = d.type.charAt(0).toUpperCase() + d.type.slice(1);
        return label.length > 6 ? label.slice(0, 6) : label;
      });

    nodeMerged.select('.node-id')
      .text((d) => {
        const parts = d.id.split('-');
        return parts[parts.length - 1];
      });

    const drag = d3.drag<SVGGElement, NodeDatum>()
      .on('start', (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on('drag', (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on('end', (event, d) => {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      });

    nodeMerged.call(drag);

    nodeMerged
      .on('mouseover', (_event, d) => {
        if (!d.status) return;
        const s = d.status;
        tooltip
          .style('display', 'block')
          .html(
            `<div class="label">${s.agent_id}</div>` +
            `<div class="value">Type: ${s.agent_type}</div>` +
            `<div class="value">Status: ${s.status}</div>` +
            (s.tags?.length ? `<div class="value">Capabilities: ${s.tags.join(', ')}</div>` : '') +
            `<div class="value">Uptime: ${formatUptime(s.uptime_seconds)}</div>`
          );
      })
      .on('mousemove', (event) => {
        tooltip
          .style('left', event.offsetX + 15 + 'px')
          .style('top', event.offsetY - 10 + 'px');
      })
      .on('mouseout', () => {
        tooltip.style('display', 'none');
      });

    simulation.on('tick', () => {
      linkMerged
        .attr('x1', (d) => ((d.source as NodeDatum).x ?? 0))
        .attr('y1', (d) => ((d.source as NodeDatum).y ?? 0))
        .attr('x2', (d) => ((d.target as NodeDatum).x ?? 0))
        .attr('y2', (d) => ((d.target as NodeDatum).y ?? 0));

      nodeMerged.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    simulation.alpha(0.3).restart();
  }, [agents, dimensions]);

  useEffect(() => {
    if (!svgRef.current || dimensions.width === 0) return;
    const svg = d3.select(svgRef.current);
    svg.attr('width', dimensions.width).attr('height', dimensions.height);
  }, [dimensions]);

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Agent Topology</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
            {agents.length} node{agents.length !== 1 ? 's' : ''}
          </span>
          {onToggleMaximize && (
            <button className="panel-btn" onClick={onToggleMaximize} title={maximized ? 'Restore' : 'Maximize'}>
              {maximized ? '\u2716' : '\u2922'}
            </button>
          )}
        </div>
      </div>
      <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
        <div ref={containerRef} className="panel-body" style={{ padding: 0, position: 'relative', flex: 1 }}>
          <svg ref={svgRef} style={{ display: 'block', position: 'absolute', inset: 0 }} />
        </div>
        <NodeStatusSidebar agents={agents} stats={stats} />
      </div>
    </div>
  );
}
