import { useEffect, useState } from 'react';
import { useAgentStore } from '../../stores/agentStore';
import { useEventStore } from '../../stores/eventStore';
import { useGraphStore } from '../../stores/graphStore';

interface Stats {
  total_agents: number;
  active_agents: number;
  total_observations: number;
  total_claims: number;
  total_entities: number;
  websocket_clients: number;
}

export function StatusBar({ connected }: { connected: boolean }) {
  const agents = useAgentStore((s) => Array.from(s.agents.values()));
  const eventCount = useEventStore((s) => s.events.length);
  const nodeCount = useGraphStore((s) => s.nodes.length);
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const res = await fetch('/v1/stats');
        if (res.ok) {
          setStats(await res.json());
        }
      } catch {
        // API not available
      }
    };

    fetchStats();
    const interval = setInterval(fetchStats, 10000);
    return () => clearInterval(interval);
  }, []);

  const activeAgents = agents.filter((a) => a.status === 'running' || a.status === 'idle').length;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '8px 16px',
        background: 'var(--bg-tertiary)',
        borderTop: '1px solid var(--border)',
        fontSize: '11px',
        color: 'var(--text-secondary)',
        gap: '16px',
        flexShrink: 0,
      }}
    >
      <div style={{ display: 'flex', gap: '20px', alignItems: 'center' }}>
        <div className="connection-status">
          <div className={`dot ${connected ? 'connected' : 'disconnected'}`} />
          {connected ? 'Connected' : 'Disconnected'}
        </div>

        <Stat label="Agents" value={`${activeAgents} active`} />
        <Stat label="Events" value={eventCount.toString()} />
        <Stat label="Graph Nodes" value={nodeCount.toString()} />

        {stats && (
          <>
            <Stat label="Observations" value={stats.total_observations.toString()} />
            <Stat label="Claims" value={stats.total_claims.toString()} />
            <Stat label="Entities" value={stats.total_entities.toString()} />
          </>
        )}
      </div>

      <div style={{ color: 'var(--text-muted)', fontSize: '10px' }}>
        Agentic Memory System v0.2
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
      <span style={{ color: 'var(--text-muted)' }}>{label}:</span>
      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{value}</span>
    </div>
  );
}
