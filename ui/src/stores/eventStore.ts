import { create } from 'zustand';
import type { MemoryEvent } from '../types';

const MAX_EVENTS = 200;

interface EventStore {
  events: MemoryEvent[];
  addEvent: (event: MemoryEvent) => void;
  clearEvents: () => void;
}

export const useEventStore = create<EventStore>((set) => ({
  events: [],

  addEvent: (event) =>
    set((state) => ({
      events: [event, ...state.events].slice(0, MAX_EVENTS),
    })),

  clearEvents: () => set({ events: [] }),
}));
