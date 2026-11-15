import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Button } from "@heroui/react";
import { BookOpen, Compass, Layers, Map as MapIcon, Pause, Play, SlidersHorizontal, X } from "lucide-react";
import Map, { Layer, Source } from "react-map-gl/maplibre";
import type { StyleSpecification } from "maplibre-gl";
import { useTheme } from "next-themes";
import "maplibre-gl/dist/maplibre-gl.css";
import { api } from "../api/client";
import { call, failureText } from "../api/http";
import { readSse } from "../api/sse";
import { apiUrl } from "../api/url";
import { Chip, Field, Input, Notice, Progress, Segmented, Select, Term } from "../components/ui";
import { useNames } from "../hooks/useNames";
import { useTr } from "../i18n";
import { useStore } from "../store/useStore";

const SEASONS = ["annual", "DJF", "MAM", "JJA", "SON"] as const;
const PALETTES = ["rdbu", "puor", "cividis"] as const;
const LAYERS = ["trend", "ai_class"] as const;
type LayerName = (typeof LAYERS)[number];

/** The same colour stops the tile renderer uses, for the map legend. */
const PALETTE_GRADIENTS: Record<string, string> = {
  rdbu: "linear-gradient(90deg,#2166ac,#67a9cf,#d1e5f0,#f7f7f7,#fddbc7,#ef8a62,#b2182b)",
  puor: "linear-gradient(90deg,#542788,#998ec3,#d8daeb,#f7f7f7,#fee0b6,#f1a340,#b35806)",
  cividis: "linear-gradient(90deg,#00204d,#31446b,#666970,#958f78,#cbba69,#ffea46)",
};
const AI_LEGEND: Array<[string, string, string]> = [
  ["#4477aa", "лінійна", "linear"],
  ["#ee6677", "стрибок", "step"],
  ["#ccbb44", "прискорення", "accelerating"],
  ["#66ccee", "сезонний зсув", "seasonal shift"],
];

/** Esri Gray Canvas basemap (no key needed): land and sea below the trend layer, place names above it. */
function basemap(dark: boolean): StyleSpecification {
  const flavour = dark ? "Dark" : "Light";
  const tiles = (layer: string) => [`https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_${flavour}_Gray_${layer}/MapServer/tile/{z}/{y}/{x}`];
  const attribution = "Esri, HERE, Garmin, © OpenStreetMap contributors";
  return {
    version: 8,
    sources: {
      base: { type: "raster", tiles: tiles("Base"), tileSize: 256, maxzoom: 16, attribution },
      labels: { type: "raster", tiles: tiles("Reference"), tileSize: 256, maxzoom: 16 },
    },
    layers: [
      { id: "base", type: "raster", source: "base" },
      { id: "labels", type: "raster", source: "labels" },
    ],
  };
}

/** The draft lives in the address, so a link reopens the same investigation. */
function useDraft() {
  const [params, setParams] = useSearchParams();
  const read = (key: string, fallback: string) => params.get(key) ?? fallback;
  const update = (patch: Record<string, string | null>) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        for (const [key, value] of Object.entries(patch)) {
          if (value === null || value === "") next.delete(key);
          else next.set(key, value);
        }
        return next;
      },
      { replace: true },
    );
  return { read, update };
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-xs font-semibold uppercase tracking-widest text-muted">{title}</h3>
      {children}
    </section>
  );
}

