import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { Button } from "@heroui/react";
import { FolderOpen, LogIn, Send, UserPlus, Users } from "lucide-react";
import { api } from "../api/client";
import { call, failureText } from "../api/http";
import { Chip, EmptyState, Field, Notice, Page, PageHeader, Panel, SectionTitle, Select, TextArea } from "../components/ui";
import { useTr } from "../i18n";
import { useStore } from "../store/useStore";

export function Join() {
  const tr = useTr();
  const { token: share = "" } = useParams();
  const session = useStore((state) => state.token);
  const role = useStore((state) => state.role);
  const client = useQueryClient();
  const isGuest = role === "guest";
  const [caseId, setCaseId] = useState("");
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const shared = useQuery({
    queryKey: ["shared", share, session],
    enabled: Boolean(session && share),
    queryFn: () => call(api.GET("/api/v1/education/shared/{token}", { params: { path: { token: share } } })),
  });
  const myCases = useQuery({ queryKey: ["cases", session], enabled: Boolean(session && !isGuest), queryFn: () => call(api.GET("/api/v1/cases")) });
  const join = useMutation({
    mutationFn: () => call(api.POST("/api/v1/education/shared/{token}/join", { params: { path: { token: share } } })),
    onSuccess: async () => {
      setError(null);
      await client.invalidateQueries({ queryKey: ["shared", share] });
    },
    onError: (reason) => setError(failureText(reason)),
  });
  const view = join.data ?? shared.data;
  const choices = [...(view?.case_ids ?? []), ...(myCases.data ?? []).map((item) => item.id).filter((id) => !view?.case_ids.includes(id))];
  const chosen = caseId || choices[0] || "";

  const submit = useMutation({
    mutationFn: () => call(api.POST("/api/v1/education/submissions", { body: { assignment_id: view?.id ?? "", case_id: chosen, text } })),
    onSuccess: async () => {
      setError(null);
      setText("");
      await client.invalidateQueries({ queryKey: ["badges"] });
    },
    onError: (reason) => setError(failureText(reason)),
  });

  return (
    <Page>
      <PageHeader
        icon={<Users size={22} />}
        eyebrow={tr("Посилання класу", "Class link")}
        title={view?.title ?? tr("Завдання класу", "Class assignment")}
        subtitle={tr("Приєднайся, розслідуй справи і здай висновок.", "Join, investigate the cases and hand in your conclusion.")}
        actions={<Chip tone={view?.joined ? "success" : "neutral"}>{view?.joined ? tr("Ти в класі", "Joined") : tr("Ще не приєднано", "Not joined")}</Chip>}
      />
      {isGuest && (
        <Notice tone="info" text={tr("Гість не може приєднатися. Увійди або зареєструйся і повернись за цим посиланням.", "A guest cannot join. Sign in or register, then come back to this link.")} />
      )}
      <Notice text={error || (shared.isError ? failureText(shared.error) : null)} />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Panel className="flex flex-col gap-4">
          <SectionTitle icon={<FolderOpen size={18} />}>{tr("Справи завдання", "Assignment cases")}</SectionTitle>
          {(view?.case_ids ?? []).length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {view?.case_ids.map((id) => (
                <Link key={id} to={`/case/${id}`}><Chip tone="accent">{id}</Chip></Link>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted">{tr("Відкрий власну справу в Розслідуванні.", "Open your own case in Explore.")}</p>
          )}
          {!view?.joined &&
            (isGuest ? (
              <Link to="/session" className="bg-gradient-brand flex h-10 items-center justify-center gap-2 rounded-xl font-medium text-white hover:opacity-90">
                <LogIn size={16} /> {tr("Увійти", "Sign in")}
              </Link>
            ) : (
              <Button variant="primary" onClick={() => join.mutate()} isDisabled={!session || join.isPending || !view}>
                <UserPlus size={16} /> {tr("Приєднатися", "Join class")}
              </Button>
            ))}
        </Panel>
        {view?.joined ? (
          <Panel className="flex flex-col gap-4">
            <SectionTitle icon={<Send size={18} />}>{tr("Мій висновок", "My conclusion")}</SectionTitle>
            <Field label={tr("Справа", "Case")}>
              <Select value={chosen} onChange={(event) => setCaseId(event.target.value)}>
                {choices.map((id) => <option key={id} value={id}>{id}</option>)}
              </Select>
            </Field>
            <Field label={tr("Висновок", "Conclusion")}>
              <TextArea className="min-h-32" value={text} onChange={(event) => setText(event.target.value)} placeholder={tr("Що показали докази?", "What did the evidence show?")} />
            </Field>
            <Button variant="primary" onClick={() => submit.mutate()} isDisabled={!chosen || !text.trim() || submit.isPending}>
              <Send size={16} /> {tr("Здати", "Hand in")}
            </Button>
            {submit.isSuccess && <Notice tone="success" text={tr("Відповідь здано. Бейдж — у журналі.", "Answer handed in. Your badge is in the journal.")} />}
          </Panel>
        ) : (
          <EmptyState icon={<Send size={28} />} title={tr("Після приєднання тут з’явиться форма відповіді", "The answer form appears after you join")} />
        )}
      </div>
    </Page>
  );
}
