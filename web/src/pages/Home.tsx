import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@heroui/react";
import {
  Activity,
  ArrowRight,
  Building2,
  Clock,
  FlaskConical,
  GitBranch,
  Layers,
  ScanSearch,
  Sparkles,
  Split,
  Users,
} from "lucide-react";
import type { ReactNode } from "react";
import { api } from "../api/client";
import { call, failureText } from "../api/http";
import { Chip, Notice, Panel, Skeleton, Slope, VerdictBadge } from "../components/ui";
import { useNames } from "../hooks/useNames";
import { useTr } from "../i18n";
import { useStore } from "../store/useStore";

/** One icon per evidence tool of a demo case. */
const TOOL_ICONS: Record<string, ReactNode> = {
  vertical_profile: <Layers size={18} />,
  split: <Split size={18} />,
  witnesses: <Users size={18} />,
  alibi: <ScanSearch size={18} />,
  urban_contrast: <Building2 size={18} />,
  years_to_proof: <Clock size={18} />,
  story: <Sparkles size={18} />,
};

export function Home() {
  const navigate = useNavigate();
  const token = useStore((state) => state.token);
  const language = useStore((state) => state.language);
  const tr = useTr();
  const names = useNames();
  const demos = useQuery({
    queryKey: ["demos", language, token],
    enabled: Boolean(token),
    queryFn: () => call(api.GET("/api/v1/education/demos", { params: { query: { lang: language } } })),
  });
  const radar = useQuery({
    queryKey: ["radar", "strongest", 1, language, "teaser"],
    queryFn: () => call(api.GET("/api/v1/radar", { params: { query: { feed: "strongest", lang: language, page: 1, page_size: 3 } } })),
  });

  return (
    <div className="flex w-full flex-col">
      <section className="relative flex flex-col items-center justify-center overflow-hidden px-6 pt-24 pb-28 text-center">
        <span className="mb-6 rounded-full bg-emerald-500/10 px-3 py-1 text-xs font-medium text-emerald-500">
          NASA Space Apps Challenge 2024
        </span>
        <h1 className="mb-6 max-w-4xl text-5xl font-bold tracking-tight text-foreground md:text-7xl">
          TerraTrend <span className="bg-gradient-to-r from-blue-500 to-emerald-500 bg-clip-text text-transparent">Detective</span>
        </h1>
        <p className="mb-10 max-w-3xl text-xl leading-relaxed text-muted md:text-2xl">
          {tr(
            "Розслідуй значущі зміни у взаємопов’язаній системі Землі. Збирай докази, звіряй джерела і відрізняй справжні тренди від випадковості.",
            "Investigate significant changes in the Earth's interconnected system. Gather evidence, cross-validate sources, and expose the true climate trends.",
          )}
        </p>
        <div className="flex flex-col gap-4 sm:flex-row">
          <Button onClick={() => navigate("/explore")} variant="primary" className="flex items-center gap-2 rounded-xl px-8 py-6 text-lg font-medium shadow-lg shadow-brand-from/30">
            {tr("Почати розслідування", "Start investigation")} <ArrowRight size={18} />
          </Button>
          <Button onClick={() => navigate("/radar")} variant="outline" className="flex items-center gap-2 rounded-xl px-8 py-6 text-lg font-medium">
            <Activity size={18} /> {tr("Відкрити радар", "Open Trend Radar")}
          </Button>
        </div>
      </section>

      <section className="mx-auto w-full max-w-7xl px-4 pb-4 sm:px-6 lg:px-10">
        <p className="mb-1 text-xs font-semibold uppercase tracking-widest text-accent">{tr("Як це працює", "How it works")}</p>
        <h2 className="mb-6 text-3xl font-bold tracking-tight text-foreground">{tr("Три кроки до відповіді", "Three steps to an answer")}</h2>
        <ol className="grid grid-cols-1 gap-5 md:grid-cols-3">
          {[
            [
              tr("Обери що і де", "Pick what and where"),
              tr("Наприклад, температуру повітря на півночі України за 2000–2024 роки. Дані беремо з супутників NASA.", "For example, air temperature in northern Ukraine over 2000–2024. The data comes from NASA satellites."),
            ],
            [
              tr("Система перевіряє докази", "The system checks the evidence"),
              tr("Не один тест, а шість: чи не випадковість, чи бачать те саме інші джерела, чи не винне Ель-Ніньйо тощо.", "Not one test but six: is it chance, do other sources agree, is El Niño to blame, and so on."),
            ],
            [
              tr("Отримай вирок простими словами", "Get a verdict in plain words"),
              tr("Від «доведено» до «немає доказів» — з поясненням, чому, і з картою, де саме змінюється.", "From “proven” to “no evidence” — with the reasons and a map of where it changes."),
            ],
          ].map(([title, text], index) => (
            <li key={title}>
              <Panel className="h-full">
                <span className="bg-gradient-brand mb-4 flex h-9 w-9 items-center justify-center rounded-full font-semibold text-white">{index + 1}</span>
                <h3 className="mb-2 text-lg font-semibold text-foreground">{title}</h3>
                <p className="text-muted">{text}</p>
              </Panel>
            </li>
          ))}
        </ol>
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <Button variant="primary" onClick={() => navigate("/explore?variable=merra2_t2m&region=ukraine_north&from=2000&to=2024")}>
            {tr("Спробувати на прикладі", "Try an example")} <ArrowRight size={16} />
          </Button>
          <span className="text-sm text-muted">{tr("Температура повітря на півночі України — реальні дані NASA.", "Air temperature in northern Ukraine — real NASA data.")}</span>
        </div>
      </section>

      <section className="mx-auto w-full max-w-7xl px-4 py-12 sm:px-6 lg:px-10">
        <div className="mb-8 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-widest text-accent">{tr("Навчання", "Learn")}</p>
            <h2 className="text-3xl font-bold tracking-tight text-foreground">{tr("Демо-справи", "Demo cases")}</h2>
            <p className="mt-2 max-w-2xl text-lg text-muted">
              {tr("Сім справ, які крок за кроком показують, як працює кожен інструмент доказів.", "Seven cases that show, step by step, how each evidence tool works.")}
            </p>
          </div>
          <Button variant="ghost" onClick={() => navigate("/learn")} className="self-start md:self-auto">
            <FlaskConical size={16} /> {tr("Уся лабораторія", "Whole lab")}
          </Button>
        </div>
        {demos.isError && <Notice text={failureText(demos.error)} />}
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {demos.isLoading || !demos.data
            ? Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-52" />)
            : demos.data.map((demo, index) => (
                <Panel
                  key={demo.id}
                  as="button"
                  type="button"
                  interactive
                  className="flex flex-col gap-3"
                  onClick={() => navigate(`/learn?demo=${demo.id}`)}
                >
                  <div className="flex items-center justify-between">
                    <span className="bg-gradient-brand flex h-9 w-9 items-center justify-center rounded-xl text-white">
                      {TOOL_ICONS[demo.tool] ?? <GitBranch size={18} />}
                    </span>
                    <span className="text-xs font-medium tabular-nums text-muted">{String(index + 1).padStart(2, "0")}</span>
                  </div>
                  <h3 className="text-lg font-semibold leading-snug text-foreground">{demo.title}</h3>
                  <p className="line-clamp-3 flex-1 text-sm text-muted">{demo.summary}</p>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted">
                      {demo.steps.length} {tr("кроки", "steps")}
                    </span>
                    <span className="flex items-center gap-1 font-medium text-accent">
                      {tr("Пройти", "Start")} <ArrowRight size={14} />
                    </span>
                  </div>
                </Panel>
              ))}
        </div>
      </section>

      <section className="mx-auto mb-20 w-full max-w-7xl px-4 py-12 sm:px-6 lg:px-10">
        <Panel className="relative overflow-hidden p-6 md:p-10">
          <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] lg:items-center">
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-widest text-accent">{tr("Наживо", "Live")}</p>
              <h2 className="mb-3 text-3xl font-bold tracking-tight text-foreground">{tr("Радар трендів", "Trend radar")}</h2>
              <p className="mb-6 text-lg text-muted">
                {tr(
                  "Система сама патрулює планету і відбирає найсильніші тренди після поправки FDR. Відкрий картку, щоб розслідувати.",
                  "The system patrols the planet and picks the strongest trends after the FDR correction. Open a card to investigate.",
                )}
              </p>
              <Button variant="secondary" onClick={() => navigate("/radar")}>
                <Activity size={16} /> {tr("До радару", "Open the radar")}
              </Button>
            </div>
            <div className="flex flex-col gap-3">
              {radar.isLoading || !radar.data
                ? Array.from({ length: 3 }, (_, index) => <Skeleton key={index} className="h-20" />)
                : radar.data.items.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => navigate(`/explore?${new URLSearchParams({ variable: item.variable_id, region: item.region_id, season: item.season }).toString()}`)}
                      className="ring-gradient flex items-center justify-between gap-4 rounded-xl border border-[var(--glass-border)] bg-surface/50 px-4 py-3 text-left transition-colors hover:bg-surface"
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <VerdictBadge code={item.verdict_level} direction={item.direction} />
                          <Chip>{names.season(item.season)}</Chip>
                        </div>
                        <p className="mt-1 truncate font-medium text-foreground">
                          {names.variable(item.variable_id)} · {names.region(item.region_id)}
                        </p>
                      </div>
                      <Slope value={item.slope_decade} unit={`${names.units(item.variable_id)} ${tr("за 10 р.", "/dec")}`.trim()} className="text-lg" />
                    </button>
                  ))}
            </div>
          </div>
        </Panel>
      </section>
    </div>
  );
}