export function Explore() {
  const navigate = useNavigate();
  const tr = useTr();
  const names = useNames();
  const [welcome, setWelcome] = useState(() => {
    try {
      return localStorage.getItem("earthtrend.explore-welcome") !== "seen";
    } catch {
      return true;
    }
  });
  const hideWelcome = () => {
    setWelcome(false);
    try {
      localStorage.setItem("earthtrend.explore-welcome", "seen");
    } catch {
      // Storage may be blocked; the hint then shows again next time.
    }
  };
  const { resolvedTheme } = useTheme();
  const mapStyle = useMemo(() => basemap(resolvedTheme !== "light"), [resolvedTheme]);
  const token = useStore((state) => state.token);
  const role = useStore((state) => state.role);
  const language = useStore((state) => state.language);
  const draft = useDraft();

  const variableId = draft.read("variable", "");
  const regionId = draft.read("region", "");
  const season = draft.read("season", "annual");
  const fromYear = draft.read("from", "2000");
  const toYear = draft.read("to", "2024");
  const layer = draft.read("layer", "trend") as LayerName;
  const palette = draft.read("palette", "rdbu");
  const significantOnly = draft.read("sig", "") === "1";

  const [query, setQuery] = useState("");
  const [cmrQuery, setCmrQuery] = useState("");
  const [name, setName] = useState(tr("Моя точка", "My point"));
  const [lon, setLon] = useState("30.5");
  const [lat, setLat] = useState("48.4");
  const [radius, setRadius] = useState("50");
  const [year, setYear] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<{ progress: number; stage: string; message: string } | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [setupOpen, setSetupOpen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);

  const variables = useQuery({
    queryKey: ["variables", query],
    enabled: Boolean(token),
    queryFn: () => call(api.GET("/api/v1/variables", { params: { query: query ? { q: query } : {} } })),
  });
  const regions = useQuery({
    queryKey: ["regions"],
    enabled: Boolean(token),
    queryFn: () => call(api.GET("/api/v1/regions")),
  });
  const selectedVariable = variableId || variables.data?.[0]?.id || "";
  const selectedRegion = regionId || regions.data?.[0]?.id || "";
  // A link may carry an id the catalog does not know; show it instead of silently picking another one.
  const unknownVariable = Boolean(variableId && !query && variables.data && !variables.data.some((item) => item.id === variableId));
  const unknownRegion = Boolean(regionId && regions.data && !regions.data.some((item) => item.id === regionId));

  const detail = useQuery({
    queryKey: ["variable", selectedVariable],
    enabled: Boolean(token && selectedVariable),
    queryFn: () => call(api.GET("/api/v1/variables/{variable_id}", { params: { path: { variable_id: selectedVariable } } })),
  });
  const region = useQuery({
    queryKey: ["region", selectedRegion],
    enabled: Boolean(token && selectedRegion),
    queryFn: () => call(api.GET("/api/v1/regions/{region_id}", { params: { path: { region_id: selectedRegion } } })),
  });
  const potential = useQuery({
    queryKey: ["potential", selectedRegion],
    enabled: Boolean(token && selectedRegion),
    queryFn: () => call(api.GET("/api/v1/regions/{region_id}/potential", { params: { path: { region_id: selectedRegion } } })),
  });
  const products = useQuery({
    queryKey: ["tiles", selectedVariable],
    enabled: Boolean(selectedVariable),
    retry: 3,
    queryFn: () => call(api.GET("/api/v1/tiles/products", { params: { query: { variable_id: selectedVariable } } })),
  });

  // The grid for the chosen season; its period is the default period of the case.
  const product = useMemo(
    () => products.data?.find((item) => item.season === season) ?? products.data?.[0],
    [products.data, season],
  );
  const years = useMemo(() => product?.years ?? [], [product]);
  // A year frame shows that year's anomaly, so the legend switches to the frame scale.
  const frame = year !== null && Boolean(product?.frame_vmax);
  const scale = (frame ? product?.frame_vmax : product?.vmax) ?? 1;

  useEffect(() => {
    setYear(null);
    setPlaying(false);
  }, [product?.data_version, product?.season, selectedVariable]);

  useEffect(() => {
    if (!playing || years.length === 0) return;
    const timer = window.setInterval(() => {
      setYear((current) => {
        const index = current === null ? 0 : years.indexOf(current) + 1;
        return years[index % years.length];
      });
    }, 900);
    return () => window.clearInterval(timer);
  }, [playing, years]);

  const tileUrl = useMemo(() => {
    if (!product) return null;
    const extra = new URLSearchParams({ palette, significant_only: String(significantOnly) });
    if (year !== null) extra.set("year", String(year));
    return apiUrl(`${product.tile_url.replace("{product}", layer)}&${extra.toString()}`);
  }, [product, layer, palette, significantOnly, year]);

  const custom = useMutation({
    mutationFn: () =>
      call(api.POST("/api/v1/regions/custom", { body: { name, point: [Number(lon), Number(lat)], radius_km: Number(radius) } })),
    onSuccess: (created) => {
      draft.update({ region: created.id });
      setError(null);
    },
    onError: (reason) => setError(failureText(reason)),
  });
  const cmr = useMutation({
    mutationFn: () => call(api.POST("/api/v1/variables/cmr", { body: { query: cmrQuery } })),
    onSuccess: (created) => {
      draft.update({ variable: created.id });
      setError(null);
    },
    onError: (reason) => setError(failureText(reason)),
  });
  const cancel = useMutation({
    mutationFn: (id: string) => call(api.DELETE("/api/v1/jobs/{job_id}", { params: { path: { job_id: id } } })),
    onError: (reason) => setError(failureText(reason)),
  });

  const run = async () => {
    if (!token) {
      setError(tr("Сесія ще відкривається, спробуй за мить.", "The session is still opening, try again in a moment."));
      return;
    }
    setError(null);
    setJob(null);
    setRunning(true);
    try {
      const created = await call(
        api.POST("/api/v1/cases", {
          body: {
            variable_id: selectedVariable,
            region_id: selectedRegion,
            period_start: `${fromYear}-01`,
            period_end: `${toYear}-12`,
            season: season === "annual" ? null : season,
            language,
          },
        }),
      );
      if (created.status !== "queued" || !created.job_id) {
        navigate(`/case/${created.id}`);
        return;
      }
      const id = created.job_id;
      setJobId(id);
      setInfoOpen(true);
      const current = await call(api.GET("/api/v1/jobs/{job_id}", { params: { path: { job_id: id } } }));
      setJob({ progress: current.progress, stage: current.stage, message: current.message });
      let finished = false;
      await readSse(`/api/v1/jobs/${id}/events`, { method: "GET" }, (event, data) => {
        if (!data || typeof data !== "object") return;
        const body = data as { progress?: number; stage?: string; message?: string };
        setJob({ progress: body.progress ?? 0, stage: body.stage ?? event, message: body.message ?? "" });
        if (event === "completed") {
          finished = true;
          navigate(`/case/${created.id}`);
        } else if (body.stage === "failed" || body.stage === "cancelled") {
          finished = true;
          setError(
            body.stage === "failed"
              ? `${tr("Аналіз не вдався", "The analysis failed")}: ${body.message ?? ""}`
              : tr("Аналіз скасовано.", "The analysis was cancelled."),
          );
        }
      });
      if (!finished) setError(tr("Потік прогресу обірвався. Відкрий справу пізніше з журналу.", "The progress stream ended early. Open the case later from the journal."));
    } catch (reason) {
      const text = failureText(reason);
      setError(
        text.startsWith("data_not_ready")
          ? tr(
              "Для цієї пари змінна + регіон аналітика ще не порахувала дані. Спробуй іншу пару, наприклад вологу ґрунту на півдні України.",
              "Analytics has not computed this variable + region pair yet. Try another pair, for example soil moisture in southern Ukraine.",
            )
          : text,
      );
    } finally {
      setRunning(false);
    }
  };

  const yearOptions = useMemo(() => Array.from({ length: 2025 - 1980 }, (_, index) => String(1980 + index)), []);
  const variableName = (item: { name: string; name_uk?: string | null }) => (language === "uk" ? item.name_uk || item.name : item.name);

  const setup = (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-[var(--glass-border)] px-5 py-4">
        <h2 className="flex items-center gap-2 font-semibold text-foreground">
          <SlidersHorizontal size={18} className="text-accent" />
          {tr("Налаштування справи", "Investigation setup")}
        </h2>
        <button type="button" className="text-muted hover:text-foreground xl:hidden" onClick={() => setSetupOpen(false)} aria-label={tr("Закрити", "Close")}>
          <X size={18} />
        </button>
      </div>
      <div className="flex flex-1 flex-col gap-6 overflow-y-auto px-5 py-5">
        <Group title={tr("1. Що досліджуємо", "1. What to investigate")}>
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={tr("Пошук: температура, посуха…", "Search: temperature, drought…")} />
          <Select value={selectedVariable} onChange={(event) => draft.update({ variable: event.target.value })} aria-label={tr("Змінна", "Variable")}>
            {(variables.data ?? []).map((item) => (
              <option key={item.id} value={item.id}>{variableName(item)}</option>
            ))}
            {unknownVariable && <option value={variableId}>{variableId}</option>}
          </Select>
          {detail.data?.kid_description && <p className="text-xs text-muted">{detail.data.kid_description}</p>}
        </Group>
        <Group title={tr("2. Де", "2. Where")}>
          <Select value={selectedRegion} onChange={(event) => draft.update({ region: event.target.value })} aria-label={tr("Регіон", "Region")}>
            {(regions.data ?? []).map((item) => (
              <option key={item.id} value={item.id}>{language === "uk" ? item.name_uk || item.name : item.name}</option>
            ))}
            {unknownRegion && <option value={regionId}>{regionId}</option>}
          </Select>
          {(unknownVariable || unknownRegion) && (
            <Notice text={tr("Цього у каталозі немає — справа не відкриється. Обери інше зі списку.", "This is not in the catalog — the case will not open. Pick another one from the list.")} />
          )}
        </Group>
        <Group title={tr("3. За який час", "3. Over which years")}>
          <div className="grid grid-cols-2 gap-2">
            <Field label={tr("Від", "From")}>
              <Select value={fromYear} onChange={(event) => draft.update({ from: event.target.value })}>
                {yearOptions.map((item) => <option key={item} value={item}>{item}</option>)}
              </Select>
            </Field>
            <Field label={tr("До", "To")}>
              <Select value={toYear} onChange={(event) => draft.update({ to: event.target.value })}>
                {yearOptions.map((item) => <option key={item} value={item}>{item}</option>)}
              </Select>
            </Field>
          </div>
          <Segmented
            value={season as (typeof SEASONS)[number]}
            onChange={(value) => draft.update({ season: value })}
            options={SEASONS.map((item) => ({ value: item, label: item === "annual" ? tr("Рік", "Year") : names.season(item) }))}
          />
        </Group>
        <Group title={tr("Додатково (необов’язково)", "More (optional)")}>
          <details className="group rounded-xl border border-[var(--glass-border)] px-3 py-2 text-sm">
            <summary className="cursor-pointer select-none font-medium text-foreground">{tr("Свій регіон: точка і радіус", "Custom region: point and radius")}</summary>
            <div className="mt-3 flex flex-col gap-2">
              <Input value={name} onChange={(event) => setName(event.target.value)} aria-label={tr("Назва", "Name")} />
              <div className="grid grid-cols-3 gap-2">
                <Input value={lon} onChange={(event) => setLon(event.target.value)} aria-label={tr("Довгота", "Longitude")} placeholder="lon" />
                <Input value={lat} onChange={(event) => setLat(event.target.value)} aria-label={tr("Широта", "Latitude")} placeholder="lat" />
                <Input value={radius} onChange={(event) => setRadius(event.target.value)} aria-label={tr("Радіус, км", "Radius, km")} placeholder="km" />
              </div>
              <Button size="sm" variant="secondary" onClick={() => custom.mutate()} isDisabled={!token || custom.isPending}>
                {tr("Зберегти регіон", "Save region")}
              </Button>
            </div>
          </details>
          <details className="rounded-xl border border-[var(--glass-border)] px-3 py-2 text-sm">
            <summary className="cursor-pointer select-none font-medium text-foreground">{tr("Пошук у каталозі NASA CMR", "Search the NASA CMR catalog")}</summary>
            <div className="mt-3 flex flex-col gap-2">
              <Input value={cmrQuery} onChange={(event) => setCmrQuery(event.target.value)} placeholder="MOD13A3" />
              <Button size="sm" variant="secondary" onClick={() => cmr.mutate()} isDisabled={!token || role === "guest" || !cmrQuery || cmr.isPending}>
                {tr("Шукати", "Search")}
              </Button>
            </div>
          </details>
        </Group>
        <Notice text={error || (variables.isError ? failureText(variables.error) : null)} />
      </div>
      <div className="border-t border-[var(--glass-border)] p-4">
        <Button
          variant="primary"
          fullWidth
          onClick={() => void run()}
          isDisabled={running || !selectedVariable || !selectedRegion || Number(fromYear) >= Number(toYear)}
          className="h-12 rounded-xl text-base font-semibold"
        >
          <Play size={18} /> {running ? tr("Аналізуємо…", "Analysing…") : tr("Почати аналіз", "Run analysis")}
        </Button>
        <p className="mt-2 text-center text-xs text-muted">
          {tr("Система перевірить тренд шістьма способами й відкриє справу з вироком.", "The system checks the trend six ways and opens a case with a verdict.")}
        </p>
      </div>
    </div>
  );

  const info = (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-[var(--glass-border)] px-5 py-4">
        <h2 className="flex items-center gap-2 font-semibold text-foreground">
          <BookOpen size={18} className="text-accent" />
          {tr("Паспорт і підказки", "Passport and hints")}
        </h2>
        <button type="button" className="text-muted hover:text-foreground xl:hidden" onClick={() => setInfoOpen(false)} aria-label={tr("Закрити", "Close")}>
          <X size={18} />
        </button>
      </div>
      <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-5 py-5 text-sm">
        {job && (
          <div className="flex flex-col gap-2 rounded-xl border border-[var(--glass-border)] p-4">
            <div className="flex items-center justify-between">
              <span className="font-medium text-foreground">{job.stage}</span>
              <span className="tabular-nums text-muted">{job.progress}%</span>
            </div>
            <Progress value={job.progress} />
            <p className="text-xs text-muted">{job.message}</p>
            <Button size="sm" variant="ghost" onClick={() => jobId && cancel.mutate(jobId)} isDisabled={!jobId || !running || cancel.isPending}>
              {tr("Скасувати", "Cancel")}
            </Button>
          </div>
        )}
        {detail.data && (
          <div className="flex flex-col gap-2">
            <h3 className="text-lg font-semibold text-foreground">{variableName(detail.data)}</h3>
            <div className="flex flex-wrap gap-1.5">
              <Chip>{detail.data.units}</Chip>
              {detail.data.theme && <Chip tone="accent">{detail.data.theme}</Chip>}
              {detail.data.level && <Chip>{detail.data.level}</Chip>}
            </div>
            <p className="text-muted">{detail.data.kid_description}</p>
            {detail.data.links.length > 0 && (
              <ul className="mt-1 flex flex-col gap-1 text-xs text-muted">
                {detail.data.links.slice(0, 4).map((link) => (
                  <li key={`${link.source_id}-${link.target_id}`}>
                    <span className="font-medium text-foreground">{link.direction}</span> · {link.target_id}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {region.data && (
          <div className="flex items-center justify-between rounded-xl border border-[var(--glass-border)] px-4 py-3">
            <span className="flex items-center gap-2 text-foreground">
              <Compass size={16} className="text-accent" />
              {region.data.name}
            </span>
            <span className="text-xs tabular-nums text-muted">{Math.round(region.data.area_km2).toLocaleString()} km²</span>
          </div>
        )}
        {(potential.data ?? []).length > 0 && (
          <div className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-widest text-muted">{tr("Де тренд імовірний (M2)", "Where a trend is likely (M2)")}</h3>
            {(potential.data ?? []).map((hint) => (
              <button
                key={`${hint.variable_id}-${hint.season}`}
                type="button"
                className="flex flex-col gap-1.5 rounded-xl px-3 py-2 text-left transition-colors hover:bg-default"
                onClick={() => draft.update({ variable: hint.variable_id, season: hint.season })}
              >
                <span className="flex items-center justify-between text-foreground">
                  <span>{names.variable(hint.variable_id)} · {names.season(hint.season)}</span>
                  <span className="tabular-nums text-muted">{Math.round(hint.p_significant * 100)}%</span>
                </span>
                <Progress value={hint.p_significant * 100} className="h-1.5" />
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );

  return (
    <div className="relative flex h-[calc(100vh-61px)] w-full overflow-hidden">
      {(setupOpen || infoOpen) && (
        <button type="button" aria-label={tr("Закрити панель", "Close panel")} className="absolute inset-0 z-20 bg-black/40 xl:hidden" onClick={() => { setSetupOpen(false); setInfoOpen(false); }} />
      )}
      <aside
        className={`glass absolute inset-y-0 left-0 z-30 w-80 transition-transform duration-300 xl:static xl:translate-x-0 xl:rounded-none xl:border-y-0 xl:border-l-0 ${setupOpen ? "translate-x-0" : "-translate-x-full"}`}
      >
        {setup}
      </aside>

      <main className="relative min-w-0 flex-1">
        {welcome && (
          <div className="glass absolute right-3 top-3 z-20 max-w-sm rounded-2xl p-4 shadow-xl">
            <p className="mb-2 font-semibold text-foreground">{tr("Як користуватись", "How to use")}</p>
            <ol className="mb-3 list-decimal space-y-1 pl-5 text-sm text-muted">
              <li>{tr("Ліворуч обери, що досліджуємо — наприклад, температуру.", "On the left, pick what to investigate — for example, temperature.")}</li>
              <li>{tr("Обери регіон і роки.", "Pick a region and years.")}</li>
              <li>{tr("Натисни «Почати аналіз» — отримаєш вирок і пояснення.", "Press Run analysis — you get a verdict and an explanation.")}</li>
            </ol>
            <p className="mb-3 text-sm text-muted">{tr("Карта вже показує, де змінюється обрана величина по всьому світу.", "The map already shows where the chosen quantity changes worldwide.")}</p>
            <button type="button" className="text-sm font-medium text-accent hover:underline" onClick={hideWelcome}>{tr("Зрозуміло", "Got it")}</button>
          </div>
        )}
        <Map initialViewState={{ longitude: 31, latitude: 49, zoom: 3 }} mapStyle={mapStyle} style={{ width: "100%", height: "100%" }}>
          {tileUrl && (
            <Source key={tileUrl} id="trend" type="raster" tiles={[tileUrl]} tileSize={256}>
              <Layer id="trend-layer" type="raster" beforeId="labels" paint={{ "raster-opacity": 0.7, "raster-resampling": "linear" }} />
            </Source>
          )}
        </Map>

        <div className="absolute left-3 top-3 z-10 flex gap-2 xl:hidden">
          <Button size="sm" variant="secondary" onClick={() => setSetupOpen(true)}>
            <SlidersHorizontal size={16} /> {tr("Справа", "Setup")}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setInfoOpen(true)}>
            <BookOpen size={16} /> {tr("Паспорт", "Passport")}
          </Button>
        </div>

        <div className="glass absolute bottom-4 left-1/2 z-10 flex w-[min(640px,calc(100%-24px))] -translate-x-1/2 flex-col gap-3 rounded-2xl p-4 shadow-xl">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="flex items-center gap-2 text-sm font-medium text-foreground">
              <MapIcon size={16} className="text-accent" />
              {product ? `${tr("Сітка", "Grid")} ${product.period} · ${names.season(product.season)}` : tr("Для цієї змінної ще немає сітки", "No grid for this variable yet")}
            </span>
            {product && (
              <div className="flex items-center gap-2">
                <Segmented
                  value={layer}
                  onChange={(value) => draft.update({ layer: value })}
                  options={[
                    { value: "trend", label: <span className="flex items-center gap-1"><Layers size={14} /> {tr("Тренд", "Trend")}</span> },
                    { value: "ai_class", label: tr("Форма змін", "Change shape") },
                  ]}
                />
                {layer === "trend" && (
                  <Select className="w-auto py-1.5" value={palette} onChange={(event) => draft.update({ palette: event.target.value })} aria-label={tr("Палітра", "Palette")}>
                    {PALETTES.map((item) => <option key={item} value={item}>{item}</option>)}
                  </Select>
                )}
              </div>
            )}
          </div>
          {product && layer === "trend" && (
            <div className="flex flex-col gap-1">
              <div className="h-2.5 w-full rounded-full" style={{ background: PALETTE_GRADIENTS[palette] ?? PALETTE_GRADIENTS.rdbu }} />
              <div className="flex justify-between text-[11px] tabular-nums text-muted">
                <span>−{scale.toPrecision(2)}</span>
                <span>0</span>
                <span>
                  +{scale.toPrecision(2)} {names.units(selectedVariable)}{" "}
                  {frame ? tr(`аномалія ${year}`, `anomaly in ${year}`) : tr("за 10 років", "per decade")}
                </span>
              </div>
              <p className="text-xs text-muted">
                {frame
                  ? tr("Кадр року: червоне — вище норми 1991–2020, синє — нижче норми.", "Year frame: red — above the 1991–2020 normal, blue — below it.")
                  : tr("Червоне — величина зростає, синє — спадає, прозоре — майже без змін.", "Red — the quantity is rising, blue — falling, clear — barely changing.")}
              </p>
            </div>
          )}
          {product && layer === "ai_class" && (
            <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
              <Term id="ai_class">{tr("Що це?", "What is this?")}</Term>
              {AI_LEGEND.map(([colour, uk, en]) => (
                <span key={en} className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ background: colour }} />
                  {tr(uk, en)}
                </span>
              ))}
            </div>
          )}
          {product && (
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2 text-sm text-muted">
                <input type="checkbox" className="accent-[var(--color-accent)]" checked={significantOnly} onChange={(event) => draft.update({ sig: event.target.checked ? "1" : null })} />
                <Term id="fdr_only">{tr("Лише надійні тренди", "Reliable trends only")}</Term>
              </label>
              {years.length > 0 && layer === "trend" && (
                <div className="flex min-w-[220px] flex-1 items-center gap-2">
                  <Button size="sm" variant="ghost" isIconOnly onClick={() => setPlaying((value) => !value)} aria-label={tr("Таймлапс", "Timelapse")}>
                    {playing ? <Pause size={14} /> : <Play size={14} />}
                  </Button>
                  <input
                    type="range"
                    className="range flex-1"
                    min={0}
                    max={years.length}
                    value={year === null ? 0 : years.indexOf(year) + 1}
                    onChange={(event) => {
                      setPlaying(false);
                      const index = Number(event.target.value);
                      setYear(index === 0 ? null : years[index - 1]);
                    }}
                    aria-label={tr("Рік кадру", "Frame year")}
                  />
                  <span className="w-14 text-right text-sm font-semibold tabular-nums text-foreground">{year ?? tr("тренд", "trend")}</span>
                </div>
              )}
            </div>
          )}
        </div>
      </main>

      <aside
        className={`glass absolute inset-y-0 right-0 z-30 w-96 max-w-[90vw] transition-transform duration-300 xl:static xl:translate-x-0 xl:rounded-none xl:border-y-0 xl:border-r-0 ${infoOpen ? "translate-x-0" : "translate-x-full"}`}
      >
        {info}
      </aside>
    </div>
  );
}
