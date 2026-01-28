import type { ReactNode } from 'react';

interface PanelProps {
  title: string;
  children: ReactNode;
  maximized?: boolean;
  onToggleMaximize?: () => void;
  extra?: ReactNode;
}

export function Panel({ title, children, maximized, onToggleMaximize, extra }: PanelProps) {
  return (
    <div className="panel">
      <div className="panel-header">
        <h2>{title}</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {extra}
          {onToggleMaximize && (
            <button
              onClick={onToggleMaximize}
              className="panel-btn"
              title={maximized ? 'Restore' : 'Maximize'}
            >
              {maximized ? '\u25F4' : '\u25F2'}
            </button>
          )}
        </div>
      </div>
      <div className="panel-body">
        {children}
      </div>
    </div>
  );
}
