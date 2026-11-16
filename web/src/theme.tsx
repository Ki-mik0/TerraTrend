import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Theme = "light" | "dark";

/** Same key as before, so a reader's saved choice survives. index.html applies it before React starts. */
const STORAGE_KEY = "theme";

type ThemeState = { resolvedTheme: Theme; theme: Theme; setTheme: (theme: Theme) => void };

const ThemeContext = createContext<ThemeState>({ resolvedTheme: "dark", theme: "dark", setTheme: () => undefined });

function stored(fallback: Theme): Theme {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : fallback;
  } catch {
    return fallback;
  }
}

/** Light or dark, kept as a class on <html> and in localStorage. */
export function ThemeProvider({ children, defaultTheme = "dark" }: { children: ReactNode; defaultTheme?: Theme }) {
  const [theme, setThemeState] = useState<Theme>(() => stored(defaultTheme));

  useEffect(() => {
    const root = document.documentElement;
    root.classList.remove("light", "dark");
    root.classList.add(theme);
    root.style.colorScheme = theme;
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* private mode: the choice lasts for this visit only */
    }
  }, []);

  const value = useMemo(() => ({ resolvedTheme: theme, theme, setTheme }), [theme, setTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeState {
  return useContext(ThemeContext);
}
