import { useAgentStore } from '../../stores/agentStore';
import { useEventStore } from '../../stores/eventStore';
import { useGraphStore } from '../../stores/graphStore';

export function StatusBar({ connected }: { connected: boolean }) {
  const agents = useAgentStore((s) => Array.from(s.agents.values()));
  const eventCount = useEventStore((s) => s.events.length);
  const nodeCount = useGraphStore((s) => s.nodes.length);

  const activeAgents = agents.filter((a) => a.status === 'running' || a.status === 'idle').length;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '6px 16px',
        background: 'var(--bg-tertiary)',
        borderTop: '1px solid var(--border)',
        fontSize: '11px',
        color: 'var(--text-secondary)',
        gap: '16px',
        flexShrink: 0,
      }}
    >
      <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
        <div className="connection-status">
          <div className={`dot ${connected ? 'connected' : 'disconnected'}`} />
          {connected ? 'Connected' : 'Disconnected'}
        </div>
        <Stat label="Nodes" value={`${activeAgents}/${agents.length}`} />
        <Stat label="Events" value={eventCount.toString()} />
        <Stat label="Graph" value={`${nodeCount} nodes`} />
      </div>

      <div style={{ color: 'var(--text-muted)', fontSize: '10px' }}>
        Agentic Memory v0.3
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
