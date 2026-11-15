import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@heroui/react";
import { Copy, Inbox, Link2, PlusCircle, Users } from "lucide-react";
import { api } from "../api/client";
import { call, failureText } from "../api/http";
import { Chip, EmptyState, Field, Input, Notice, Page, PageHeader, Panel, SectionTitle, Select, VerdictBadge } from "../components/ui";
import { useNames } from "../hooks/useNames";
import { useTr } from "../i18n";
import { useStore } from "../store/useStore";

function StepBadge({ n }: { n: number }) {
  return <span className="bg-gradient-brand flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-semibold text-white">{n}</span>;
}

export function Teacher() {
  const tr = useTr();
  const names = useNames();
  const token = useStore((state) => state.token);
  const role = useStore((state) => state.role);
  const client = useQueryClient();
  const teaches = role === "teacher" || role === "admin";
  const [title, setTitle] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [studentIds, setStudentIds] = useState("");
  const [assignmentId, setAssignmentId] = useState("");
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const myCases = useQuery({ queryKey: ["cases", token], enabled: Boolean(token && teaches), queryFn: () => call(api.GET("/api/v1/cases")) });
  const assignments = useQuery({
    queryKey: ["assignments", token],
    enabled: Boolean(token && teaches),
    queryFn: () => call(api.GET("/api/v1/education/assignments")),
  });
  const selected = assignmentId || assignments.data?.[0]?.id || "";
  const detail = useQuery({
    queryKey: ["assignment", selected],
    enabled: Boolean(token && teaches && selected),
    queryFn: () => call(api.GET("/api/v1/education/assignments/{assignment_id}", { params: { path: { assignment_id: selected } } })),
  });
  const submissions = useQuery({
    queryKey: ["submissions", selected],
    enabled: Boolean(token && teaches && selected),
    queryFn: () => call(api.GET("/api/v1/education/submissions", { params: { query: { assignment_id: selected } } })),
  });

  const create = useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/v1/education/assignments", {
          body: { title, case_ids: picked, student_ids: studentIds.split(",").map((item) => item.trim()).filter(Boolean) },
        }),
      ),
    onSuccess: async (created) => {
      setError(null);
      setTitle("");
      setPicked([]);
      setStudentIds("");
      setAssignmentId(created.id);
      await client.invalidateQueries({ queryKey: ["assignments"] });
    },
    onError: (reason) => setError(failureText(reason)),
  });
  const share = useMutation({
    mutationFn: () => call(api.POST("/api/v1/education/assignments/{assignment_id}/share", { params: { path: { assignment_id: selected } } })),
    onSuccess: async () => {
      setError(null);
      setCopied(false);
      await client.invalidateQueries({ queryKey: ["assignment", selected] });
    },
    onError: (reason) => setError(failureText(reason)),
  });

  const shareToken = share.data?.token || detail.data?.share_token;
  const shareLink = shareToken ? `${window.location.origin}/join/${shareToken}` : null;

  if (!teaches) {
    return (
      <Page>
        <PageHeader icon={<Users size={22} />} title={tr("Кабінет вчителя", "Teacher desk")} subtitle={tr("Завдання, посилання класу і відповіді учнів.", "Assignments, class links and student answers.")} />
        <EmptyState
          icon={<Users size={28} />}
          title={tr("Цей кабінет — для вчителя", "This desk is for teachers")}
          text={tr("Учень відкриває завдання за посиланням класу, яке дає вчитель.", "A student opens an assignment from the class link the teacher shares.")}
        />
      </Page>
    );
  }

  return (
    <Page>
      <PageHeader
        icon={<Users size={22} />}
        eyebrow={tr("Клас", "Class")}
        title={tr("Кабінет вчителя", "Teacher desk")}
        subtitle={tr("Створи завдання зі своїх справ, поділись посиланням і читай відповіді.", "Build an assignment from your cases, share the link and read the answers.")}
        actions={<Chip tone="accent">{assignments.data?.length ?? 0} {tr("завдань", "assignments")}</Chip>}
      />
      <Notice text={error || (assignments.isError ? failureText(assignments.error) : null)} />

      <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Panel className="flex flex-col gap-4">
          <SectionTitle icon={<StepBadge n={1} />}>{tr("Створи завдання", "Create an assignment")}</SectionTitle>
          <Field label={tr("Назва", "Title")}>
            <Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder={tr("Посуха на півдні", "Drought in the south")} />
          </Field>
          <Field label={tr("Справи завдання", "Cases")} hint={tr("Порожньо — учень бере будь-яку свою справу.", "Leave empty — a student uses any own case.")}>
            <div className="flex max-h-48 flex-col gap-1 overflow-auto rounded-xl border border-[var(--glass-border)] p-2">
              {(myCases.data ?? []).map((item) => (
                <label key={item.id} className="flex cursor-pointer items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-default">
                  <span className="flex items-center gap-2 text-foreground">
                    <input
                      type="checkbox"
                      className="accent-[var(--color-accent)]"
                      checked={picked.includes(item.id)}
                      onChange={(event) => setPicked((current) => (event.target.checked ? [...current, item.id] : current.filter((id) => id !== item.id)))}
                    />
                    {names.variable(item.variable_id)} · {names.region(item.region_id)}
                  </span>
                  <VerdictBadge code={item.verdict?.code} direction={item.verdict?.direction} />
                </label>
              ))}
              {myCases.data?.length === 0 && (
                <p className="p-2 text-xs text-muted">
                  {tr("Спершу відкрий справу в ", "Open a case first in ")}
                  <Link to="/explore" className="text-accent">{tr("Розслідуванні", "Explore")}</Link>.
                </p>
              )}
            </div>
          </Field>
          <Field label={tr("Id учнів через кому", "Student ids, comma separated")} hint={tr("Необов’язково: учні можуть приєднатися за посиланням.", "Optional: students can join by the link.")}>
            <Input value={studentIds} onChange={(event) => setStudentIds(event.target.value)} />
          </Field>
          <Button variant="primary" onClick={() => create.mutate()} isDisabled={!title.trim() || create.isPending}>
            <PlusCircle size={16} /> {tr("Створити", "Create")}
          </Button>
        </Panel>

        <Panel className="flex flex-col gap-4">
          <SectionTitle icon={<StepBadge n={2} />}>{tr("Поділись з класом", "Share with the class")}</SectionTitle>
          <Field label={tr("Завдання", "Assignment")}>
            <Select value={selected} onChange={(event) => setAssignmentId(event.target.value)} disabled={!assignments.data?.length}>
              {(assignments.data ?? []).map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
            </Select>
          </Field>
          {detail.data && (
            <div className="flex flex-col gap-2 text-sm">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-muted">{tr("Справи:", "Cases:")}</span>
                {detail.data.case_ids.length
                  ? detail.data.case_ids.map((id) => <Link key={id} to={`/case/${id}`}><Chip tone="accent">{id}</Chip></Link>)
                  : <span className="text-muted">{tr("будь-яка справа учня", "any case of the student")}</span>}
              </div>
              <p className="text-muted">
                {tr("Учні:", "Students:")} <span className="text-foreground">{detail.data.student_ids.join(", ") || "—"}</span>
              </p>
            </div>
          )}
          <Button variant="secondary" onClick={() => share.mutate()} isDisabled={!selected || share.isPending}>
            <Link2 size={16} /> {shareToken ? tr("Видати нове посилання", "Issue a new link") : tr("Видати посилання класу", "Issue a class link")}
          </Button>
          {shareLink && (
            <div className="flex items-center gap-2 rounded-xl border border-accent/30 bg-accent-soft p-2 pl-3">
              <code className="min-w-0 flex-1 truncate text-sm text-foreground">{shareLink}</code>
              <Button size="sm" variant={copied ? "secondary" : "primary"} onClick={() => void navigator.clipboard?.writeText(shareLink).then(() => setCopied(true))}>
                <Copy size={14} /> {copied ? tr("Скопійовано", "Copied") : tr("Копіювати", "Copy")}
              </Button>
            </div>
          )}
        </Panel>
      </div>

      <Panel>
        <SectionTitle icon={<StepBadge n={3} />} action={<Chip>{submissions.data?.length ?? 0}</Chip>}>
          {tr("Відповіді учнів", "Student answers")}
        </SectionTitle>
        <Notice text={submissions.isError ? failureText(submissions.error) : null} />
        {(submissions.data ?? []).length > 0 ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {(submissions.data ?? []).map((item) => (
              <div key={item.id} className="rounded-xl border border-[var(--glass-border)] p-4">
                <div className="mb-2 flex items-center justify-between gap-2 text-sm">
                  <span className="font-semibold text-foreground">{item.student_id}</span>
                  <Link to={`/case/${item.case_id}`} className="text-accent hover:underline">{item.case_id}</Link>
                </div>
                <p className="whitespace-pre-wrap text-sm text-muted">{item.text}</p>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState icon={<Inbox size={28} />} title={tr("Відповідей ще немає", "No answers yet")} text={tr("Вони з’являться, коли учні здадуть завдання за посиланням.", "They appear once students hand in through the link.")} />
        )}
      </Panel>
    </Page>
  );
}
