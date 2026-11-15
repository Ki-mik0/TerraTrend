import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { GraduationCap, Languages, LogIn, Menu, Microscope, X } from "lucide-react";
import { ThemeSwitcher } from "./ThemeSwitcher";
import { ModeSwitch } from "./ui";
import { useTr } from "../i18n";
import { useStore } from "../store/useStore";

export function TopNav() {
  const location = useLocation();
  const role = useStore((state) => state.role);
  const language = useStore((state) => state.language);
  const setLanguage = useStore((state) => state.setLanguage);
  const mode = useStore((state) => state.mode);
  const setMode = useStore((state) => state.setMode);
  const tr = useTr();
  const signedIn = Boolean(role) && role !== "guest";
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => setMenuOpen(false), [location.pathname]);

  const tabs = [
    { path: "/", label: tr("Головна", "Home") },
    { path: "/explore", label: tr("Розслідування", "Explore") },
    { path: "/radar", label: tr("Радар", "Radar") },
    { path: "/compare", label: tr("Порівняння", "Compare") },
    { path: "/learn", label: tr("Лабораторія", "Lab") },
    { path: "/journal", label: tr("Журнал", "Journal") },
    { path: "/assistant", label: tr("Асистент", "Assistant") },
  ];
  if (role === "teacher" || role === "admin") tabs.push({ path: "/teacher", label: tr("Вчитель", "Teacher") });
  if (role === "admin") tabs.push({ path: "/admin", label: tr("Адмін", "Admin") });

  const isActive = (path: string) =>
    path === "/" ? location.pathname === "/" : location.pathname === path || location.pathname.startsWith(`${path}/`);

  return (
    <nav className="sticky top-0 z-50 flex w-full items-center justify-between gap-4 border-b border-[var(--glass-border)] bg-background/70 px-4 py-3 backdrop-blur-lg backdrop-saturate-150 sm:px-6">
      <div className="flex min-w-0 items-center gap-6">
        <Link to="/" className="shrink-0 text-xl font-bold tracking-tight text-foreground sm:text-2xl">
          Terra<span className="text-gradient">Trend</span>
        </Link>
        <ul className="hidden min-w-0 items-center gap-1 overflow-x-auto scrollbar-none md:flex">
          {tabs.map((tab) => {
            const active = isActive(tab.path);
            return (
              <li key={tab.path} className="relative">
                <Link
                  to={tab.path}
                  aria-current={active ? "page" : undefined}
                  className={`block whitespace-nowrap rounded-lg px-3 py-2 text-sm transition-colors ${
                    active ? "font-semibold text-foreground" : "text-muted hover:bg-default hover:text-foreground"
                  }`}
                >
                  {tab.label}
                </Link>
                {active && <span className="bg-gradient-brand absolute inset-x-3 -bottom-[13px] h-0.5 rounded-full" />}
              </li>
            );
          })}
        </ul>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <button
          type="button"
          className="hidden h-9 items-center gap-1.5 rounded-lg px-2.5 text-sm font-medium text-muted transition-colors hover:bg-default hover:text-foreground md:flex"
          onClick={() => setMode(mode === "simple" ? "expert" : "simple")}
          title={mode === "simple" ? tr("Показати всі числа і тести", "Show every number and test") : tr("Пояснювати простими словами", "Explain in plain words")}
        >
          {mode === "simple" ? <GraduationCap size={16} /> : <Microscope size={16} />}
          {mode === "simple" ? tr("Просто", "Simple") : tr("Експерт", "Expert")}
        </button>
        <button
          type="button"
          className="flex h-9 items-center gap-1.5 rounded-lg px-2.5 text-sm font-medium text-muted transition-colors hover:bg-default hover:text-foreground"
          onClick={() => setLanguage(language === "uk" ? "en" : "uk")}
          aria-label={tr("Перемкнути мову", "Switch language")}
        >
          <Languages size={16} />
          {language === "uk" ? "EN" : "УКР"}
        </button>
        <ThemeSwitcher />
        <button
          type="button"
          className="flex h-9 w-9 items-center justify-center rounded-lg text-muted hover:bg-default hover:text-foreground md:hidden"
          onClick={() => setMenuOpen((value) => !value)}
          aria-expanded={menuOpen}
          aria-label={tr("Меню", "Menu")}
        >
          {menuOpen ? <X size={18} /> : <Menu size={18} />}
        </button>
        <Link
          to="/session"
          className={`ml-1 hidden h-9 items-center gap-1.5 rounded-lg px-3 text-sm font-medium transition-colors sm:flex ${
            signedIn ? "bg-default text-foreground hover:bg-default-hover" : "bg-gradient-brand text-white hover:opacity-90"
          }`}
        >
          {signedIn ? (
            <>
              <span className="h-2 w-2 rounded-full bg-success" />
              {role}
            </>
          ) : (
            <>
              <LogIn size={16} />
              {tr("Увійти", "Sign in")}
            </>
          )}
        </Link>
      </div>
      {menuOpen && (
        <div className="absolute inset-x-3 top-full mt-2 rounded-2xl border border-[var(--glass-border)] bg-surface p-2 shadow-2xl md:hidden">
          {tabs.map((tab) => (
            <Link
              key={tab.path}
              to={tab.path}
              className={`block rounded-xl px-4 py-3 text-base ${isActive(tab.path) ? "bg-accent-soft font-semibold text-foreground" : "text-muted hover:bg-default hover:text-foreground"}`}
            >
              {tab.label}
            </Link>
          ))}
          <div className="mt-1 border-t border-[var(--glass-border)] px-2 pt-3 pb-1">
            <ModeSwitch className="w-full" />
          </div>
          <Link
            to="/session"
            className="mt-1 flex items-center gap-2 rounded-xl border-t border-[var(--glass-border)] px-4 py-3 text-base font-medium text-accent sm:hidden"
          >
            <LogIn size={16} /> {signedIn ? role : tr("Увійти", "Sign in")}
          </Link>
        </div>
      )}
    </nav>
  );
}
