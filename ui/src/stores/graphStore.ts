import { create } from 'zustand';
import type { GraphNode, GraphLink } from '../types';

interface GraphStore {
  nodes: GraphNode[];
  links: GraphLink[];
  refreshCounter: number;
  setNodes: (nodes: GraphNode[]) => void;
  addNode: (node: GraphNode) => void;
  setLinks: (links: GraphLink[]) => void;
  addLink: (link: GraphLink) => void;
  triggerRefresh: () => void;
}

export const useGraphStore = create<GraphStore>((set) => ({
  nodes: [],
  links: [],
  refreshCounter: 0,

  setNodes: (nodes) => set({ nodes }),

  addNode: (node) =>
    set((state) => {
      if (state.nodes.find((n) => n.id === node.id)) return state;
      return { nodes: [...state.nodes, node] };
    }),

  setLinks: (links) => set({ links }),

  addLink: (link) =>
    set((state) => ({ links: [...state.links, link] })),

  triggerRefresh: () =>
    set((state) => ({ refreshCounter: state.refreshCounter + 1 })),
}));
