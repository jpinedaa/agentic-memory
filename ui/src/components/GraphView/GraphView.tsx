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

type SimNode = GraphNode & d3.SimulationNodeDatum;

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  id: string;
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
        Node Types
      </div>
      {Object.entries(NODE_COLORS).map(([type, color]) => (
        <div key={type} style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <span
            style={{
              width: NODE_RADIUS[type] ? NODE_RADIUS[type] * 0.8 : 6,
              height: NODE_RADIUS[type] ? NODE_RADIUS[type] * 0.8 : 6,
              borderRadius: '50%',
              background: color,
              flexShrink: 0,
            }}
          />
          {type}
        </div>
      ))}
      <div style={{ fontWeight: 600, fontSize: '10px', marginTop: '4px', marginBottom: '2px', color: 'var(--text-primary)' }}>
        Edges
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
        <span style={{ width: 14, height: 1, background: 'var(--edge-default)', flexShrink: 0 }} />
        relationships (labeled)
      </div>
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

export function GraphView({ maximized, onToggleMaximize }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const { nodes, setNodes, links, setLinks, refreshCounter } = useGraphStore();
  const [loading, setLoading] = useState(false);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [fetchError, setFetchError] = useState(false);

  // Persistent D3 refs
  const simulationRef = useRef<d3.Simulation<SimNode, SimLink> | null>(null);
  const gRef = useRef<d3.Selection<SVGGElement, unknown, null, undefined> | null>(null);
  const zoomTransformRef = useRef<d3.ZoomTransform>(d3.zoomIdentity);
  const tooltipRef = useRef<d3.Selection<HTMLDivElement, unknown, null, undefined> | null>(null);
  const simNodesRef = useRef<SimNode[]>([]);
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

  const fetchGraphData = useCallback(async () => {
    setLoading(true);
    setFetchError(false);
    try {
      const res = await fetch('/v1/graph/nodes?limit=200');
      if (res.ok) {
        const data = await res.json();
        setNodes(data.nodes);
        setLinks(data.edges || []);
      } else {
        setFetchError(true);
      }
    } catch (e) {
      console.error('Failed to fetch graph data:', e);
      setFetchError(true);
    } finally {
      setLoading(false);
    }
  }, [setNodes, setLinks]);

  // Fetch on mount
  useEffect(() => {
    fetchGraphData();
  }, [fetchGraphData]);

  // Re-fetch when memory events arrive (debounced via refreshCounter)
  useEffect(() => {
    if (refreshCounter === 0) return; // skip initial
    // Small delay to let the server process the event
    const timer = setTimeout(fetchGraphData, 1500);
    return () => clearTimeout(timer);
  }, [refreshCounter, fetchGraphData]);

  // One-time D3 setup
  useEffect(() => {
    if (!svgRef.current || dimensions.width === 0 || dimensions.height === 0) return;
    if (initializedRef.current) return;

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
    gRef.current = g;

    g.append('g').attr('class', 'links-group');
    g.append('g').attr('class', 'nodes-group');

    // Zoom + pan
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on('zoom', (event) => {
        zoomTransformRef.current = event.transform;
        g.attr('transform', event.transform);
      });
    svg.call(zoom);

    // Tooltip
    tooltipRef.current = d3
      .select(containerRef.current!)
      .append('div')
      .attr('class', 'tooltip')
      .style('display', 'none');

    // Simulation
    const simulation = d3
      .forceSimulation<SimNode>([])
      .force('link', d3.forceLink<SimNode, SimLink>([]).id((d) => d.id).distance(60))
      .force('charge', d3.forceManyBody().strength(-80))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(20));

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

  // Update data when nodes change — D3 data join, no teardown
  useEffect(() => {
    const simulation = simulationRef.current;
    const g = gRef.current;
    const tooltip = tooltipRef.current;
    if (!simulation || !g || !tooltip || nodes.length === 0 || dimensions.width === 0) return;

    // Preserve existing positions
    const existingPositions = new Map<string, { x: number; y: number }>();
    for (const n of simNodesRef.current) {
      if (n.x != null && n.y != null) {
        existingPositions.set(n.id, { x: n.x, y: n.y });
      }
    }

    const simNodes: SimNode[] = nodes.map((n) => ({
      ...n,
      ...(existingPositions.get(n.id) || {}),
    }));
    simNodesRef.current = simNodes;

    // Build links from store edges
    const nodeIdSet = new Set(simNodes.map((n) => n.id));
    const simLinks: SimLink[] = links
      .filter((l) => nodeIdSet.has(l.source) && nodeIdSet.has(l.target))
      .map((l, i) => ({
        id: `${l.source}-${l.type}-${l.target}-${i}`,
        source: l.source,
        target: l.target,
        type: l.type,
      }));

    // Update simulation
    simulation.nodes(simNodes);
    const linkForce = simulation.force('link') as d3.ForceLink<SimNode, SimLink>;
    linkForce.links(simLinks);

    // -- Links data join --
    const linksGroup = g.select<SVGGElement>('.links-group');

    // Lines
    const link = linksGroup
      .selectAll<SVGLineElement, SimLink>('line')
      .data(simLinks, (d) => d.id);
    link.exit().remove();
    const linkEnter = link.enter()
      .append('line')
      .attr('stroke', 'var(--edge-default)')
      .attr('stroke-opacity', 0.6)
      .attr('stroke-width', 1);
    const linkMerged = linkEnter.merge(link);

    // Edge labels
    const edgeLabel = linksGroup
      .selectAll<SVGTextElement, SimLink>('text.edge-label')
      .data(simLinks, (d) => d.id);
    edgeLabel.exit().remove();
    const edgeLabelEnter = edgeLabel.enter()
      .append('text')
      .attr('class', 'edge-label')
      .attr('text-anchor', 'middle')
      .attr('fill', 'var(--text-muted)')
      .attr('font-size', '7px')
      .attr('pointer-events', 'none');
    const edgeLabelMerged = edgeLabelEnter.merge(edgeLabel);
    edgeLabelMerged.text((d) => (d as SimLink & { type: string }).type || '');

    // -- Nodes data join --
    const nodesGroup = g.select<SVGGElement>('.nodes-group');
    const node = nodesGroup
      .selectAll<SVGGElement, SimNode>('g.graph-node')
      .data(simNodes, (d) => d.id);

    node.exit().remove();

    const nodeEnter = node.enter()
      .append('g')
      .attr('class', 'graph-node')
      .attr('cursor', 'grab');

    // Circle
    nodeEnter.append('circle')
      .attr('r', (d) => NODE_RADIUS[d.type] || 8)
      .attr('fill', (d) => NODE_COLORS[d.type] || '#8b949e')
      .attr('opacity', 0.85)
      .style('filter', 'url(#graph-glow)');

    // Labels for entities
    nodeEnter.filter((d) => d.type === 'Entity')
      .append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', -16)
      .attr('fill', 'var(--text-primary)')
      .attr('font-size', '10px')
      .attr('font-weight', '500')
      .attr('pointer-events', 'none')
      .text((d) => {
        const name = (d.data as Record<string, string>).name || '';
        return name.length > 12 ? name.slice(0, 12) + '...' : name;
      });

    const nodeMerged = nodeEnter.merge(node);

    // Drag
    nodeMerged.call(
      d3.drag<SVGGElement, SimNode>()
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

    // Tooltip
    nodeMerged
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

    // Tick
    simulation.on('tick', () => {
      linkMerged
        .attr('x1', (d) => ((d.source as unknown as { x: number }).x ?? 0))
        .attr('y1', (d) => ((d.source as unknown as { y: number }).y ?? 0))
        .attr('x2', (d) => ((d.target as unknown as { x: number }).x ?? 0))
        .attr('y2', (d) => ((d.target as unknown as { y: number }).y ?? 0));

      edgeLabelMerged
        .attr('x', (d) => {
          const s = d.source as unknown as { x: number };
          const t = d.target as unknown as { x: number };
          return ((s.x ?? 0) + (t.x ?? 0)) / 2;
        })
        .attr('y', (d) => {
          const s = d.source as unknown as { y: number };
          const t = d.target as unknown as { y: number };
          return ((s.y ?? 0) + (t.y ?? 0)) / 2 - 3;
        });

      nodeMerged.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    simulation.alpha(0.3).restart();
  }, [nodes, links, dimensions]);

  // Update SVG size
  useEffect(() => {
    if (!svgRef.current || dimensions.width === 0) return;
    const svg = d3.select(svgRef.current);
    svg.attr('width', dimensions.width).attr('height', dimensions.height);
  }, [dimensions]);

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
        {loading && nodes.length === 0 ? (
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
        ) : fetchError && nodes.length === 0 ? (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              color: 'var(--text-muted)',
              fontSize: '13px',
              flexDirection: 'column',
              gap: '8px',
            }}
          >
            <span>Failed to load graph data</span>
            <button className="panel-btn" onClick={fetchGraphData} style={{ width: 'auto', padding: '4px 12px', fontSize: '11px' }}>
              Retry
            </button>
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
            No graph data yet &mdash; make an observation to get started
          </div>
        ) : (
          <>
            <svg ref={svgRef} style={{ display: 'block', position: 'absolute', inset: 0 }} />
            <Legend />
          </>
        )}
      </div>
    </div>
  );
}
