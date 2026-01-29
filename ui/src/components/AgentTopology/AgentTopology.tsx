import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import { useAgentStore } from '../../stores/agentStore';
import type { AgentStatus } from '../../types';

const AGENT_COLORS: Record<string, string> = {
  inference: '#58a6ff',
  validator: '#3fb950',
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

interface NodeDatum extends d3.SimulationNodeDatum {
  id: string;
  type: string;
  isApi: boolean;
  status?: AgentStatus;
}

interface LinkDatum extends d3.SimulationLinkDatum<NodeDatum> {
  id: string;
}

interface Props {
  maximized?: boolean;
  onToggleMaximize?: () => void;
}

function Legend() {
  return (
    <div
      style={{
        position: 'absolute',
        bottom: 8,
        left: 8,
        background: 'var(--bg-tertiary)',
        border: '1px solid var(--border)',
        borderRadius: '6px',
        padding: '8px 10px',
        fontSize: '9px',
        lineHeight: '16px',
        color: 'var(--text-secondary)',
        pointerEvents: 'none',
        zIndex: 10,
        display: 'flex',
        flexDirection: 'column',
        gap: '3px',
      }}
    >
      <div style={{ fontWeight: 600, fontSize: '10px', marginBottom: '2px', color: 'var(--text-primary)' }}>
        Agent Types
      </div>
      {Object.entries(AGENT_COLORS).filter(([k]) => k !== 'unknown').map(([type, color]) => (
        <div key={type} style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
          {type}
        </div>
      ))}
      <div style={{ fontWeight: 600, fontSize: '10px', marginTop: '4px', marginBottom: '2px', color: 'var(--text-primary)' }}>
        Status
      </div>
      {Object.entries(STATUS_COLORS).map(([status, color]) => (
        <div key={status} style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              border: `2px solid ${color}`,
              background: 'transparent',
              flexShrink: 0,
            }}
          />
          {status}
        </div>
      ))}
      <div style={{ fontWeight: 600, fontSize: '10px', marginTop: '4px', marginBottom: '2px', color: 'var(--text-primary)' }}>
        Interactions
      </div>
      <div>Scroll to zoom</div>
      <div>Drag background to pan</div>
      <div>Drag node to reposition</div>
      <div>Hover node for details</div>
    </div>
  );
}

