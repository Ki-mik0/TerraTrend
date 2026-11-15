import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@heroui/react";
import { Activity, Database, FlaskConical, KeyRound, ListChecks, RefreshCw, Shield, Trash2, Zap } from "lucide-react";
import { api } from "../api/client";
import { call, failureText, loose } from "../api/http";
import { monthlySeries } from "../api/sample";
import { Chip, EmptyState, Field, Input, Notice, Page, PageHeader, Panel, Progress, SectionTitle, Select, TextArea } from "../components/ui";
import type { Tone } from "../components/ui";
import { useTr } from "../i18n";
import { useStore } from "../store/useStore";

const FAMILIES = ["all", "catalog", "case", "story", "edu", "radar", "assistant", "tile"] as const;

function statusTone(status: string | undefined): Tone {
  if (status === "ok") return "success";
  if (status === "degraded") return "warning";
  if (status === "down") return "danger";
  return "neutral";
}

function Dot({ status }: { status: string | undefined }) {
  const colour = status === "ok" ? "bg-success" : status === "degraded" ? "bg-warning" : status === "down" ? "bg-danger" : "bg-default";
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${colour}`} />;
}

export function Admin() {
  const role = useStore((state) => state.role);
  const client = useQueryClient();
  const tr = useTr();
  const allowed = role === "admin";
  const [ownerId, setOwnerId] = useState("");
  const [keyId, setKeyId] = useState("");
  const [caseId, setCaseId] = useState("");
  const [note, setNote] = useState("");
  const [family, setFamily] = useState<(typeof FAMILIES)[number]>("radar");
  const [tool, setTool] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [secret, setSecret] = useState<string | null>(null);

  const jobs = useQuery({ queryKey: ["admin-jobs"], enabled: allowed, queryFn: () => call(api.GET("/api/v1/admin/jobs")) });
  const cache = useQuery({ queryKey: ["admin-cache"], enabled: allowed, queryFn: () => call(api.GET("/api/v1/admin/cache")) });
  const health = useQuery({
    queryKey: ["health"],
    enabled: allowed,
    queryFn: async () => {
      const [full, live, ready] = await Promise.all([call(api.GET("/health")), call(api.GET("/health/live")), call(api.GET("/health/ready"))]);
      return { full, live, ready };
    },
  });

  const issue = useMutation({
    mutationFn: () => call(api.POST("/api/v1/admin/api-keys", { body: { owner_id: ownerId } })),
    onSuccess: (data) => {
      setSecret(data.secret);
      setKeyId(data.id);
      setError(null);
    },
    onError: (reason) => setError(failureText(reason)),
  });
  const revoke = useMutation({
    mutationFn: () => call(api.DELETE("/api/v1/admin/api-keys/{key_id}", { params: { path: { key_id: keyId } } })),
    onSuccess: () => setSecret(null),
    onError: (reason) => setError(failureText(reason)),
  });
  const review = useMutation({
    mutationFn: () => call(api.POST("/api/v1/admin/ai-reviews", { body: { case_id: caseId, note } })),
    onError: (reason) => setError(failureText(reason)),
  });
  const reload = useMutation({ mutationFn: () => call(api.POST("/api/v1/admin/reload-catalog")), onError: (reason) => setError(failureText(reason)) });
  const warm = useMutation({
    mutationFn: () => call(api.POST("/api/v1/admin/warm-cache")),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["admin-cache"] });
    },
    onError: (reason) => setError(failureText(reason)),
  });
  const clear = useMutation({
    mutationFn: () => call(api.DELETE("/api/v1/admin/cache", { params: { query: { family } } })),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["admin-cache"] });
    },
    onError: (reason) => setError(failureText(reason)),
  });
  // Analytics checks: a synthetic series or grid goes straight to the analytics paths.
  const analyze = useMutation({
    mutationFn: () => call(api.POST("/api/v1/analyze", { body: { series: loose(monthlySeries("gldas_sm", "ukraine_south")) } })),
    onSuccess: (data) => setTool(JSON.stringify(data, null, 2)),
    onError: (reason) => setError(failureText(reason)),
  });
  const scan = useMutation({
    mutationFn: () => call(api.POST("/api/v1/radar/scan", { body: { series: [loose({ series: monthlySeries("gldas_sm", "ukraine_south") })] } })),
    onSuccess: (data) => setTool(JSON.stringify(data, null, 2)),
    onError: (reason) => setError(failureText(reason)),
  });
  const grid = useMutation({
    mutationFn: () => {
      // Twelve years of monthly values on a 2×2 grid; the analytics needs monthly data for a slope.
      const dates = Array.from({ length: 144 }, (_, month) => `${2007 + Math.floor(month / 12)}-${String((month % 12) + 1).padStart(2, "0")}-01`);
      const values = dates.map((_, month) => [[0.2 + 0.001 * month, 0.3], [0.25, 0.28 - 0.002 * month]]);
      return call(api.POST("/api/v1/tiles/products", { body: loose({ variable_id: "gldas_sm", period: "2007-2018", season: "annual", dates, lat: [48, 50], lon: [30, 32], values }) }));
    },
    onSuccess: (data) => setTool(JSON.stringify(data, null, 2)),
    onError: (reason) => setError(failureText(reason)),
  });

  if (!allowed) {
    return (
      <Page>
        <PageHeader icon={<Shield size={22} />} title={tr("Адмін", "Admin")} />
        <EmptyState icon={<Shield size={28} />} title={tr("Лише для адміністратора", "Admins only")} text={tr("Увійди обліковим записом з роллю admin.", "Sign in with an admin account.")} />
      </Page>
    );
  }

  const checks = Object.entries(health.data?.full.checks ?? {});

  return (
    <Page wide>
      <PageHeader
        icon={<Shield size={22} />}
        eyebrow={tr("Керування", "Operations")}
        title={tr("Адмін-панель", "Admin console")}
        subtitle={tr("Стан сервісу, кеш, задачі, ключі, рев’ю ШІ і перевірки аналітики.", "Service health, cache, jobs, keys, AI reviews and analytics checks.")}
        actions={
          <Button variant="ghost" size="sm" onClick={() => void client.invalidateQueries()}>
            <RefreshCw size={14} /> {tr("Оновити", "Refresh")}
          </Button>
        }
      />
      <Notice text={error} />

      <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
        {(["full", "live", "ready"] as const).map((name) => (
          <Panel key={name} className="flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-widest text-muted">
                {name === "full" ? tr("Загальний", "Overall") : name === "live" ? "Live" : "Ready"}
              </p>
              <p className="mt-1 text-2xl font-semibold capitalize text-foreground">{health.data?.[name].status ?? "—"}</p>
            </div>
            <Chip tone={statusTone(health.data?.[name].status)}>
              <Dot status={health.data?.[name].status} /> v{health.data?.[name].version ?? "?"}
            </Chip>
          </Panel>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <Panel>
          <SectionTitle icon={<Activity size={18} />}>{tr("Проби залежностей", "Dependency probes")}</SectionTitle>
          <ul className="flex flex-col divide-y divide-[var(--glass-border)] text-sm">
            {checks.map(([name, check]) => (
              <li key={name} className="flex items-center justify-between gap-3 py-2.5">
                <span className="flex items-center gap-2 font-medium text-foreground">
                  <Dot status={check.status} /> {name}
                </span>
                <span className="truncate text-right text-xs text-muted">{check.detail || `${check.latency_ms} ms`}</span>
              </li>
            ))}
          </ul>
          {health.isError && <Notice text={failureText(health.error)} />}
        </Panel>

        <Panel className="flex flex-col gap-4">
          <SectionTitle icon={<Database size={18} />} action={cache.data && <Chip tone={cache.data.reachable ? "success" : "danger"}>{cache.data.backend}</Chip>}>
            {tr("Кеш", "Cache")}
          </SectionTitle>
          <ul className="flex flex-col gap-2 text-sm">
            {Object.entries(cache.data?.families ?? {}).map(([name, stats]) => (
              <li key={name}>
                <div className="mb-1 flex justify-between">
                  <span className="text-foreground">{name}</span>
                  <span className="tabular-nums text-muted">
                    {stats.hits}/{stats.hits + stats.misses}
                    {typeof stats.hit_ratio === "number" ? ` · ${Math.round(stats.hit_ratio * 100)}%` : ""}
                  </span>
                </div>
                <Progress value={(stats.hit_ratio ?? 0) * 100} className="h-1.5" />
              </li>
            ))}
            {Object.keys(cache.data?.families ?? {}).length === 0 && <li className="text-muted">{tr("Ще немає звернень.", "No reads yet.")}</li>}
          </ul>
          <div className="flex flex-wrap items-end gap-2">
            <Field label={tr("Родина", "Family")}>
              <Select className="w-36" value={family} onChange={(event) => setFamily(event.target.value as (typeof FAMILIES)[number])}>
                {FAMILIES.map((item) => <option key={item} value={item}>{item}</option>)}
              </Select>
            </Field>
            <Button variant="danger-soft" onClick={() => { if (window.confirm(tr(`Скинути кеш ${family}?`, `Clear the ${family} cache?`))) clear.mutate(); }}>
              <Trash2 size={14} /> {tr("Скинути", "Clear")}
            </Button>
            <Button variant="secondary" onClick={() => warm.mutate()} isDisabled={warm.isPending}>
              <Zap size={14} /> {tr("Прогріти", "Warm")}
            </Button>
            <Button variant="ghost" onClick={() => reload.mutate()} isDisabled={reload.isPending}>
              <RefreshCw size={14} /> {tr("Каталог", "Catalog")}
            </Button>
          </div>
          {warm.data && <Notice tone="success" text={`${tr("Прогріто за", "Warmed in")} ${warm.data.took_ms.toFixed(0)} ms: ${Object.entries(warm.data.warmed).map(([k, v]) => `${k} ${v}`).join(", ")}`} />}
          {clear.data && <Notice tone="success" text={`${tr("Видалено записів", "Removed entries")}: ${clear.data.removed}`} />}
          {reload.data && <Notice tone="success" text={`${tr("Каталог перечитано, покоління", "Catalog reloaded, generation")} ${reload.data.generation}`} />}
        </Panel>

        <Panel>
          <SectionTitle icon={<ListChecks size={18} />} action={<Chip>{jobs.data?.length ?? 0}</Chip>}>
            {tr("Задачі", "Jobs")}
          </SectionTitle>
          <ul className="flex max-h-72 flex-col gap-2 overflow-y-auto text-sm">
            {(jobs.data ?? []).map((job) => (
              <li key={job.id} className="rounded-lg border border-[var(--glass-border)] px-3 py-2">
                <div className="mb-1 flex justify-between">
                  <span className="font-mono text-xs text-foreground">{job.id}</span>
                  <span className="text-xs text-muted">{job.stage}</span>
                </div>
                <Progress value={job.progress} className="h-1.5" />
              </li>
            ))}
            {jobs.data?.length === 0 && <li className="text-muted">{tr("Задач немає.", "No jobs.")}</li>}
          </ul>
          {jobs.isError && <Notice text={failureText(jobs.error)} />}
        </Panel>

        <Panel className="flex flex-col gap-3">
          <SectionTitle icon={<KeyRound size={18} />}>{tr("API-ключі", "API keys")}</SectionTitle>
          <Field label={tr("Id власника", "Owner id")}>
            <Input value={ownerId} onChange={(event) => setOwnerId(event.target.value)} />
          </Field>
          <div className="flex gap-2">
            <Button variant="primary" onClick={() => issue.mutate()} isDisabled={!ownerId || issue.isPending}>{tr("Видати ключ", "Issue key")}</Button>
            <Button variant="danger-soft" onClick={() => revoke.mutate()} isDisabled={!keyId || revoke.isPending}>{tr("Відкликати", "Revoke")}</Button>
          </div>
          {secret && (
            <div className="rounded-xl border border-warning/40 bg-warning-soft p-3 text-xs text-warning-soft-foreground">
              <p className="mb-1 font-semibold">{tr("Секрет показано один раз:", "Secret shown once:")}</p>
              <code className="break-all">{secret}</code>
            </div>
          )}
        </Panel>

        <Panel className="flex flex-col gap-3">
          <SectionTitle icon={<Shield size={18} />}>{tr("Рев’ю розбіжності ШІ", "AI disagreement review")}</SectionTitle>
          <Field label={tr("Id справи", "Case id")}>
            <Input value={caseId} onChange={(event) => setCaseId(event.target.value)} />
          </Field>
          <Field label={tr("Нотатка", "Note")}>
            <TextArea value={note} onChange={(event) => setNote(event.target.value)} />
          </Field>
          <Button variant="secondary" onClick={() => review.mutate()} isDisabled={!caseId || !note.trim() || review.isPending}>{tr("Зберегти рев’ю", "Save review")}</Button>
          {review.data && <Notice tone="success" text={`${tr("Збережено", "Saved")} ${review.data.id}`} />}
        </Panel>

        <Panel className="flex flex-col gap-3">
          <SectionTitle icon={<FlaskConical size={18} />}>{tr("Перевірка аналітики", "Analytics checks")}</SectionTitle>
          <p className="text-sm text-muted">{tr("Синтетичний ряд або сітка напряму в аналітику — після оновлення моделей чи даних.", "A synthetic series or grid sent straight to analytics — after a model or data update.")}</p>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={() => analyze.mutate()} isDisabled={analyze.isPending}>{tr("Аналіз ряду", "Analyze a series")}</Button>
            <Button size="sm" variant="secondary" onClick={() => scan.mutate()} isDisabled={scan.isPending}>{tr("Скан радару", "Radar scan")}</Button>
            <Button size="sm" variant="secondary" onClick={() => grid.mutate()} isDisabled={grid.isPending}>{tr("Пробна сітка", "Sample grid")}</Button>
          </div>
          {tool && <pre className="max-h-64 overflow-auto rounded-xl bg-default p-3 text-xs text-foreground">{tool}</pre>}
        </Panel>
      </div>
    </Page>
  );
}
