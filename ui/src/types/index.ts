// Agent status from the API
export interface AgentStatus {
  agent_id: string;
  agent_type: string;
  tags: string[];
  timestamp: string;
  started_at: string;
  uptime_seconds: number;
  status: 'running' | 'idle' | 'error' | 'stopping' | 'stale' | 'dead';
  last_action: string;
  last_action_at: string | null;
  items_processed: number;
  queue_depth: number;
  processing_time_avg_ms: number;
  error_count: number;
  memory_mb: number;
  push_interval_seconds: number;
}

// Memory events
export interface MemoryEvent {
  id: string;
  event: 'observation' | 'claim' | 'inference' | 'contradiction';
  timestamp: string;
  source?: string;
  raw_content?: string;
  text?: string;
  subject_text?: string;
  predicate_text?: string;
  object_text?: string;
}

// Graph nodes for visualization
export interface GraphNode {
  id: string;
  type: string;
  data: Record<string, unknown>;
  // D3 simulation fields
  x?: number;
  y?: number;
  fx?: number | null;
  fy?: number | null;
}

export interface GraphLink {
  source: string;
  target: string;
  type: string;
}

// WebSocket message types
export type WSMessage =
  | { type: 'agent_status'; data: AgentStatus }
  | { type: 'agent_lifecycle'; data: { event: string; agent_id: string; agent_type: string } }
  | { type: 'memory_event'; data: MemoryEvent }
  | { type: 'graph_update'; data: { operation: string; [key: string]: unknown } }
  | { type: 'system_stats'; data: SystemStats }
  | { type: 'snapshot'; data: { agents: AgentStatus[] } }
  | { type: 'pong' };

// Node info within a node-type group
export interface NodeInfo {
  agent_id: string;
  status: string;
  uptime_seconds: number;
  capabilities: string[];
}

export interface SystemStats {
  network: {
    total_nodes: number;
    active_nodes: number;
    websocket_clients: number;
    nodes_by_type: Record<string, number>;
  };
  knowledge: {
    observations: number;
    statements: number;
    concepts: number;
    sources: number;
    relationships: number;
  };
  nodes: Record<string, NodeInfo[]>;
  // Legacy fields
  total_agents: number;
  active_agents: number;
  websocket_clients: number;
}