export function AgentTopology({ maximized, onToggleMaximize }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const agents = useAgentStore((s) => Array.from(s.agents.values()));
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });

  // Persistent refs for D3 objects that survive re-renders
  const simulationRef = useRef<d3.Simulation<NodeDatum, LinkDatum> | null>(null);
  const gRef = useRef<d3.Selection<SVGGElement, unknown, null, undefined> | null>(null);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const zoomTransformRef = useRef<d3.ZoomTransform>(d3.zoomIdentity);
  const tooltipRef = useRef<d3.Selection<HTMLDivElement, unknown, null, undefined> | null>(null);
  const nodesRef = useRef<NodeDatum[]>([]);
  const linksRef = useRef<LinkDatum[]>([]);
  const initializedRef = useRef(false);

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

  // One-time D3 setup: create SVG structure, zoom, defs
  useEffect(() => {
    if (!svgRef.current || dimensions.width === 0 || dimensions.height === 0) return;
    if (initializedRef.current) return; // already set up

    const { width, height } = dimensions;
    const svg = d3.select(svgRef.current);

    svg.selectAll('*').remove();
    svg.attr('width', width).attr('height', height);

    // Defs for glow effects
    const defs = svg.append('defs');
    const filter = defs.append('filter').attr('id', 'glow');
    filter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'coloredBlur');
    const feMerge = filter.append('feMerge');
    feMerge.append('feMergeNode').attr('in', 'coloredBlur');
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic');

    const gradient = defs.append('radialGradient').attr('id', 'api-gradient');
    gradient.append('stop').attr('offset', '0%').attr('stop-color', '#58a6ff').attr('stop-opacity', '0.4');
    gradient.append('stop').attr('offset', '100%').attr('stop-color', '#58a6ff').attr('stop-opacity', '0.05');

    // Main group (zoom/pan target)
    const g = svg.append('g');
    gRef.current = g;

    // API background glow
    g.append('circle')
      .attr('class', 'api-glow')
      .attr('cx', width / 2)
      .attr('cy', height / 2)
      .attr('r', 50)
      .attr('fill', 'url(#api-gradient)');

    // Groups for links and nodes
    g.append('g').attr('class', 'links-group');
    g.append('g').attr('class', 'nodes-group');

    // Zoom + pan
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 5])
      .on('zoom', (event) => {
        zoomTransformRef.current = event.transform;
        g.attr('transform', event.transform);
      });
    zoomRef.current = zoom;
    svg.call(zoom);

    // Tooltip
    tooltipRef.current = d3
      .select(containerRef.current!)
      .append('div')
      .attr('class', 'tooltip')
      .style('display', 'none');

    // Simulation
    const simulation = d3
      .forceSimulation<NodeDatum>([])
      .force('link', d3.forceLink<NodeDatum, LinkDatum>([]).id((d) => d.id).distance(100))
      .force('charge', d3.forceManyBody().strength(-200))
      .force('center', d3.forceCenter(width / 2, height / 2));

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

  // Update data when agents change — no teardown, just update D3 data joins
  useEffect(() => {
    const simulation = simulationRef.current;
    const g = gRef.current;
    const tooltip = tooltipRef.current;
    if (!simulation || !g || !tooltip || dimensions.width === 0) return;

    const { width, height } = dimensions;

    // Build new node/link data, preserving positions of existing nodes
    const existingPositions = new Map<string, { x: number; y: number; fx?: number | null; fy?: number | null }>();
    for (const n of nodesRef.current) {
      if (n.x != null && n.y != null) {
        existingPositions.set(n.id, { x: n.x, y: n.y, fx: n.fx, fy: n.fy });
      }
    }

    const newNodes: NodeDatum[] = [
      {
        id: 'api',
        type: 'api',
        isApi: true,
        ...existingPositions.get('api') || { x: width / 2, y: height / 2 },
        fx: width / 2,
        fy: height / 2,
      },
      ...agents.map((a) => {
        const existing = existingPositions.get(a.agent_id);
        return {
          id: a.agent_id,
          type: a.agent_type,
          isApi: false,
          status: a,
          ...(existing || {}),
        };
      }),
    ];

    const newLinks: LinkDatum[] = agents.map((a) => ({
      id: `link-${a.agent_id}`,
      source: 'api',
      target: a.agent_id,
    }));

    nodesRef.current = newNodes;
    linksRef.current = newLinks;

    // Update simulation
    simulation.nodes(newNodes);
    const linkForce = simulation.force('link') as d3.ForceLink<NodeDatum, LinkDatum>;
    linkForce.links(newLinks);

    // -- Data join: links --
    const linksGroup = g.select<SVGGElement>('.links-group');
    const link = linksGroup
      .selectAll<SVGLineElement, LinkDatum>('line')
      .data(newLinks, (d) => d.id);

    link.exit().remove();

    const linkEnter = link.enter()
      .append('line')
      .attr('stroke', '#30363d')
      .attr('stroke-width', 1.5)
      .attr('stroke-dasharray', '4,4');

    const linkMerged = linkEnter.merge(link);

    // -- Data join: nodes --
    const nodesGroup = g.select<SVGGElement>('.nodes-group');
    const node = nodesGroup
      .selectAll<SVGGElement, NodeDatum>('g.node')
      .data(newNodes, (d) => d.id);

    node.exit().remove();

    const nodeEnter = node.enter()
      .append('g')
      .attr('class', 'node')
      .attr('cursor', 'grab');

    // Circle for entering nodes
    nodeEnter.append('circle')
      .attr('class', 'main-circle')
      .attr('r', (d) => (d.isApi ? 28 : 16))
      .attr('fill', (d) => {
        if (d.isApi) return '#161b22';
        return AGENT_COLORS[d.type] || AGENT_COLORS.unknown;
      });

    // Status ring for agent nodes
    nodeEnter.filter((d) => !d.isApi)
      .append('circle')
      .attr('class', 'status-ring')
      .attr('r', 20)
      .attr('fill', 'none')
      .attr('stroke-width', 1)
      .attr('opacity', 0.3);

    // Label
    nodeEnter.append('text')
      .attr('class', 'node-label')
      .attr('text-anchor', 'middle')
      .attr('dy', 4)
      .attr('fill', '#c9d1d9')
      .attr('font-size', (d) => (d.isApi ? '11px' : '9px'))
      .attr('font-weight', '600')
      .attr('pointer-events', 'none');

    // ID label below agent nodes
    nodeEnter.filter((d) => !d.isApi)
      .append('text')
      .attr('class', 'node-id')
      .attr('text-anchor', 'middle')
      .attr('dy', 30)
      .attr('fill', '#8b949e')
      .attr('font-size', '8px')
      .attr('pointer-events', 'none');

    // Merge enter + update
    const nodeMerged = nodeEnter.merge(node);

    // Update dynamic attributes on ALL nodes (enter + existing)
    nodeMerged.select('.main-circle')
      .attr('stroke', (d) => {
        if (d.isApi) return '#58a6ff';
        const status = d.status?.status || 'running';
        return STATUS_COLORS[status] || STATUS_COLORS.running;
      })
      .attr('stroke-width', (d) => (d.isApi ? 2.5 : 2))
      .style('filter', (d) => {
        const status = d.status?.status;
        if (d.isApi || status === 'running') return 'url(#glow)';
        return 'none';
      });

    nodeMerged.select('.status-ring')
      .attr('stroke', (d) => {
        const status = d.status?.status || 'running';
        return STATUS_COLORS[status] || STATUS_COLORS.running;
      });

    nodeMerged.select('.node-label')
      .text((d) => {
        if (d.isApi) return 'API';
        return d.type.charAt(0).toUpperCase() + d.type.slice(1, 4);
      });

    nodeMerged.select('.node-id')
      .text((d) => d.id.split('-').slice(-1)[0]);

    // Drag behavior
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
        if (!d.isApi) {
          d.fx = null;
          d.fy = null;
        }
      });

    nodeMerged.call(drag);

    // Tooltip handlers
    nodeMerged
      .on('mouseover', (_event, d) => {
        if (d.isApi || !d.status) return;
        const s = d.status;
        tooltip
          .style('display', 'block')
          .html(
            `<div class="label">${s.agent_id}</div>` +
            `<div class="value">Type: ${s.agent_type}</div>` +
            `<div class="value">Status: ${s.status}</div>` +
            `<div class="value">Processed: ${s.items_processed}</div>` +
            `<div class="value">Errors: ${s.error_count}</div>` +
            `<div class="value">Avg time: ${s.processing_time_avg_ms.toFixed(1)}ms</div>` +
            `<div class="value">Memory: ${s.memory_mb.toFixed(1)} MB</div>`
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

    // Tick
    simulation.on('tick', () => {
      linkMerged
        .attr('x1', (d) => ((d.source as NodeDatum).x ?? 0))
        .attr('y1', (d) => ((d.source as NodeDatum).y ?? 0))
        .attr('x2', (d) => ((d.target as NodeDatum).x ?? 0))
        .attr('y2', (d) => ((d.target as NodeDatum).y ?? 0));

      nodeMerged.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    // Gently reheat — don't reset positions
    simulation.alpha(0.3).restart();
  }, [agents, dimensions]);

  // Update SVG size when dimensions change (without full rebuild)
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
            {agents.length} agent{agents.length !== 1 ? 's' : ''}
          </span>
          {onToggleMaximize && (
            <button className="panel-btn" onClick={onToggleMaximize} title={maximized ? 'Restore' : 'Maximize'}>
              {maximized ? '\u2716' : '\u2922'}
            </button>
          )}
        </div>
      </div>
      <div ref={containerRef} className="panel-body" style={{ padding: 0, position: 'relative' }}>
        <svg ref={svgRef} style={{ display: 'block', position: 'absolute', inset: 0 }} />
        <Legend />
      </div>
    </div>
  );
}
