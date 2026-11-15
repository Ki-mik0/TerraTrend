import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@heroui/react";
import { Activity, ArrowRight, ChevronLeft, ChevronRight, Shapes } from "lucide-react";
import { api } from "../api/client";
import { call, failureText } from "../api/http";
import { Chip, EmptyState, Notice, Page, PageHeader, Panel, SectionTitle, Segmented, Skeleton, Slope, Term, VerdictBadge, VerdictScale } from "../components/ui";
import { useNames } from "../hooks/useNames";
import { useExpert, useTr } from "../i18n";
import { useStore } from "../store/useStore";

const FEEDS = ["strongest", "opposite", "accelerating", "breakpoints", "almost", "stable", "ai_flagged"] as const;
type Feed = (typeof FEEDS)[number];
const PAGE_SIZE = 12;

const FEED_LABELS: Record<Feed, [string, string]> = {
  strongest: ["Найсильніші", "Strongest"],
  opposite: ["Протилежні", "Opposite"],
  accelerating: ["Прискорення", "Accelerating"],
  breakpoints: ["Точки зламу", "Breakpoints"],
  almost: ["Майже доведені", "Almost proven"],
  stable: ["Стабільні", "Stable"],
  ai_flagged: ["Позначені ШІ", "AI flagged"],
};

const FEED_HELP: Record<Feed, [string, string]> = {
  strongest: ["Тренди з найпереконливішими доказами по всій планеті.", "Trends with the most convincing evidence across the planet."],
  opposite: ["Одна й та сама величина в одному місці зростає, а поруч — спадає.", "The same quantity rises in one place and falls next door."],
  accelerating: ["Зміни, які з роками стають швидшими.", "Changes that speed up over the years."],
  breakpoints: ["Місця, де ряд різко змінився за останні роки.", "Places where the series shifted sharply in recent years."],
  almost: ["Схоже на тренд, але для доказу бракує кількох років даних.", "Looks like a trend, but a few more years of data are needed for proof."],
  stable: ["Регіони, де помітних змін немає.", "Regions with no noticeable change."],
  ai_flagged: ["Статистика бачить тренд, а ШІ підозрює стрибок приладу — варто перевірити.", "Statistics see a trend while the AI suspects an instrument jump — worth checking."],
};

const NOVELTY: Record<string, [string, string]> = {
  new: ["нове", "new"],
  upgraded: ["посилилось", "upgraded"],
  downgraded: ["послабилось", "downgraded"],
};

