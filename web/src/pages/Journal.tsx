import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@heroui/react";
import { Award, BookOpen, CircleCheck, FolderOpen, GraduationCap, Lightbulb, NotebookPen, Split, Target, Trash2, XCircle } from "lucide-react";
import { api } from "../api/client";
import { call, failureText } from "../api/http";
import { Chip, EmptyState, Field, Notice, Page, PageHeader, Panel, SectionTitle, Segmented, Select, TextArea, VerdictBadge } from "../components/ui";
import { useNames } from "../hooks/useNames";
import { useTr } from "../i18n";
import { useStore } from "../store/useStore";

const BADGES: Record<string, { icon: ReactNode; label: [string, string] }> = {
  assignment: { icon: <GraduationCap size={18} />, label: ["Здане завдання", "Assignment handed in"] },
  demo: { icon: <CircleCheck size={18} />, label: ["Пройдене демо", "Demo completed"] },
  quiz: { icon: <Lightbulb size={18} />, label: ["Правильна вікторина", "Quiz answered"] },
  first_significant_trend: { icon: <Target size={18} />, label: ["Перший значущий тренд", "First significant trend"] },
  found_split: { icon: <Split size={18} />, label: ["Знайшов розкол", "Found a split"] },
  refuted_false_trend: { icon: <XCircle size={18} />, label: ["Спростував хибний тренд", "Refuted a false trend"] },
};

