import { create } from 'zustand';
import type { AgentStatus } from '../types';

interface AgentStore {
  agents: Map<string, AgentStatus>;
  setAgent: (status: AgentStatus) => void;
  setAgents: (agents: AgentStatus[]) => void;
  removeAgent: (agentId: string) => void;
  getAgentList: () => AgentStatus[];
}

export const useAgentStore = create<AgentStore>((set, get) => ({
  agents: new Map(),

  setAgent: (status) =>
    set((state) => {
      const agents = new Map(state.agents);
      agents.set(status.agent_id, status);
      return { agents };
    }),

  setAgents: (agents) =>
    set(() => {
      const map = new Map<string, AgentStatus>();
      agents.forEach((a) => map.set(a.agent_id, a));
      return { agents: map };
    }),

  removeAgent: (agentId) =>
    set((state) => {
      const agents = new Map(state.agents);
      agents.delete(agentId);
      return { agents };
    }),

  getAgentList: () => Array.from(get().agents.values()),
}));
