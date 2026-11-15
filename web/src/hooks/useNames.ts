/**
 * Human names for the ids the API speaks in: variables, regions, seasons and units.
 * The catalog queries share their cache keys with Explore and Compare, so this costs no extra calls.
 */
import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { call } from "../api/http";
import { useStore } from "../store/useStore";

const SEASONS: Record<string, [string, string]> = {
  annual: ["Увесь рік", "Whole year"],
  DJF: ["Зима", "Winter"],
  MAM: ["Весна", "Spring"],
  JJA: ["Літо", "Summer"],
  SON: ["Осінь", "Autumn"],
};

/** Catalog units as a reader writes them; a temperature difference in K equals one in °C. */
const UNITS: Record<string, [string, string]> = {
  K: ["°C", "°C"],
  "°C": ["°C", "°C"],
  "1": ["", ""],
  mm: ["мм", "mm"],
  "mm/day": ["мм/день", "mm/day"],
  "kg/m2": ["кг/м²", "kg/m²"],
  day: ["днів", "days"],
};

export function useNames() {
  const token = useStore((state) => state.token);
  const language = useStore((state) => state.language);
  const variables = useQuery({
    queryKey: ["variables", ""],
    enabled: Boolean(token),
    staleTime: 10 * 60 * 1000,
    queryFn: () => call(api.GET("/api/v1/variables")),
  });
  const regions = useQuery({
    queryKey: ["regions"],
    enabled: Boolean(token),
    staleTime: 10 * 60 * 1000,
    queryFn: () => call(api.GET("/api/v1/regions")),
  });
  const pick = useCallback((pair: [string, string]) => (language === "en" ? pair[1] : pair[0]), [language]);

  const passport = useCallback((id: string) => variables.data?.find((item) => item.id === id), [variables.data]);

  const variable = useCallback(
    (id: string) => {
      const found = passport(id);
      if (!found) return id;
      return language === "uk" ? found.name_uk || found.name : found.name;
    },
    [passport, language],
  );

  const region = useCallback(
    (id: string) => {
      const found = regions.data?.find((item) => item.id === id);
      if (!found) return id;
      return language === "uk" ? found.name_uk || found.name : found.name;
    },
    [regions.data, language],
  );

  const season = useCallback((code: string | null | undefined) => pick(SEASONS[code ?? "annual"] ?? [code ?? "", code ?? ""]), [pick]);

  /** Units of a variable, ready to follow a number ("°C", "мм/день"); empty for a dimensionless share. */
  const units = useCallback(
    (id: string) => {
      const raw = passport(id)?.units ?? "";
      return UNITS[raw] ? pick(UNITS[raw]) : raw;
    },
    [passport, pick],
  );

  return { variable, region, season, units, passport, ready: Boolean(variables.data && regions.data) };
}
