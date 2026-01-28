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

export function AgentTopology({ maximized, onToggleMaximize }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const agents = useAgentStore((s) => Array.from(s.agents.values()));
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });

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

  // D3 rendering
  useEffect(() => {
    if (!svgRef.current || dimensions.width === 0 || dimensions.height === 0) return;

    const { width, height } = dimensions;
    const svg = d3.select(svgRef.current);

    svg.selectAll('*').remove();
    svg.attr('width', width).attr('height', height);

    // Build nodes: API center + agents
    const nodes: NodeDatum[] = [
      { id: 'api', type: 'api', isApi: true, x: width / 2, y: height / 2, fx: width / 2, fy: height / 2 },
      ...agents.map((a) => ({
        id: a.agent_id,
        type: a.agent_type,
        isApi: false,
        status: a,
      })),
    ];

    const links: LinkDatum[] = agents.map((a) => ({
      id: `link-${a.agent_id}`,
      source: 'api',
      target: a.agent_id,
    }));

    // Defs for glow effects
    const defs = svg.append('defs');
    const filter = defs.append('filter').attr('id', 'glow');
    filter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'coloredBlur');
    const feMerge = filter.append('feMerge');
    feMerge.append('feMergeNode').attr('in', 'coloredBlur');
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic');

    // Radial gradient for API node
    const gradient = defs.append('radialGradient').attr('id', 'api-gradient');
    gradient.append('stop').attr('offset', '0%').attr('stop-color', '#58a6ff').attr('stop-opacity', '0.4');
    gradient.append('stop').attr('offset', '100%').attr('stop-color', '#58a6ff').attr('stop-opacity', '0.05');

    // Main group (zoom/pan target)
    const g = svg.append('g');

    // Zoom + pan on SVG
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 5])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });
    svg.call(zoom);

    // Simulation
    const simulation = d3
      .forceSimulation<NodeDatum>(nodes)
      .force('link', d3.forceLink<NodeDatum, LinkDatum>(links).id((d) => d.id).distance(100))
      .force('charge', d3.forceManyBody().strength(-200))
      .force('center', d3.forceCenter(width / 2, height / 2));

    // Links
    const link = g
      .append('g')
      .selectAll('line')
      .data(links)
      .join('line')
      .attr('stroke', '#30363d')
      .attr('stroke-width', 1.5)
      .attr('stroke-dasharray', '4,4');

    // API background glow
    g.append('circle')
      .attr('cx', width / 2)
      .attr('cy', height / 2)
      .attr('r', 50)
      .attr('fill', 'url(#api-gradient)');

    // Nodes
    const node = g
      .append('g')
      .selectAll<SVGGElement, NodeDatum>('g')
      .data(nodes)
      .join('g')
      .attr('cursor', 'grab');

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
        // Keep API fixed, release agents
        if (!d.isApi) {
          d.fx = null;
          d.fy = null;
        }
      });

    node.call(drag);

    // Node circles
    node
      .append('circle')
      .attr('r', (d) => (d.isApi ? 28 : 16))
      .attr('fill', (d) => {
        if (d.isApi) return '#161b22';
        return AGENT_COLORS[d.type] || AGENT_COLORS.unknown;
      })
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

    // Status ring for agents
    node
      .filter((d) => !d.isApi)
      .append('circle')
      .attr('r', 20)
      .attr('fill', 'none')
      .attr('stroke', (d) => {
        const status = d.status?.status || 'running';
        return STATUS_COLORS[status] || STATUS_COLORS.running;
      })
      .attr('stroke-width', 1)
      .attr('opacity', 0.3);

    // Labels
    node
      .append('text')
      .text((d) => {
        if (d.isApi) return 'API';
        return d.type.charAt(0).toUpperCase() + d.type.slice(1, 4);
      })
      .attr('text-anchor', 'middle')
      .attr('dy', 4)
      .attr('fill', '#c9d1d9')
      .attr('font-size', (d) => (d.isApi ? '11px' : '9px'))
      .attr('font-weight', '600')
      .attr('pointer-events', 'none');

    // Agent ID below
    node
      .filter((d) => !d.isApi)
      .append('text')
      .text((d) => d.id.split('-').slice(-1)[0])
      .attr('text-anchor', 'middle')
      .attr('dy', 30)
      .attr('fill', '#8b949e')
      .attr('font-size', '8px')
      .attr('pointer-events', 'none');

    // Tooltip
    const tooltip = d3
      .select(containerRef.current!)
      .append('div')
      .attr('class', 'tooltip')
      .style('display', 'none');

    node
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
      link
        .attr('x1', (d) => ((d.source as NodeDatum).x ?? 0))
        .attr('y1', (d) => ((d.source as NodeDatum).y ?? 0))
        .attr('x2', (d) => ((d.target as NodeDatum).x ?? 0))
        .attr('y2', (d) => ((d.target as NodeDatum).y ?? 0));

      node.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    return () => {
      simulation.stop();
      tooltip.remove();
    };
  }, [agents, dimensions]);

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
      </div>
    </div>
  );
}