export function Radar() {
  const navigate = useNavigate();
  const tr = useTr();
  const names = useNames();
  const expert = useExpert();
  const language = useStore((state) => state.language);
  const [feed, setFeed] = useState<Feed>("strongest");
  const [page, setPage] = useState(1);

  const cards = useQuery({
    queryKey: ["radar", feed, page, language],
    queryFn: () => call(api.GET("/api/v1/radar", { params: { query: { feed, lang: language, page, page_size: PAGE_SIZE } } })),
  });
  const typology = useQuery({
    queryKey: ["radar-typology"],
    queryFn: () => call(api.GET("/api/v1/radar/typology")),
  });
  const pages = Math.max(1, Math.ceil((cards.data?.total ?? 0) / PAGE_SIZE));

  // A radar card is a statistical candidate. It opens the investigation with the same variable,
  // region and season, so the reader gets a real case with the full evidence protocol.
  const investigate = (variable: string, region: string, season: string) =>
    navigate(`/explore?${new URLSearchParams({ variable, region, season }).toString()}`);

  return (
    <Page>
      <PageHeader
        icon={<Activity size={22} />}
        eyebrow={tr("Патруль планети", "Planet patrol")}
        title={tr("Радар трендів", "Trend radar")}
        subtitle={tr(
          "Система сама перевіряє тисячі пар «що × де» і показує, де на планеті щось помітно змінюється. Це кандидати для розслідування, а не готові відкриття — натисни картку, щоб перевірити.",
          "The system checks thousands of “what × where” pairs and shows where on the planet something is clearly changing. These are leads to investigate, not finished discoveries — open a card to check.",
        )}
        actions={<Chip tone="accent">{cards.data?.total ?? 0} {tr("кандидатів", "candidates")}</Chip>}
      />
      <div className="-mt-4 mb-6"><VerdictScale /></div>

      <Segmented
        className="mb-6"
        value={feed}
        onChange={(value) => {
          setFeed(value);
          setPage(1);
        }}
        options={FEEDS.map((item) => ({ value: item, label: tr(...FEED_LABELS[item]) }))}
      />
      <p className="-mt-3 mb-6 text-muted">{tr(...FEED_HELP[feed])}</p>
      <Notice text={cards.isError ? failureText(cards.error) : null} />

      <div className="mb-6 grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
        {cards.isLoading
          ? Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-48" />)
          : (cards.data?.items ?? []).map((item) => (
              <Panel
                key={item.id}
                as="button"
                type="button"
                interactive
                className="flex flex-col gap-4"
                onClick={() => investigate(item.variable_id, item.region_id, item.season)}
              >
                <div className="flex items-center justify-between gap-2">
                  <VerdictBadge code={item.verdict_level} direction={item.direction} />
                  <div className="flex items-center gap-1.5">
                    {item.novelty !== "unchanged" && NOVELTY[item.novelty] && <Chip tone="accent">{tr(...NOVELTY[item.novelty])}</Chip>}
                    {item.split_flag && <Chip tone="warning">{tr("розкол", "split")}</Chip>}
                    <Chip>{names.season(item.season)}</Chip>
                  </div>
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-foreground">{names.variable(item.variable_id)}</h3>
                  <p className="text-sm text-muted">{names.region(item.region_id)}</p>
                </div>
                <Slope value={item.slope_decade} unit={`${names.units(item.variable_id)} ${tr("за 10 років", "per decade")}`.trim()} className="text-3xl" />
                {expert && <dl className="grid grid-cols-3 gap-2 border-t border-[var(--glass-border)] pt-3 text-xs">
                  <div>
                    <dt className="text-muted">%/10 {tr("р.", "y")}</dt>
                    <dd className="font-semibold tabular-nums text-foreground">{item.pct_decade.toFixed(1)}%</dd>
                  </div>
                  <div>
                    <dt className="text-muted"><Term id="q_fdr" bare>q FDR</Term></dt>
                    <dd className="font-semibold tabular-nums text-foreground">{item.q_fdr.toFixed(3)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted"><Term id="snr" bare>SNR</Term></dt>
                    <dd className="font-semibold tabular-nums text-foreground">{item.snr.toFixed(2)}</dd>
                  </div>
                </dl>}
                {item.years_to_detect !== null && item.years_to_detect !== undefined && (
                  <p className="text-xs text-muted">
                    <Term id="years_to_proof" bare>{tr("Років до доказу", "Years to proof")}</Term>: <span className="font-semibold text-foreground">{item.years_to_detect}</span>
                  </p>
                )}
                <span className="mt-auto flex items-center gap-1 text-sm font-medium text-accent">
                  {tr("Розслідувати", "Investigate")} <ArrowRight size={14} />
                </span>
              </Panel>
            ))}
      </div>
      {cards.data?.items.length === 0 && (
        <EmptyState icon={<Activity size={28} />} title={tr("У цій стрічці поки порожньо", "This feed is empty for now")} text={tr("Спробуй іншу стрічку.", "Try another feed.")} />
      )}
      {pages > 1 && (
        <div className="mb-10 flex items-center justify-center gap-3">
          <Button variant="ghost" size="sm" isIconOnly onClick={() => setPage((value) => value - 1)} isDisabled={page <= 1} aria-label={tr("Назад", "Previous")}>
            <ChevronLeft size={16} />
          </Button>
          <span className="text-sm tabular-nums text-muted">
            {page} / {pages}
          </span>
          <Button variant="ghost" size="sm" isIconOnly onClick={() => setPage((value) => value + 1)} isDisabled={page >= pages} aria-label={tr("Далі", "Next")}>
            <ChevronRight size={16} />
          </Button>
        </div>
      )}

      <section className="mt-12">
        <SectionTitle icon={<Shapes size={18} />}>{tr("Типологія змін", "Change typology")}</SectionTitle>
        <p className="-mt-2 mb-5 max-w-2xl text-sm text-muted">
          {tr("Регіони, де кілька змінних змінюються разом однаково — наприклад, «тепліше, сухіше, менше зелені».", "Regions where several variables change together the same way — for example “warmer, drier, less green”.")}
        </p>
        <Notice text={typology.isError ? failureText(typology.error) : null} />
        <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
          {(typology.data?.clusters ?? []).map((cluster) => (
            <Panel key={cluster.id} className="flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold text-foreground">
                  {Object.entries(cluster.signs).map(([variable, sign]) => `${names.variable(variable)} ${sign > 0 ? "↑" : sign < 0 ? "↓" : "="}`).join(", ")}
                </h3>
                <Chip>{names.season(cluster.season)}</Chip>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(cluster.signs).map(([variable, sign]) => (
                  <Chip key={variable} tone={sign > 0 ? "warm" : sign < 0 ? "cool" : "neutral"}>
                    {sign > 0 ? "↑" : sign < 0 ? "↓" : "="} {names.variable(variable)}
                  </Chip>
                ))}
              </div>
              <p className="text-xs text-muted">{(cluster.area_km2 / 1e6).toFixed(1)} {tr("млн км²", "M km²")}</p>
              <div className="flex flex-wrap gap-2 border-t border-[var(--glass-border)] pt-3">
                {cluster.region_ids.map((region) => (
                  <button
                    key={region}
                    type="button"
                    className="text-sm font-medium text-accent hover:underline"
                    onClick={() => investigate(Object.keys(cluster.signs)[0] ?? "", region, cluster.season)}
                  >
                    {names.region(region)} →
                  </button>
                ))}
              </div>
            </Panel>
          ))}
        </div>
      </section>
    </Page>
  );
}
