import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@heroui/react";
import { ArrowRight, BookA, Check, CircleHelp, Dices, FlaskConical, Footprints, Play, Sparkles } from "lucide-react";
import { api, type Schema } from "../api/client";
import { call, failureText } from "../api/http";
import { LineChart } from "../components/Charts";
import { Chip, EmptyState, Notice, Page, PageHeader, Panel, Progress, Range, SectionTitle, Select, Skeleton, Stat, Term } from "../components/ui";
import { useTr } from "../i18n";
import { useStore } from "../store/useStore";

function QuizCard({ quiz, index }: { quiz: Schema<"QuizResponse">; index: number }) {
  const tr = useTr();
  const client = useQueryClient();
  const [choice, setChoice] = useState<number | null>(null);
  const answer = useMutation({
    mutationFn: (picked: number) =>
      call(api.POST("/api/v1/education/quizzes/{quiz_id}", { params: { path: { quiz_id: quiz.id } }, body: { choice: picked } })),
    onSuccess: async (result) => {
      if (result.badge) await client.invalidateQueries({ queryKey: ["badges"] });
    },
  });
  const result = answer.data;
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-[var(--glass-border)] p-4">
      <p className="text-sm font-medium text-foreground">
        <span className="mr-2 text-muted tabular-nums">{index + 1}.</span>
        {quiz.question}
      </p>
      <div className="grid gap-2">
        {quiz.options.map((option, optionIndex) => {
          const picked = choice === optionIndex;
          const state = result && picked ? (result.correct ? "right" : "wrong") : picked ? "picked" : "idle";
          return (
            <button
              key={option}
              type="button"
              disabled={answer.isPending || result?.correct}
              onClick={() => {
                setChoice(optionIndex);
                answer.mutate(optionIndex);
              }}
              className={`rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
                state === "right"
                  ? "border-success/50 bg-success-soft text-success-soft-foreground"
                  : state === "wrong"
                    ? "border-danger/40 bg-danger-soft text-danger-soft-foreground"
                    : state === "picked"
                      ? "border-accent/50 bg-accent-soft text-foreground"
                      : "border-[var(--glass-border)] text-foreground hover:bg-default"
              }`}
            >
              {option}
            </button>
          );
        })}
      </div>
      {result && (
        <p className={`text-sm ${result.correct ? "text-success" : "text-muted"}`}>
          {result.correct ? tr("Правильно! ", "Correct! ") : tr("Не зовсім. ", "Not quite. ")}
          {result.explanation}
          {result.badge && <span className="ml-1 font-semibold text-accent">{tr("Новий бейдж!", "New badge!")}</span>}
        </p>
      )}
      {answer.isError && <Notice text={failureText(answer.error)} />}
    </div>
  );
}

