import { useEventStore } from '../../stores/eventStore';
import type { MemoryEvent } from '../../types';

const EVENT_COLORS: Record<string, string> = {
  observation: 'var(--event-observation)',
  claim: 'var(--event-claim)',
  inference: 'var(--event-inference)',
  contradiction: 'var(--event-contradiction)',
};

const EVENT_ICONS: Record<string, string> = {
  observation: '\u25CF', // ●
  claim: '\u25CB',       // ○
  inference: '\u25D0',   // ◐
  contradiction: '\u25C6', // ◆
};

function formatTime(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', { hour12: false });
  } catch {
    return '--:--:--';
  }
}

function EventCard({ event }: { event: MemoryEvent }) {
  const color = EVENT_COLORS[event.event] || 'var(--text-secondary)';
  const icon = EVENT_ICONS[event.event] || '\u25CF';
  const content = event.raw_content || event.text || '';
  const label = event.event.toUpperCase().slice(0, 3);

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: '10px',
        padding: '8px 0',
        borderBottom: '1px solid var(--border)',
        animation: 'slideIn 0.3s ease-out',
      }}
    >
      <span style={{ color, fontSize: '14px', flexShrink: 0, marginTop: '1px' }}>
        {icon}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '2px' }}>
          <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
            {formatTime(event.timestamp)}
          </span>
          <span
            style={{
              fontSize: '9px',
              fontWeight: 700,
              color,
              background: `${color}15`,
              padding: '1px 5px',
              borderRadius: '3px',
              letterSpacing: '0.5px',
            }}
          >
            {label}
          </span>
          {event.source && (
            <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
              via {event.source}
            </span>
          )}
        </div>
        <div
          style={{
            fontSize: '12px',
            color: 'var(--text-primary)',
            lineHeight: '1.4',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {content || '(empty)'}
        </div>
      </div>
    </div>
  );
}

export function EventStream() {
  const events = useEventStore((s) => s.events);

  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="panel-header">
        <h2>Event Stream</h2>
        <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
          {events.length} event{events.length !== 1 ? 's' : ''}
        </span>
      </div>
      <div className="panel-body" style={{ padding: '0 var(--panel-padding)' }}>
        {events.length === 0 ? (
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
            Waiting for events...
          </div>
        ) : (
          events.map((e, i) => <EventCard key={`${e.id}-${i}`} event={e} />)
        )}
      </div>
    </div>
  );
}
