import { useEffect, useRef, useCallback, useState } from 'react';
import * as d3 from 'd3';
import { useGraphStore } from '../../stores/graphStore';
import type { GraphNode } from '../../types';

const NODE_COLORS: Record<string, string> = {
  Entity: '#58a6ff',
  Observation: '#8b949e',
  Claim: '#3fb950',
};

const NODE_RADIUS: Record<string, number> = {
  Entity: 12,
  Observation: 8,
  Claim: 10,
};

interface Props {
  maximized?: boolean;
  onToggleMaximize?: () => void;
}

export function GraphView({ maximized, onToggleMaximize }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const { nodes, setNodes } = useGraphStore();
  const [loading, setLoading] = useState(false);
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

  const fetchGraphData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/v1/graph/nodes?limit=200');
      if (res.ok) {
        const data = await res.json();
        setNodes(data.nodes);
      }
    } catch (e) {
      console.error('Failed to fetch graph data:', e);
    } finally {
      setLoading(false);
    }
  }, [setNodes]);

  useEffect(() => {
    fetchGraphData();
  }, [fetchGraphData]);

  useEffect(() => {
    if (!svgRef.current || nodes.length === 0 || dimensions.width === 0 || dimensions.height === 0) return;

    const { width, height } = dimensions;
    const svg = d3.select(svgRef.current);

    svg.selectAll('*').remove();
    svg.attr('width', width).attr('height', height);

    // Defs
    const defs = svg.append('defs');
    const filter = defs.append('filter').attr('id', 'graph-glow');
    filter.append('feGaussianBlur').attr('stdDeviation', '2').attr('result', 'coloredBlur');
    const feMerge = filter.append('feMerge');
    feMerge.append('feMergeNode').attr('in', 'coloredBlur');
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic');

    const g = svg.append('g');

    // Zoom + pan
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });
    svg.call(zoom);

    // Simulation nodes (copy to avoid mutating store)
    const simNodes: (GraphNode & d3.SimulationNodeDatum)[] = nodes.map((n) => ({ ...n }));

    interface SimLink extends d3.SimulationLinkDatum<GraphNode & d3.SimulationNodeDatum> {
      id: string;
    }
    const simLinks: SimLink[] = [];

    const simulation = d3
      .forceSimulation(simNodes)
      .force('link', d3.forceLink<GraphNode & d3.SimulationNodeDatum, SimLink>(simLinks).id((d) => d.id).distance(60))
      .force('charge', d3.forceManyBody().strength(-80))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(20));

    // Links
    const link = g
      .append('g')
      .selectAll('line')
      .data(simLinks)
      .join('line')
      .attr('stroke', 'var(--edge-default)')
      .attr('stroke-width', 1);

    // Nodes
    const node = g
      .append('g')
      .selectAll<SVGGElement, GraphNode & d3.SimulationNodeDatum>('g')
      .data(simNodes)
      .join('g')
      .attr('cursor', 'grab');

    // Drag
    node.call(
      d3.drag<SVGGElement, GraphNode & d3.SimulationNodeDatum>()
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
        })
    );

    // Circles
    node
      .append('circle')
      .attr('r', (d) => NODE_RADIUS[d.type] || 8)
      .attr('fill', (d) => NODE_COLORS[d.type] || '#8b949e')
      .attr('opacity', 0.85)
      .style('filter', 'url(#graph-glow)');

    // Labels for entities
    node
      .filter((d) => d.type === 'Entity')
      .append('text')
      .text((d) => {
        const name = (d.data as Record<string, string>).name || '';
        return name.length > 12 ? name.slice(0, 12) + '...' : name;
      })
      .attr('text-anchor', 'middle')
      .attr('dy', -16)
      .attr('fill', 'var(--text-primary)')
      .attr('font-size', '10px')
      .attr('font-weight', '500')
      .attr('pointer-events', 'none');

    // Tooltip
    const tooltip = d3
      .select(containerRef.current!)
      .append('div')
      .attr('class', 'tooltip')
      .style('display', 'none');

    node
      .on('mouseover', (_event, d) => {
        const data = d.data as Record<string, string>;
        let html = `<div class="label">${d.type}</div>`;
        if (data.name) html += `<div class="value">Name: ${data.name}</div>`;
        if (data.raw_content) html += `<div class="value">${data.raw_content.slice(0, 100)}</div>`;
        if (data.subject_text) html += `<div class="value">${data.subject_text} ${data.predicate_text} ${data.object_text}</div>`;
        tooltip.style('display', 'block').html(html);
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
      link
        .attr('x1', (d) => ((d.source as unknown as { x: number }).x ?? 0))
        .attr('y1', (d) => ((d.source as unknown as { y: number }).y ?? 0))
        .attr('x2', (d) => ((d.target as unknown as { x: number }).x ?? 0))
        .attr('y2', (d) => ((d.target as unknown as { y: number }).y ?? 0));

      node.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    return () => {
      simulation.stop();
      tooltip.remove();
    };
  }, [nodes, dimensions]);

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Knowledge Graph</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
            {nodes.length} node{nodes.length !== 1 ? 's' : ''}
          </span>
          <button className="panel-btn" onClick={fetchGraphData} title="Refresh">
            &#x21bb;
          </button>
          {onToggleMaximize && (
            <button className="panel-btn" onClick={onToggleMaximize} title={maximized ? 'Restore' : 'Maximize'}>
              {maximized ? '\u2716' : '\u2922'}
            </button>
          )}
        </div>
      </div>
      <div ref={containerRef} className="panel-body" style={{ padding: 0, position: 'relative' }}>
        {loading ? (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              color: 'var(--text-muted)',
            }}
          >
            Loading graph...
          </div>
        ) : nodes.length === 0 ? (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              color: 'var(--text-muted)',
              fontSize: '13px',
            }}
          >
            No graph data yet
          </div>
        ) : (
          <svg ref={svgRef} style={{ display: 'block', position: 'absolute', inset: 0 }} />
        )}
      </div>
    </div>
  );
}
