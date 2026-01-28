import { useWebSocket } from './hooks/useWebSocket';
import { AgentTopology } from './components/AgentTopology/AgentTopology';
import { EventStream } from './components/EventStream/EventStream';
import { GraphView } from './components/GraphView/GraphView';
import { StatusBar } from './components/StatusBar/StatusBar';

function getWsUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  // In dev mode, vite proxies /v1 to API
  return `${protocol}//${window.location.host}/v1/ws`;
}

export default function App() {
  const { connected } = useWebSocket(getWsUrl());

  return (
    <>
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 20px',
          background: 'var(--bg-secondary)',
          borderBottom: '1px solid var(--border)',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div
            style={{
              width: '24px',
              height: '24px',
              borderRadius: '6px',
              background: 'linear-gradient(135deg, #58a6ff 0%, #3fb950 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '12px',
              fontWeight: 700,
            }}
          >
            M
          </div>
          <span style={{ fontSize: '14px', fontWeight: 600, letterSpacing: '-0.3px' }}>
            Agentic Memory
          </span>
        </div>

        <div className="connection-status">
          <div className={`dot ${connected ? 'connected' : 'disconnected'}`} />
          {connected ? 'Live' : 'Reconnecting...'}
        </div>
      </div>

      {/* Main content */}
      <div
        style={{
          flex: 1,
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gridTemplateRows: '1fr 1fr',
          gap: '1px',
          background: 'var(--border)',
          overflow: 'hidden',
        }}
      >
        {/* Top left: Agent Topology */}
        <div style={{ background: 'var(--bg-primary)', padding: '8px' }}>
          <AgentTopology />
        </div>

        {/* Top right: Event Stream */}
        <div style={{ background: 'var(--bg-primary)', padding: '8px' }}>
          <EventStream />
        </div>

        {/* Bottom: Knowledge Graph (spans full width) */}
        <div style={{ background: 'var(--bg-primary)', padding: '8px', gridColumn: '1 / -1' }}>
          <GraphView />
        </div>
      </div>

      {/* Status bar */}
      <StatusBar connected={connected} />
    </>
  );
}
