import { useEffect, useRef, useCallback, useState } from 'react';
import type { WSMessage } from '../types';
import { useAgentStore } from '../stores/agentStore';
import { useEventStore } from '../stores/eventStore';

const RECONNECT_DELAY = 3000;

export function useWebSocket(url: string) {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();

  const { setAgent, setAgents, removeAgent } = useAgentStore();
  const { addEvent } = useEventStore();

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      console.log('WebSocket connected');
    };

    ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        handleMessage(msg);
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };

    ws.onclose = () => {
      setConnected(false);
      console.log('WebSocket disconnected, reconnecting...');
      reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY);
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      ws.close();
    };

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  const handleMessage = useCallback(
    (msg: WSMessage) => {
      switch (msg.type) {
        case 'snapshot':
          setAgents(msg.data.agents);
          break;
        case 'agent_status':
          setAgent(msg.data);
          break;
        case 'agent_lifecycle':
          if (msg.data.event === 'deregistered') {
            removeAgent(msg.data.agent_id);
          }
          break;
        case 'memory_event':
          addEvent({
            id: msg.data.id || crypto.randomUUID(),
            event: msg.data.event,
            timestamp: msg.data.timestamp || new Date().toISOString(),
            source: msg.data.source,
            raw_content: msg.data.raw_content,
            text: msg.data.text,
          });
          break;
        case 'pong':
          break;
      }
    },
    [setAgent, setAgents, removeAgent, addEvent]
  );

  const send = useCallback((data: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { connected, send };
}
