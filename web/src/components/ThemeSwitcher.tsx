import { useEffect, useState } from "react";
import { useTheme } from "../theme";
import { Moon, Sun } from "lucide-react";

import { useTr } from "../i18n";

export function ThemeSwitcher() {
  const { resolvedTheme, setTheme } = useTheme();
  const tr = useTr();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);
  if (!mounted) return <span className="h-9 w-9" />;

  const dark = resolvedTheme !== "light";
  return (
    <button
      type="button"
      onClick={() => setTheme(dark ? "light" : "dark")}
      className="flex h-9 w-9 items-center justify-center rounded-lg text-muted transition-colors hover:bg-default hover:text-foreground"
      aria-label={dark ? tr("Світла тема", "Light theme") : tr("Темна тема", "Dark theme")}
      title={dark ? tr("Світла тема", "Light theme") : tr("Темна тема", "Dark theme")}
    >
      {dark ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  );
}