export function Journal() {
  const tr = useTr();
  const names = useNames();
  const token = useStore((state) => state.token);
  const role = useStore((state) => state.role);
  const isGuest = role === "guest";
  const client = useQueryClient();
  const [caseId, setCaseId] = useState("");
  const [text, setText] = useState("");
  const [kind, setKind] = useState<"note" | "hypothesis">("note");
  const [error, setError] = useState<string | null>(null);

  const enabled = Boolean(token && !isGuest);
  const journal = useQuery({ queryKey: ["journal", token], enabled, queryFn: () => call(api.GET("/api/v1/journal")) });
  const saved = useQuery({ queryKey: ["journal-cases", token], enabled, queryFn: () => call(api.GET("/api/v1/journal/cases")) });
  const myCases = useQuery({ queryKey: ["cases", token], enabled, queryFn: () => call(api.GET("/api/v1/cases")) });
  const badges = useQuery({ queryKey: ["badges", token], enabled: Boolean(token), queryFn: () => call(api.GET("/api/v1/education/badges")) });

  const byId = useMemo(() => new Map((myCases.data ?? []).map((item) => [item.id, item])), [myCases.data]);
  const chosenCase = caseId || saved.data?.[0]?.case_id || "";
  const caseName = (id: string) => {
    const known = byId.get(id);
    return known ? `${names.variable(known.variable_id)} · ${names.region(known.region_id)}` : id;
  };

  const add = useMutation({
    mutationFn: () => call(api.POST("/api/v1/journal/notes", { body: { case_id: chosenCase, text, kind } })),
    onSuccess: async () => {
      setError(null);
      setText("");
      await client.invalidateQueries({ queryKey: ["journal"] });
    },
    onError: (reason) => setError(failureText(reason)),
  });
  const remove = useMutation({
    mutationFn: (noteId: string) => call(api.DELETE("/api/v1/journal/notes/{note_id}", { params: { path: { note_id: noteId } } })),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["journal"] });
    },
    onError: (reason) => setError(failureText(reason)),
  });

  return (
    <Page>
      <PageHeader
        icon={<BookOpen size={22} />}
        eyebrow={tr("Особисте", "Personal")}
        title={tr("Журнал детектива", "Detective journal")}
        subtitle={tr("Твої справи, нотатки, гіпотези і бейджі.", "Your cases, notes, hypotheses and badges.")}
        actions={
          <>
            <Chip tone="accent">{journal.data?.notes.length ?? 0} {tr("нотаток", "notes")}</Chip>
            <Chip>{badges.data?.length ?? 0} {tr("бейджів", "badges")}</Chip>
          </>
        }
      />
      {isGuest && (
        <Notice
          tone="info"
          text={tr("Справи гостя тимчасові і в журнал не потрапляють. Увійди, щоб вести журнал.", "Guest cases are temporary and stay out of the journal. Sign in to keep one.")}
        />
      )}
      <Notice text={journal.isError ? failureText(journal.error) : error} />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
        <div className="flex flex-col gap-6">
          <Panel className="flex flex-col gap-4">
            <SectionTitle icon={<NotebookPen size={18} />}>{tr("Нова нотатка", "New note")}</SectionTitle>
            <Segmented<"note" | "hypothesis">
              value={kind}
              onChange={setKind}
              options={[
                { value: "note", label: tr("Нотатка", "Note") },
                { value: "hypothesis", label: tr("Гіпотеза", "Hypothesis") },
              ]}
            />
            <Field label={tr("Справа", "Case")}>
              <Select value={chosenCase} onChange={(event) => setCaseId(event.target.value)} disabled={!enabled}>
                {(saved.data ?? []).map((item) => <option key={item.case_id} value={item.case_id}>{caseName(item.case_id)}</option>)}
              </Select>
            </Field>
            <Field label={tr("Текст", "Text")}>
              <TextArea
                value={text}
                onChange={(event) => setText(event.target.value)}
                disabled={!enabled}
                placeholder={kind === "hypothesis" ? tr("Я думаю, що…", "I think that…") : tr("Що я помітив…", "What I noticed…")}
              />
            </Field>
            <Button variant="primary" onClick={() => add.mutate()} isDisabled={!enabled || !chosenCase || !text.trim() || add.isPending}>
              {tr("Зберегти", "Save")}
            </Button>
          </Panel>

          <Panel>
            <SectionTitle icon={<Award size={18} />}>{tr("Бейджі", "Badges")}</SectionTitle>
            {(badges.data ?? []).length > 0 ? (
              <ul className="grid grid-cols-1 gap-2">
                {(badges.data ?? []).map((item) => {
                  const badge = BADGES[item.code];
                  return (
                    <li key={item.id} className="flex items-center gap-3 rounded-xl border border-[var(--glass-border)] p-3">
                      <span className="bg-gradient-brand flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-white">{badge?.icon ?? <Award size={18} />}</span>
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-foreground">{badge ? tr(...badge.label) : item.code}</p>
                        <p className="truncate text-xs text-muted">{item.reason}</p>
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="text-sm text-muted">{tr("Бейджі з’являться за демо, вікторини і справи.", "Badges come from demos, quizzes and cases.")}</p>
            )}
          </Panel>
        </div>

        <div className="flex flex-col gap-6">
          <Panel>
            <SectionTitle icon={<FolderOpen size={18} />}>{tr("Збережені справи", "Saved cases")}</SectionTitle>
            <Notice text={saved.isError ? failureText(saved.error) : null} />
            {(saved.data ?? []).length > 0 ? (
              <ul className="flex flex-col divide-y divide-[var(--glass-border)]">
                {(saved.data ?? []).map((item) => {
                  const known = byId.get(item.case_id);
                  return (
                    <li key={item.case_id}>
                      <Link to={`/case/${item.case_id}`} className="flex items-center justify-between gap-3 rounded-lg px-2 py-3 transition-colors hover:bg-default">
                        <span className="min-w-0 truncate font-medium text-foreground">{caseName(item.case_id)}</span>
                        <VerdictBadge code={known?.verdict?.code} direction={known?.verdict?.direction} />
                      </Link>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <EmptyState
                icon={<FolderOpen size={28} />}
                title={tr("Поки жодної справи", "No cases yet")}
                text={tr("Відкрий першу справу в Розслідуванні — вона збережеться тут.", "Open your first case in Explore — it will be saved here.")}
                action={<Link to="/explore" className="text-sm font-medium text-accent hover:underline">{tr("До розслідування →", "Go to Explore →")}</Link>}
              />
            )}
          </Panel>

          <div className="flex flex-col gap-3">
            {(journal.data?.notes ?? []).map((note) => (
              <Panel key={note.id} className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <Chip tone={note.kind === "hypothesis" ? "warning" : "accent"}>
                      {note.kind === "hypothesis" ? tr("гіпотеза", "hypothesis") : tr("нотатка", "note")}
                    </Chip>
                    <Link to={`/case/${note.case_id}`} className="text-sm text-muted hover:text-accent">{caseName(note.case_id)}</Link>
                  </div>
                  <p className="whitespace-pre-wrap text-foreground">{note.text}</p>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  isIconOnly
                  aria-label={tr("Видалити", "Delete")}
                  onClick={() => {
                    if (window.confirm(tr("Видалити нотатку?", "Delete this note?"))) remove.mutate(note.id);
                  }}
                >
                  <Trash2 size={16} />
                </Button>
              </Panel>
            ))}
          </div>
        </div>
      </div>
    </Page>
  );
}
