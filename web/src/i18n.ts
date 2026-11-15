import { useCallback } from "react";

import { useStore, type Language } from "./store/useStore";

export type Translate = (uk: string, en: string) => string;

/** Both strings sit next to each other at the call site, so a missing translation is visible in review. */
export function useTr(): Translate {
  const language = useStore((state) => state.language);
  return useCallback((uk: string, en: string) => (language === "en" ? en : uk), [language]);
}

/** True when the reader asked for every number of the evidence protocol. */
export function useExpert(): boolean {
  return useStore((state) => state.mode) === "expert";
}

export function useLanguage(): Language {
  return useStore((state) => state.language);
}

/** Verdict codes from verdict_rules_v1, as the reader sees them. */
export const VERDICT_LABELS: Record<string, [string, string]> = {
  proven: ["Доведено", "Proven"],
  strong: ["Сильні докази", "Strong evidence"],
  likely: ["Ймовірно", "Likely"],
  suspicious: ["Підозріло", "Suspicious"],
  no_evidence: ["Немає доказів", "No evidence"],
  inadmissible: ["Не можна розглянути", "Inadmissible"],
};

export function verdictLabel(code: string | null | undefined, tr: Translate): string {
  if (!code) return tr("без вироку", "no verdict");
  const pair = VERDICT_LABELS[code];
  return pair ? tr(pair[0], pair[1]) : code;
}
