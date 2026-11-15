import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@heroui/react";
import { Bot, History, LogIn, MessageSquare, Send, Sparkles, Wrench } from "lucide-react";
import { api } from "../api/client";
import { call, failureText } from "../api/http";
import { readSse } from "../api/sse";
import { Chip, EmptyState, Notice, Page, PageHeader, Panel, SectionTitle, Segmented, TextArea } from "../components/ui";
import { useTr } from "../i18n";
import { useStore } from "../store/useStore";

const SUGGESTIONS: Array<[string, string]> = [
  ["Чи висихає південь України влітку?", "Is southern Ukraine drying in summer?"],
  ["Чи гріється Арктика швидше за інші регіони?", "Is the Arctic warming faster than other regions?"],
  ["Що змінюється найсильніше на планеті?", "What is changing the most on the planet?"],
];

export function Assistant() {
  const token = useStore((state) => state.token);
  const role = useStore((state) => state.role);
  const language = useStore((state) => state.language);
  const tr = useTr();
  const client = useQueryClient();
  const canAsk = Boolean(token) && role !== "guest";
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState("");
  const [mode, setMode] = useState<"investigate" | "teach">("investigate");
  const [selected, setSelected] = useState("");
  const [live, setLive] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const history = useQuery({
    queryKey: ["exchanges", token],
    enabled: canAsk,
    queryFn: () => call(api.GET("/api/v1/assistant/exchanges", { params: { query: { limit: 20 } } })),
  });
  const one = useQuery({
    queryKey: ["exchange", selected],
    enabled: Boolean(canAsk && selected),
    queryFn: () => call(api.GET("/api/v1/assistant/exchanges/{exchange_id}", { params: { path: { exchange_id: selected } } })),
  });
  const ask = useMutation({
    mutationFn: () => call(api.POST("/api/v1/assistant/ask", { body: { question, language, mode } })),
    onMutate: () => {
      setAsked(question);
      setLive("");
    },
    onSuccess: async (data) => {
      setError(null);
      setSelected(data.exchange_id);
      setQuestion("");
      await client.invalidateQueries({ queryKey: ["exchanges"] });
    },
    onError: (reason) => setError(failureText(reason)),
  });
  const stream = async () => {
    setAsked(question);
    setLive("");
    setSelected("");
    setError(null);
    setStreaming(true);
    try {
      await readSse(
        "/api/v1/assistant/ask/stream",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, language, mode }) },
        (event, data) => {
          if (event === "answer_chunk" && data && typeof data === "object" && "text" in data) {
            setLive((current) => current + String((data as { text: string }).text));
          }
          if (event === "done" && data && typeof data === "object" && "exchange_id" in data) {
            setSelected(String((data as { exchange_id: string }).exchange_id));
          }
        },
      );
      setQuestion("");
      await client.invalidateQueries({ queryKey: ["exchanges"] });
    } catch (reason) {
      setError(failureText(reason));
    } finally {
      setStreaming(false);
    }
  };

  const shown = one.data ?? ask.data;
  const shownQuestion = one.data?.question ?? asked;
  const busy = ask.isPending || streaming;

  return (
    <Page>
      <PageHeader
        icon={<MessageSquare size={22} />}
        eyebrow={tr("ШІ-помічник", "AI helper")}
        title={tr("Асистент детектива", "Detective assistant")}
        subtitle={tr("Постав запитання — асистент складе план розслідування і відповість лише числами з відкритих справ.", "Ask a question — the assistant plans the investigation and answers only with numbers from opened cases.")}
      />
      {!canAsk && (
        <Panel className="mb-6 flex flex-col items-start gap-3 md:flex-row md:items-center md:justify-between">
          <p className="text-sm text-muted">{tr("Асистент доступний після входу. Гість може читати каталог і радар.", "Sign in to use the assistant. Guests can read the catalog and the radar.")}</p>
          <Link to="/session" className="bg-gradient-brand inline-flex h-9 items-center gap-2 rounded-lg px-4 text-sm font-medium text-white hover:opacity-90">
            <LogIn size={16} /> {tr("Увійти", "Sign in")}
          </Link>
        </Panel>
      )}
      <Notice text={error || (history.isError ? failureText(history.error) : null)} />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <Panel className="flex min-h-[560px] flex-col" padded={false}>
          <div className="flex-1 space-y-5 overflow-y-auto p-5 md:p-6">
            {!shownQuestion && !shown ? (
              <EmptyState
                icon={<Sparkles size={28} />}
                title={tr("З чого почнемо розслідування?", "Where shall we start?")}
                text={tr("Спробуй одне з запитань нижче або напиши своє.", "Try one of the questions below or write your own.")}
                action={
                  <div className="flex flex-wrap justify-center gap-2">
                    {SUGGESTIONS.map(([uk, en]) => (
                      <button key={en} type="button" className="rounded-full border border-[var(--glass-border)] px-3 py-1.5 text-sm text-foreground hover:bg-default" onClick={() => setQuestion(tr(uk, en))}>
                        {tr(uk, en)}
                      </button>
                    ))}
                  </div>
                }
              />
            ) : (
              <>
                {shownQuestion && (
                  <div className="flex justify-end">
                    <p className="bg-gradient-brand max-w-[80%] rounded-2xl rounded-br-md px-4 py-3 text-white">{shownQuestion}</p>
                  </div>
                )}
                {shown && shown.plan.length > 0 && (
                  <div className="flex gap-3">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-default text-muted"><Wrench size={15} /></span>
                    <ol className="flex flex-1 flex-col gap-2 border-l border-[var(--glass-border)] pl-4">
                      {shown.plan.map((step, index) => (
                        <li key={`${step.tool}-${index}`} className="text-sm">
                          <Chip tone="accent">{step.tool}</Chip>
                          <span className="ml-2 text-muted">{step.reason}</span>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}
                {(live || shown?.answer || busy) && (
                  <div className="flex gap-3">
                    <span className="bg-gradient-brand flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-white"><Bot size={16} /></span>
                    <div className="max-w-[85%] rounded-2xl rounded-tl-md border border-[var(--glass-border)] bg-surface/60 px-4 py-3">
                      <p className="whitespace-pre-wrap leading-relaxed text-foreground">
                        {live || shown?.answer || <span className="animate-pulse text-muted">{tr("Думаю…", "Thinking…")}</span>}
                      </p>
                      {shown && shown.case_ids.length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-1.5">
                          {shown.case_ids.map((id) => (
                            <Link key={id} to={`/case/${id}`}><Chip tone="accent">{tr("справа", "case")} {id}</Chip></Link>
                          ))}
                        </div>
                      )}
                      {shown && (shown.warnings ?? []).map((item) => <p key={item} className="mt-2 text-xs text-muted">⚠ {item}</p>)}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
          <div className="border-t border-[var(--glass-border)] p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <Segmented<"investigate" | "teach">
                value={mode}
                onChange={setMode}
                options={[
                  { value: "investigate", label: tr("Розслідування", "Investigate") },
                  { value: "teach", label: tr("Навчання", "Teach") },
                ]}
              />
              <span className="text-xs text-muted">{mode === "teach" ? tr("Сократівські запитання замість готової відповіді", "Socratic questions instead of a ready answer") : tr("План, інструменти і відповідь з id справи", "Plan, tools and an answer with a case id")}</span>
            </div>
            <div className="flex items-end gap-2">
              <TextArea
                className="min-h-14 flex-1"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey && canAsk && question.trim() && !busy) {
                    event.preventDefault();
                    void stream();
                  }
                }}
                placeholder={tr("Чи висихає південь України влітку?", "Is southern Ukraine drying in summer?")}
                disabled={!canAsk}
              />
              <div className="flex flex-col gap-2">
                <Button variant="primary" onClick={() => void stream()} isDisabled={!canAsk || !question.trim() || busy} aria-label={tr("Надіслати", "Send")}>
                  <Send size={16} /> {tr("Надіслати", "Send")}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => ask.mutate()} isDisabled={!canAsk || !question.trim() || busy}>
                  {tr("Без стріму", "No stream")}
                </Button>
              </div>
            </div>
          </div>
        </Panel>

        <Panel className="h-fit">
          <SectionTitle icon={<History size={18} />}>{tr("Історія", "History")}</SectionTitle>
          {(history.data?.exchanges ?? []).length > 0 ? (
            <ul className="flex flex-col gap-1">
              {(history.data?.exchanges ?? []).map((item) => (
                <li key={item.exchange_id}>
                  <button
                    type="button"
                    onClick={() => { setSelected(item.exchange_id); setLive(""); setAsked(""); }}
                    className={`w-full rounded-lg px-3 py-2 text-left text-sm transition-colors ${selected === item.exchange_id ? "bg-accent-soft text-foreground" : "text-muted hover:bg-default hover:text-foreground"}`}
                  >
                    <span className="line-clamp-2">{item.question}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">{tr("Тут з’являться твої запитання.", "Your questions will appear here.")}</p>
          )}
        </Panel>
      </div>
    </Page>
  );
}
