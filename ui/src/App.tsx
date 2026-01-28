import { useState, useCallback } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { AgentTopology } from './components/AgentTopology/AgentTopology';
import { EventStream } from './components/EventStream/EventStream';
import { GraphView } from './components/GraphView/GraphView';
import { StatusBar } from './components/StatusBar/StatusBar';

function getWsUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/v1/ws`;
}

type PanelId = 'topology' | 'events' | 'graph';

export default function App() {
  const { connected } = useWebSocket(getWsUrl());
  const [maximized, setMaximized] = useState<PanelId | null>(null);

  const toggleMaximize = useCallback((id: PanelId) => {
    setMaximized((prev) => (prev === id ? null : id));
  }, []);

  const isVisible = (id: PanelId) => maximized === null || maximized === id;
  const isFull = (id: PanelId) => maximized === id;

  return (
    <>
      {/* Header */}
      <header className="app-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div className="app-logo">M</div>
          <span className="app-title">Agentic Memory</span>
        </div>
        <div className="connection-status">
          <div className={`dot ${connected ? 'connected' : 'disconnected'}`} />
          {connected ? 'Live' : 'Reconnecting...'}
        </div>
      </header>

      {/* Main content */}
      <main className={`grid-layout ${maximized ? 'maximized' : ''}`}>
        {isVisible('topology') && (
          <div className={`grid-cell ${isFull('topology') ? 'cell-full' : 'cell-top-left'}`}>
            <AgentTopology
              maximized={isFull('topology')}
              onToggleMaximize={() => toggleMaximize('topology')}
            />
          </div>
        )}

        {isVisible('events') && (
          <div className={`grid-cell ${isFull('events') ? 'cell-full' : 'cell-top-right'}`}>
            <EventStream
              maximized={isFull('events')}
              onToggleMaximize={() => toggleMaximize('events')}
            />
          </div>
        )}

        {isVisible('graph') && (
          <div className={`grid-cell ${isFull('graph') ? 'cell-full' : 'cell-bottom'}`}>
            <GraphView
              maximized={isFull('graph')}
              onToggleMaximize={() => toggleMaximize('graph')}
            />
          </div>
        )}
      </main>

      {/* Status bar */}
      <StatusBar connected={connected} />
    </>
  );
}