export function Lab() {
  const tr = useTr();
  const token = useStore((state) => state.token);
  const language = useStore((state) => state.language);
  const client = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [noise, setNoise] = useState(1);
  const [years, setYears] = useState(20);
  const [autocorrelation, setAutocorrelation] = useState(0.3);
  const [trend, setTrend] = useState(0.2);
  const [seed, setSeed] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [openTerm, setOpenTerm] = useState<string | null>(null);
  const enabled = Boolean(token);

  const glossary = useQuery({
    queryKey: ["glossary", language, token],
    enabled,
    queryFn: () => call(api.GET("/api/v1/education/glossary", { params: { query: { lang: language } } })),
  });
  const quizzes = useQuery({
    queryKey: ["quizzes", language, token],
    enabled,
    queryFn: () => call(api.GET("/api/v1/education/quizzes", { params: { query: { lang: language } } })),
  });
  const demos = useQuery({
    queryKey: ["demos", language, token],
    enabled,
    queryFn: () => call(api.GET("/api/v1/education/demos", { params: { query: { lang: language } } })),
  });
  const selectedDemo = params.get("demo") || demos.data?.[0]?.id || "";
  const demo = useQuery({
    queryKey: ["demo", selectedDemo, language, token],
    enabled: Boolean(enabled && selectedDemo),
    queryFn: () => call(api.GET("/api/v1/education/demos/{demo_id}", { params: { path: { demo_id: selectedDemo }, query: { lang: language } } })),
  });
  const progress = useQuery({
    queryKey: ["demo-progress", selectedDemo, token],
    enabled: Boolean(enabled && selectedDemo),
    queryFn: () => call(api.GET("/api/v1/education/demos/{demo_id}/progress", { params: { path: { demo_id: selectedDemo } } })),
  });
  const lab = useMutation({
    mutationFn: () => call(api.POST("/api/v1/education/lab", { body: { noise, years, autocorrelation, trend_per_decade: trend, seed } })),
    onSuccess: () => setError(null),
    onError: (reason) => setError(failureText(reason)),
  });
  const step = useMutation({
    mutationFn: (number: number) =>
      call(api.POST("/api/v1/education/demos/{demo_id}/steps/{step}", { params: { path: { demo_id: selectedDemo, step: number } } })),
    onSuccess: async (result) => {
      setError(null);
      client.setQueryData(["demo-progress", selectedDemo, token], result);
      if (result.badge) await client.invalidateQueries({ queryKey: ["badges"] });
    },
    onError: (reason) => setError(failureText(reason)),
  });
  const done = new Set(progress.data?.steps_done ?? []);
  const pages = (glossary.data ?? []).filter((item) => item.kind === "page");
  const terms = (glossary.data ?? []).filter((item) => item.kind !== "page");
  const share = progress.data && progress.data.total_steps > 0 ? (progress.data.steps_done.length / progress.data.total_steps) * 100 : 0;

  return (
    <Page>
      <PageHeader
        icon={<FlaskConical size={22} />}
        eyebrow={tr("Навчання", "Learn")}
        title={tr("Лабораторія детектива", "Detective lab")}
        subtitle={tr("Додай шум, скороти ряд, додай автокореляцію — і подивись, як змінюється значущість.", "Add noise, shorten the series, add autocorrelation — and watch significance change.")}
      />
      <Notice text={error} />

      <div className="mb-10 grid grid-cols-1 gap-6 lg:grid-cols-[340px_minmax(0,1fr)]">
        <Panel className="flex flex-col gap-5">
          <SectionTitle icon={<Dices size={18} />}>{tr("Параметри ряду", "Series settings")}</SectionTitle>
          <div className="-mt-2 rounded-xl bg-accent-soft p-3 text-sm text-foreground">
            <p className="mb-1 font-medium">{tr("Що спробувати", "Things to try")}</p>
            <ul className="list-disc space-y-0.5 pl-5 text-muted">
              <li>{tr("Збільш шум — тренд зникне з радара статистики.", "Raise the noise — the trend disappears for the statistics.")}</li>
              <li>{tr("Скороти ряд до 10 років — доказів забракне.", "Cut the series to 10 years — the evidence runs out.")}</li>
              <li>{tr("Додай автокореляцію — незалежних точок стане менше.", "Add autocorrelation — fewer independent points remain.")}</li>
            </ul>
          </div>
          <Range label={tr("Шум", "Noise")} value={noise} min={0} max={10} step={0.1} onChange={(event) => setNoise(Number(event.target.value))} />
          <Range label={tr("Років", "Years")} value={years} min={5} max={100} onChange={(event) => setYears(Number(event.target.value))} />
          <Range label={tr("Автокореляція", "Autocorrelation")} value={autocorrelation} min={0} max={0.9} step={0.05} onChange={(event) => setAutocorrelation(Number(event.target.value))} />
          <Range label={tr("Тренд за 10 років", "Trend per decade")} value={trend} min={-1} max={1} step={0.05} onChange={(event) => setTrend(Number(event.target.value))} />
          <div className="flex gap-2">
            <Button variant="primary" className="flex-1" onClick={() => lab.mutate()} isDisabled={!enabled || lab.isPending}>
              <Play size={16} /> {tr("Запустити", "Run")}
            </Button>
            <Button variant="secondary" onClick={() => { setSeed((value) => value + 1); lab.reset(); }}>
              {tr("Новий шум", "New noise")}
            </Button>
          </div>
        </Panel>
        <Panel className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label={<Term id="slope">{tr("Нахил", "Slope")}</Term>} value={lab.data?.slope_decade?.toFixed(3) ?? "—"} hint={tr("за 10 років", "per decade")} />
            <Stat label={<Term id="p_value">p-value</Term>} value={lab.data?.p_value?.toFixed(3) ?? "—"} />
            <Stat label={<Term id="n_eff">n_eff</Term>} value={lab.data?.n_eff?.toFixed(1) ?? "—"} hint={tr("незалежних точок", "independent points")} />
            <Stat
              label={<Term id="significant">{tr("Висновок", "Result")}</Term>}
              value={lab.data ? (lab.data.significant ? tr("Значущий", "Significant") : tr("Ні", "No")) : "—"}
              tone={lab.data ? (lab.data.significant ? "accent" : undefined) : undefined}
            />
          </div>
          {lab.data && (
            <p className="text-foreground">
              {lab.data.significant
                ? tr("Тренд значущий: з таким шумом і довжиною ряду він навряд чи випадковий.", "The trend is significant: with this noise and length it is unlikely to be chance.")
                : tr("Тренд не доведено: шум або короткий ряд ховають його. Спробуй додати років або зменшити шум.", "The trend is not proven: noise or a short series hides it. Try more years or less noise.")}
            </p>
          )}
          {lab.data?.series?.length ? (
            <LineChart name="lab" values={lab.data.series} />
          ) : (
            <EmptyState icon={<Sparkles size={28} />} title={tr("Тут з’явиться синтетичний ряд", "The synthetic series appears here")} text={tr("Налаштуй параметри і натисни «Запустити».", "Set the parameters and press Run.")} />
          )}
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Panel className="flex max-h-[640px] flex-col">
          <SectionTitle icon={<BookA size={18} />}>{tr("Словник", "Glossary")}</SectionTitle>
          <Notice text={glossary.isError ? failureText(glossary.error) : null} />
          <div className="-mx-2 flex-1 overflow-y-auto px-2">
            {pages.map((item) => (
              <div key={item.id} className="mb-3 rounded-xl border border-accent/30 bg-accent-soft p-4">
                <p className="mb-1 flex items-center gap-1.5 font-semibold text-foreground">
                  <Sparkles size={14} className="text-accent" /> {item.term}
                </p>
                <p className="text-sm leading-relaxed text-foreground/90">{item.text}</p>
              </div>
            ))}
            {glossary.isLoading && <Skeleton className="h-40" />}
            <ul className="flex flex-col divide-y divide-[var(--glass-border)]">
              {terms.map((item) => {
                const open = openTerm === item.id;
                return (
                  <li key={item.id}>
                    <button type="button" className="flex w-full items-center justify-between py-3 text-left text-sm font-medium text-foreground" onClick={() => setOpenTerm(open ? null : item.id)} aria-expanded={open}>
                      {item.term}
                      <span className={`text-muted transition-transform ${open ? "rotate-90" : ""}`}>›</span>
                    </button>
                    {open && (
                      <div className="pb-3 text-sm text-muted">
                        <p>{item.text}</p>
                        {item.example && <p className="mt-1 italic">{item.example}</p>}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        </Panel>

        <Panel className="flex max-h-[640px] flex-col">
          <SectionTitle icon={<CircleHelp size={18} />} action={<Chip>{quizzes.data?.length ?? 0}</Chip>}>
            {tr("Вікторини", "Quizzes")}
          </SectionTitle>
          <Notice text={quizzes.isError ? failureText(quizzes.error) : null} />
          <div className="-mx-2 flex flex-1 flex-col gap-3 overflow-y-auto px-2">
            {quizzes.isLoading && <Skeleton className="h-40" />}
            {(quizzes.data ?? []).map((quiz, index) => <QuizCard key={quiz.id} quiz={quiz} index={index} />)}
          </div>
        </Panel>

        <Panel className="flex max-h-[640px] flex-col">
          <SectionTitle icon={<Footprints size={18} />}>{tr("Демо крок за кроком", "Demo step by step")}</SectionTitle>
          <Select
            className="mb-3"
            value={selectedDemo}
            onChange={(event) => setParams((current) => { const next = new URLSearchParams(current); next.set("demo", event.target.value); return next; }, { replace: true })}
            aria-label={tr("Демо-справа", "Demo case")}
          >
            {(demos.data ?? []).map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
          </Select>
          {demo.data && <p className="mb-3 text-sm text-muted">{demo.data.summary}</p>}
          {progress.data && (
            <div className="mb-4 flex items-center gap-3">
              <Progress value={share} />
              <span className="shrink-0 text-xs tabular-nums text-muted">
                {progress.data.steps_done.length}/{progress.data.total_steps}
              </span>
            </div>
          )}
          <ol className="-mx-2 flex flex-1 flex-col gap-2 overflow-y-auto px-2">
            {(demo.data?.steps ?? []).map((item) => {
              const finished = done.has(item.number);
              return (
                <li key={item.number} className={`flex gap-3 rounded-xl border p-3 ${finished ? "border-success/40 bg-success-soft" : "border-[var(--glass-border)]"}`}>
                  <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${finished ? "bg-success text-white" : "bg-default text-foreground"}`}>
                    {finished ? <Check size={14} /> : item.number}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-foreground">{item.title}</p>
                    <p className="mb-2 text-xs text-muted">{item.text}</p>
                    {!finished && (
                      <Button size="sm" variant="secondary" onClick={() => step.mutate(item.number)} isDisabled={!enabled || step.isPending}>
                        {tr("Зроблено", "Done")}
                      </Button>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
          {progress.data?.finished && <Notice tone="success" text={tr("Демо пройдено — бейдж у журналі.", "Demo completed — the badge is in your journal.")} />}
          {demo.data && (
            <Link
              className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-accent hover:underline"
              to={`/explore?${new URLSearchParams({ variable: demo.data.variable_id, region: demo.data.region_id, from: demo.data.period_start.slice(0, 4), to: demo.data.period_end.slice(0, 4) }).toString()}`}
            >
              {tr("Відкрити справу демо", "Open the demo case")} <ArrowRight size={14} />
            </Link>
          )}
        </Panel>
      </div>
    </Page>
  );
}
