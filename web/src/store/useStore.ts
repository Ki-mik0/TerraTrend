import { create } from "zustand";

const SESSION_KEY = "earthtrend.session";
const LANGUAGE_KEY = "earthtrend.language";
const MODE_KEY = "earthtrend.mode";

export type Language = "uk" | "en";
/** "simple" explains results in words; "expert" shows every number of the evidence protocol. */
export type Mode = "simple" | "expert";

export interface Session {
  token: string;
  userId: string;
  role: string;
}

interface AppState {
  token: string | null;
  userId: string | null;
  role: string | null;
  language: Language;
  mode: Mode;
  setSession: (session: Session) => void;
  clearSession: () => void;
  setLanguage: (language: Language) => void;
  setMode: (mode: Mode) => void;
}

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage can be blocked (private mode); the session then lives only in memory.
  }
}

const saved = read<Session | null>(SESSION_KEY, null);
const savedLanguage = read<Language>(LANGUAGE_KEY, "uk");
const savedMode = read<Mode>(MODE_KEY, "simple");

export const useStore = create<AppState>((set) => ({
  token: saved?.token || null,
  userId: saved?.userId ?? null,
  role: saved?.role ?? null,
  language: savedLanguage === "en" ? "en" : "uk",
  mode: savedMode === "expert" ? "expert" : "simple",
  setSession: (session) =>
    set((state) => {
      if (state.token === session.token && state.userId === session.userId && state.role === session.role) {
        return state;
      }
      write(SESSION_KEY, session);
      return { token: session.token, userId: session.userId, role: session.role };
    }),
  clearSession: () => {
    write(SESSION_KEY, null);
    set({ token: null, userId: null, role: null });
  },
  setMode: (mode) => {
    write(MODE_KEY, mode);
    set({ mode });
  },
  setLanguage: (language) => {
    write(LANGUAGE_KEY, language);
    set({ language });
  },
}));
