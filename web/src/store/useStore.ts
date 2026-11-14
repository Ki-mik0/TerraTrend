import { create } from 'zustand';

interface AppState {
    variable: string;
    period: [number, number];
    region: any | null;
    setVariable: (v: string) => void;
    setPeriod: (p: [number, number]) => void;
    setRegion: (r: any) => void;
}

export const useStore = create<AppState>((set) => ({
    variable: 'lst_day',
    period: [2010, 2023],
    region: null,
    setVariable: (variable) => set({ variable }),
    setPeriod: (period) => set({ period }),
    setRegion: (region) => set({ region }),
}));