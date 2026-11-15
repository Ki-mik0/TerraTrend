import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Button } from "@heroui/react";
import { ArrowRight, GitCompare, Scale } from "lucide-react";
import { api } from "../api/client";
import { call, failureText } from "../api/http";
import { compareSentence } from "../explain";
import { useNames } from "../hooks/useNames";
import { Chip, DataSourceChip, EmptyState, Slope, Field, Input, Notice, Page, PageHeader, Panel, Select, VerdictBadge } from "../components/ui";
import { useTr } from "../i18n";
import { useStore } from "../store/useStore";

export function Compare() {
  const token = useStore((state) => state.token);
  const language = useStore((state) => state.language);
  const tr = useTr();
  const names = useNames();
  const [variableId, setVariableId] = useState("");
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
  const [fromYear, setFromYear] = useState("2000");
  const [toYear, setToYear] = useState("2024");
  const [error, setError] = useState<string | null>(null);

  const variables = useQuery({ queryKey: ["variables", ""], enabled: Boolean(token), queryFn: () => call(api.GET("/api/v1/variables")) });
  const regions = useQuery({ queryKey: ["regions"], enabled: Boolean(token), queryFn: () => call(api.GET("/api/v1/regions")) });
  const chosenVariable = variableId || variables.data?.[0]?.id || "";
  const chosenLeft = left || regions.data?.[0]?.id || "";
  const chosenRight = right || regions.data?.[1]?.id || regions.data?.[0]?.id || "";
  const regionName = names.region;

  const compare = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/v1/cases/compare", {
          body: {
            variable_id: chosenVariable,
            region_ids: [chosenLeft, chosenRight],
            period_start: `${fromYear}-01`,
            period_end: `${toYear}-12`,
            language,
          },
        }),
      ),
    onSuccess: () => setError(null),
    onError: (reason) => setError(failureText(reason)),
  });

  return (
    <Page>
      <PageHeader
        icon={<GitCompare size={22} />}
        eyebrow={tr("Два регіони", "Two regions")}
        title={tr("Порівняння регіонів", "Cross-region comparison")}
        subtitle={tr("Одна змінна, два регіони. Для кожного відкривається справа за тими самими правилами.", "One variable, two regions. Each side opens a case under the same rules.")}
      />

      <Panel className="mb-6">
        <div className="grid grid-cols-1 items-end gap-4 md:grid-cols-2 lg:grid-cols-[1.3fr_1fr_1fr_110px_110px_auto]">
          <Field label={tr("Змінна", "Variable")}>
            <Select value={chosenVariable} onChange={(event) => setVariableId(event.target.value)}>
              {(variables.data ?? []).map((item) => (
                <option key={item.id} value={item.id}>{language === "uk" ? item.name_uk || item.name : item.name}</option>
              ))}
            </Select>
          </Field>
          <Field label={tr("Перший регіон", "First region")}>
            <Select value={chosenLeft} onChange={(event) => setLeft(event.target.value)}>
              {(regions.data ?? []).map((item) => <option key={item.id} value={item.id}>{names.region(item.id)}</option>)}
            </Select>
          </Field>
          <Field label={tr("Другий регіон", "Second region")}>
            <Select value={chosenRight} onChange={(event) => setRight(event.target.value)}>
              {(regions.data ?? []).map((item) => <option key={item.id} value={item.id}>{names.region(item.id)}</option>)}
            </Select>
          </Field>
          <Field label={tr("Від", "From")}>
            <Input type="number" min={1980} max={2024} value={fromYear} onChange={(event) => setFromYear(event.target.value)} />
          </Field>
          <Field label={tr("До", "To")}>
            <Input type="number" min={1981} max={2025} value={toYear} onChange={(event) => setToYear(event.target.value)} />
          </Field>
          <Button
            variant="primary"
            className="h-10"
            onClick={() => compare.mutate()}
            isDisabled={!token || compare.isPending || chosenLeft === chosenRight || Number(fromYear) >= Number(toYear)}
          >
            <Scale size={16} /> {tr("Порівняти", "Compare")}
          </Button>
        </div>
      </Panel>

      <Notice text={chosenLeft && chosenLeft === chosenRight ? tr("Обери два різні регіони.", "Pick two different regions.") : error} />
      <Notice text={variables.isError ? failureText(variables.error) : null} />

      {compare.data && compare.data.cases.length === 2 && (() => {
        const [first, second] = compare.data.cases;
        const text = compareSentence(
          { region: names.region(first.region_id), slope: first.slope_decade },
          { region: names.region(second.region_id), slope: second.slope_decade },
          names.variable(first.variable_id),
          names.units(first.variable_id),
          tr,
        );
        return text ? <Panel className="mb-6"><p className="text-lg text-foreground">{text}</p></Panel> : null;
      })()}
      {compare.data ? (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          {compare.data.cases.map((item, index) => (
            <Panel key={item.id} className="relative flex flex-col gap-4 overflow-hidden">
              <div className="bg-gradient-brand absolute inset-x-0 top-0 h-1" />
              <div className="flex items-center justify-between">
                <Chip>{index === 0 ? tr("Перший", "First") : tr("Другий", "Second")}</Chip>
                {item.status !== "completed" && <Chip tone="warning">{tr("рахується…", "computing…")}</Chip>}
              </div>
              <div>
                <h3 className="text-2xl font-bold text-foreground">{regionName(item.region_id)}</h3>
                <p className="text-sm text-muted">{names.variable(item.variable_id)}</p>
              </div>
              <DataSourceChip version={item.datasets_version} />
              <VerdictBadge code={item.verdict?.code} direction={item.direction} size="lg" />
              {typeof item.slope_decade === "number" && (
                <Slope value={item.slope_decade} unit={`${names.units(item.variable_id)} ${tr("за 10 років", "per decade")}`.trim()} className="text-2xl" />
              )}
              <Link to={`/case/${item.id}`} className="mt-auto inline-flex items-center gap-1 text-sm font-medium text-accent hover:underline">
                {tr("Відкрити справу", "Open the case")} <ArrowRight size={14} />
              </Link>
            </Panel>
          ))}
        </div>
      ) : (
        <EmptyState
          icon={<Scale size={28} />}
          title={tr("Обери змінну і два регіони", "Pick a variable and two regions")}
          text={tr("Результати стануть поруч — з вироком для кожного боку.", "The results will sit side by side, each with its verdict.")}
        />
      )}
    </Page>
  );
}
