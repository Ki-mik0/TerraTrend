import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@heroui/react";
import { ArrowLeft, BookOpenText, Building2, ExternalLink, SearchX, Layers, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import { api } from "../api/client";
import { ApiFailure, call, failureText } from "../api/http";
import { BarChart } from "../components/Charts";
import { ExportPanel } from "../components/ExportPanel";
import { CheckList, Chip, DataSourceChip, EmptyState, Notice, Page, Panel, SectionTitle, Skeleton, Slope, Stat, Term, VerdictBadge, VerdictScale } from "../components/ui";
import { caseSentence, evidenceChecks } from "../explain";
import { useNames } from "../hooks/useNames";
import { useExpert, useTr } from "../i18n";
import { VERDICT_MEANING } from "../terms";
import { useStore } from "../store/useStore";

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function CasePage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const token = useStore((state) => state.token);
  const language = useStore((state) => state.language);
  const tr = useTr();
  const expert = useExpert();
  const names = useNames();
  const client = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const enabled = Boolean(token && id);
  const record = useQuery({
    queryKey: ["case", id],
    enabled,
    queryFn: () => call(api.GET("/api/v1/cases/{case_id}", { params: { path: { case_id: id } } })),
  });
  const evidence = useQuery({
    queryKey: ["evidence", id],
    enabled,
    queryFn: () => call(api.GET("/api/v1/cases/{case_id}/evidence", { params: { path: { case_id: id } } })),
  });
  const profile = useQuery({
    queryKey: ["profile", id],
    enabled,
    queryFn: () => call(api.GET("/api/v1/cases/{case_id}/profile", { params: { path: { case_id: id } } })),
  });
  const urban = useQuery({
    queryKey: ["urban", id],
    enabled,
    queryFn: () => call(api.GET("/api/v1/cases/{case_id}/urban", { params: { path: { case_id: id } } })),
  });
  const story = useQuery({
    queryKey: ["story", id, language],
    enabled,
    queryFn: () => call(api.GET("/api/v1/cases/{case_id}/story", { params: { path: { case_id: id }, query: { language } } })),
  });

  const rewrite = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/v1/story", {
          body: { variable_id: record.data?.variable_id ?? "", region_id: record.data?.region_id ?? "", language },
        }),
      ),
    onError: (reason) => setError(failureText(reason)),
  });
  const remove = useMutation({
    mutationFn: () => call(api.DELETE("/api/v1/cases/{case_id}", { params: { path: { case_id: id } } })),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["cases"] });
      navigate("/journal");
    },
    onError: (reason) => setError(failureText(reason)),
  });

  const shownStory = rewrite.data ?? story.data;
  const data = record.data;
  const verdict = data?.verdict ?? null;
  const direction = data?.direction ?? shownStory?.direction ?? verdict?.direction ?? null;
  const from = data?.period?.start?.slice(0, 4) ?? "";
  const to = data?.period?.end?.slice(0, 4) ?? "";
  const proof = evidence.data;
  const slope = data?.slope_decade ?? shownStory?.slope_decade ?? null;
  const units = data ? names.units(data.variable_id) : "";
  const meaning = VERDICT_MEANING.find(([code]) => code === verdict?.code);
  const sentence = data
    ? caseSentence(
        {
          variable: names.variable(data.variable_id),
          region: names.region(data.region_id),
          season: names.season(null),
          units,
          slope,
          direction,
          verdict: verdict?.code,
          from,
          to,
        },
        tr,
      )
    : null;
  const checks = proof ? evidenceChecks(proof, verdict?.code, tr) : [];
  const hasProfile = (profile.data?.levels ?? []).length > 0;
  const hasUrban = Boolean(urban.data);

  // A link to a case that is gone (deleted, another account's, or from before a server reset).
  if (record.error instanceof ApiFailure && record.error.status === 404) {
    return (
      <Page>
        <EmptyState
          icon={<SearchX size={28} />}
          title={tr("Цієї справи немає", "This case is not here")}
          text={tr(
            "Її могли видалити, вона належить іншому акаунту, або посилання старе. Відкрий нову справу — це займе кілька секунд.",
            "It may have been deleted, belong to another account, or the link is old. Open a new case — it takes a few seconds.",
          )}
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <Button variant="primary" onClick={() => navigate("/explore")}>
                <Layers size={16} /> {tr("Нове розслідування", "New investigation")}
              </Button>
              <Button variant="secondary" onClick={() => navigate("/journal")}>
                <BookOpenText size={16} /> {tr("Мої справи", "My cases")}
              </Button>
            </div>
          }
        />
      </Page>
    );
  }

  return (
    <Page>
      <Link to="/journal" className="mb-6 inline-flex items-center gap-1.5 text-sm text-muted hover:text-foreground">
        <ArrowLeft size={16} /> {tr("До журналу", "Back to journal")}
      </Link>
      <Notice text={error || (record.isError ? failureText(record.error) : null)} />

      <Panel className="relative mb-6 overflow-hidden">
        <div className="bg-gradient-brand absolute inset-x-0 top-0 h-1" />
        <div className="flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
          <div className="min-w-0">
            <p className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-muted">
              <ShieldCheck size={14} className="text-accent" /> {tr("Розслідування", "Investigation")}
            </p>
            {data ? (
              <h1 className="text-3xl font-bold tracking-tight text-foreground md:text-4xl">
                {names.variable(data.variable_id)} <span className="text-muted">·</span> {names.region(data.region_id)}
              </h1>
            ) : (
              <Skeleton className="h-10 w-80" />
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
              {from && <Chip>{from}–{to}</Chip>}
              {data && data.status !== "completed" && <Chip tone="warning">{tr("рахується…", "computing…")}</Chip>}
              <DataSourceChip version={data?.datasets_version} />
              {proof?.gam_accelerating && <Chip tone="warm">{tr("прискорюється", "accelerating")}</Chip>}
            </div>
          </div>
          <div className="flex flex-col items-start gap-3 md:items-end">
            <span className="text-xs font-semibold uppercase tracking-widest text-muted"><Term id="verdict">{tr("Вирок", "Verdict")}</Term></span>
            <VerdictBadge code={verdict?.code} direction={direction} size="lg" />
            {typeof slope === "number" && <Slope value={slope} unit={`${units} ${tr("за 10 років", "per decade")}`.trim()} className="text-2xl" />}
          </div>
        </div>
      </Panel>

      {sentence && (
        <Panel className="mb-6">
          <SectionTitle>{tr("Що це означає", "What this means")}</SectionTitle>
          <p className="text-lg leading-relaxed text-foreground">{sentence}</p>
          {meaning && <p className="mt-2 text-muted">{tr(meaning[1], meaning[2])}</p>}
          <div className="mt-4"><VerdictScale current={verdict?.code} /></div>
        </Panel>
      )}

      {proof ? (
        expert ? (
          <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
            <Stat label={<Term id="witnesses">{tr("Свідки", "Witnesses")}</Term>} value={`${proof.witnesses_confirmed}/${proof.witnesses_total}`} hint={tr("незалежні датасети", "independent datasets")} tone="accent" />
            <Stat label={<Term id="robustness">{tr("Стійкість", "Robustness")}</Term>} value={pct(proof.triangle_same_sign_share)} hint={tr("вікон того ж знаку", "windows, same sign")} />
            <Stat label={<Term id="alibi">{tr("Алібі: сирий", "Alibi: raw")}</Term>} value={proof.alibi_b_raw.toFixed(3)} />
            <Stat label={<Term id="alibi">{tr("Алібі: залишок", "Alibi: left")}</Term>} value={proof.alibi_b_adjusted.toFixed(3)} hint={tr("після ENSO/NAO/вулканів", "after ENSO/NAO/volcanoes")} />
            <Stat label={<Term id="quality">{tr("Пропуски", "Gaps")}</Term>} value={pct(proof.quality.gap_fraction)} />
            <Stat label={<Term id="n_eff">n_eff</Term>} value={proof.quality.n_eff.toFixed(1)} hint={tr("незалежних точок", "independent points")} />
          </div>
        ) : (
          <Panel className="mb-6">
            <SectionTitle>{tr("Докази", "Evidence")}</SectionTitle>
            <p className="-mt-2 mb-4 text-sm text-muted">
              {tr("Система не вірить одному тесту — ось що показала кожна перевірка. Перемкни «Експерт» угорі, щоб побачити всі числа.", "The system does not trust a single test — here is what each check showed. Switch to Expert at the top to see every number.")}
            </p>
            <CheckList checks={checks} />
          </Panel>
        )
      ) : (
        evidence.isLoading && <Skeleton className="mb-6 h-24" />
      )}

      <div className={`mb-6 grid grid-cols-1 gap-6 ${expert || hasProfile || hasUrban ? "lg:grid-cols-3" : ""}`}>
        <Panel className={expert || hasProfile || hasUrban ? "lg:col-span-2" : ""}>
          <SectionTitle>{tr("Який місяць змінюється найбільше", "Which month changes most")}</SectionTitle>
          <p className="-mt-2 mb-2 text-sm text-muted">
            {tr("Кожен стовпчик — на скільки змінюється цей місяць за 10 років. Вище нуля (тепліше колір) — зростає, нижче — спадає.", "Each bar is how much that month changes per decade. Above zero (warm colour) means rising, below means falling.")}
          </p>
          {proof ? (
            <BarChart labels={proof.months.map((item) => new Date(2000, item.month - 1, 1).toLocaleString(language === "uk" ? "uk-UA" : "en-US", { month: "short" }))} values={proof.months.map((item) => item.slope)} />
          ) : evidence.isError ? (
            <Notice text={failureText(evidence.error)} />
          ) : (
            <EmptyState title={tr("Докази з’являться, коли справу завершено", "Evidence appears when the case is complete")} />
          )}
        </Panel>
        <div className="flex flex-col gap-6">
          {(expert || hasProfile) && (
          <Panel>
            <SectionTitle icon={<Layers size={18} />}>{tr("Вертикальний профіль", "Vertical profile")}</SectionTitle>
            {(profile.data?.levels ?? []).length > 0 ? (
              <ul className="flex flex-col divide-y divide-[var(--glass-border)] text-sm">
                {profile.data?.levels.map((level) => (
                  <li key={level.pressure_hpa} className="flex items-center justify-between py-2">
                    <span className="tabular-nums text-muted">{level.pressure_hpa} hPa</span>
                    <span className="flex items-center gap-2">
                      <Chip>{level.pattern}</Chip>
                      <Slope value={level.slope} />
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted">{profile.isError ? failureText(profile.error) : tr("Для цієї справи профілю немає.", "No vertical profile for this case.")}</p>
            )}
          </Panel>
          )}
          {(expert || hasUrban) && (
          <Panel>
            <SectionTitle icon={<Building2 size={18} />}>{tr("Місто проти околиць", "City vs. surroundings")}</SectionTitle>
            {urban.data ? (
              <div className="grid grid-cols-3 gap-2 text-center text-sm">
                <div>
                  <p className="text-xs text-muted">{tr("Місто", "City")}</p>
                  <Slope value={urban.data.city_slope} />
                </div>
                <div>
                  <p className="text-xs text-muted">{tr("Околиці", "Ring")}</p>
                  <Slope value={urban.data.ring_slope} />
                </div>
                <div>
                  <p className="text-xs text-muted">{tr("Різниця", "Difference")}</p>
                  <Slope value={urban.data.difference} />
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted">{tr("Для цієї справи немає даних міста.", "No city data for this case.")}</p>
            )}
          </Panel>
          )}
        </div>
      </div>

      <Panel className="mb-6">
        <SectionTitle
          icon={<BookOpenText size={18} />}
          action={
            <Button size="sm" variant="ghost" onClick={() => rewrite.mutate()} isDisabled={!data || rewrite.isPending}>
              <RefreshCw size={14} /> {tr("Переписати", "Rewrite")}
            </Button>
          }
        >
          {shownStory?.title || tr("Історія справи", "Case story")}
        </SectionTitle>
        {story.isError && !rewrite.data && <Notice text={failureText(story.error)} tone="info" />}
        {shownStory ? (
          <div className="flex flex-col gap-4">
            <p className="max-w-3xl whitespace-pre-wrap text-base leading-relaxed text-foreground">{shownStory.text}</p>
            <div className="flex flex-wrap gap-1.5">
              {shownStory.pattern && <Chip tone="accent">{shownStory.pattern}</Chip>}
              {expert && <Chip>{shownStory.source}</Chip>}
              {(shownStory.caveats ?? []).map((item) => <Chip key={item} tone="warning">{item}</Chip>)}
            </div>
            {(shownStory.related ?? []).length > 0 && (
              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-muted">{tr("Співучасники", "Accomplices")}</h3>
                <div className="flex flex-wrap gap-2">
                  {shownStory.related.map((item) => (
                    <Chip key={item.variable_id}>
                      {names.variable(item.variable_id) !== item.variable_id ? names.variable(item.variable_id) : item.name || item.variable_id} ·{" "}
                      {item.role === "driver" ? tr("причина", "cause") : item.role === "response" ? tr("наслідок", "effect") : item.role === "process" ? tr("пов’язаний процес", "linked process") : item.role}
                      {typeof item.lag_months === "number" && ` · ${item.lag_months} ${tr("міс.", "mo")}`}
                    </Chip>
                  ))}
                </div>
              </div>
            )}
            {(shownStory.papers ?? []).length > 0 && (
              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-muted">{tr("Що кажуть науковці", "What scientists say")}</h3>
                <ul className="flex flex-col gap-1.5 text-sm">
                  {shownStory.papers.map((paper) => (
                    <li key={paper.url || paper.title}>
                      <a href={paper.url || (paper.doi ? `https://doi.org/${paper.doi}` : "#")} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
                        {paper.title} <ExternalLink size={12} />
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : story.isLoading ? (
          <Skeleton className="h-24" />
        ) : (
          <p className="text-sm text-muted">{tr("Історії ще немає.", "No story yet.")}</p>
        )}
      </Panel>

      <ExportPanel
        caseId={id}
        ready={data?.status === "completed" && Boolean(data?.verdict)}
        action={
          <Button
            size="sm"
            variant="danger-soft"
            onClick={() => {
              if (window.confirm(tr("Видалити справу назавжди? Це не можна скасувати.", "Delete this case for good? This cannot be undone."))) remove.mutate();
            }}
            isDisabled={remove.isPending || !data}
          >
            <Trash2 size={14} /> {tr("Видалити справу", "Delete case")}
          </Button>
        }
      />
    </Page>
  );
}
