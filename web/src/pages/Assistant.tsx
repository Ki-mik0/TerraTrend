import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@heroui/react";
import { Bot, History, LogIn, MessageSquare, MessageSquarePlus, Send, Sparkles, Wrench } from "lucide-react";
import { api } from "../api/client";
import { call, failureText } from "../api/http";
import type { components } from "../api/schema";
import { readSse } from "../api/sse";
import { Chip, EmptyState, Notice, Page, PageHeader, Panel, SectionTitle, Segmented, TextArea } from "../components/ui";
import { useTr, type Translate } from "../i18n";
import { useStore } from "../store/useStore";

type Answer = components["schemas"]["AskResponse"];
type Past = components["schemas"]["ExchangeResponse"];

/** One question and its answer in the open chat. */
type Turn = {
  key: string;
  question: string;
  exchangeId?: string;
  live: string;
  pending: boolean;
  data?: Answer;
};

const SUGGESTIONS: Array<[string, string]> = [
  ["Чи висихає південь України влітку?", "Is southern Ukraine drying in summer?"],
  ["Чи гріється Арктика швидше за інші регіони?", "Is the Arctic warming faster than other regions?"],
  ["Що змінюється найсильніше на планеті?", "What is changing the most on the planet?"],
];

let turnCounter = 0;
const nextKey = () => `turn-${++turnCounter}`;

export function Assistant() {
  const token = useStore((state) => state.token);
  const role = useStore((state) => state.role);
  const language = useStore((state) => state.language);
  const tr = useTr();
  const client = useQueryClient();
  const canAsk = Boolean(token) && role !== "guest";
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<"investigate" | "teach">("investigate");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const history = useQuery({
    queryKey: ["exchanges", token],
    enabled: canAsk,
    queryFn: () => call(api.GET("/api/v1/assistant/exchanges", { params: { query: { limit: 20 } } })),
  });

  const update = (key: string, patch: Partial<Turn>) =>
    setTurns((current) => current.map((turn) => (turn.key === key ? { ...turn, ...patch } : turn)));

  const begin = (text: string): string => {
    const key = nextKey();
    setTurns((current) => [...current, { key, question: text, live: "", pending: true }]);
    setQuestion("");
    setError(null);
    return key;
  };

  const ask = useMutation({
    mutationFn: (vars: { key: string; text: string }) =>
      call(api.POST("/api/v1/assistant/ask", { body: { question: vars.text, language, mode } })),
    onSuccess: async (data, vars) => {
      update(vars.key, { pending: false, data, exchangeId: data.exchange_id });
      await client.invalidateQueries({ queryKey: ["exchanges"] });
    },
    onError: (reason, vars) => {
      update(vars.key, { pending: false });
      setError(failureText(reason));
    },
  });

  const stream = async (text: string) => {
    const key = begin(text);
    try {
      await readSse(
        "/api/v1/assistant/ask/stream",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: text, language, mode }) },
        (event, data) => {
          if (event === "answer_chunk" && data && typeof data === "object" && "text" in data) {
            const chunk = String((data as { text: string }).text);
            setTurns((current) => current.map((turn) => (turn.key === key ? { ...turn, live: turn.live + chunk } : turn)));
          }
          if (event === "done" && data && typeof data === "object" && "exchange_id" in data) {
            update(key, { exchangeId: String((data as { exchange_id: string }).exchange_id) });
          }
        },
      );
      await client.invalidateQueries({ queryKey: ["exchanges"] });
    } catch (reason) {
      setError(failureText(reason));
    } finally {
      update(key, { pending: false });
    }
  };

  const busy = ask.isPending || turns.some((turn) => turn.pending);
  const send = () => {
    const text = question.trim();
    if (canAsk && text && !busy) void stream(text);
  };
  const sendWithoutStream = () => {
    const text = question.trim();
    if (canAsk && text && !busy) ask.mutate({ key: begin(text), text });
  };
  const newChat = () => {
    setTurns([]);
    setQuestion("");
    setError(null);
  };
  const openPast = (item: Past) => {
    setTurns([{ key: nextKey(), question: item.question, exchangeId: item.exchange_id, live: "", pending: false, data: item }]);
    setError(null);
  };

  const lastLive = turns.at(-1)?.live.length ?? 0;
  useEffect(() => {
    if (turns.length) bottom.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [turns.length, lastLive]);

  const openId = turns.length === 1 ? turns[0].exchangeId : undefined;
  const countLabel =
    turns.length === 0
      ? tr("Новий чат", "New chat")
      : tr(`Запитань у цьому чаті: ${turns.length}`, `${turns.length} ${turns.length === 1 ? "question" : "questions"} in this chat`);

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
          <div className="flex items-center justify-between gap-3 border-b border-[var(--glass-border)] px-5 py-3">
            <span className="text-sm text-muted">{countLabel}</span>
            <Button size="sm" variant="secondary" onPress={newChat} isDisabled={busy || turns.length === 0}>
              <MessageSquarePlus size={16} /> {tr("Новий чат", "New chat")}
            </Button>
          </div>
          <div className="max-h-[70vh] flex-1 space-y-6 overflow-y-auto p-5 md:p-6">
            {turns.length === 0 ? (
              <EmptyState
                icon={<Sparkles size={28} />}
                title={tr("З чого почнемо розслідування?", "Where shall we start?")}
                text={tr("Спробуй одне з запитань нижче або напиши своє.", "Try one of the questions below or write your own.")}
                action={
                  <div className="flex flex-wrap justify-center gap-2">
                    {SUGGESTIONS.map(([uk, en]) => (
                      <button
                        key={en}
                        type="button"
                        className="rounded-full border border-[var(--glass-border)] px-3 py-1.5 text-sm text-foreground hover:bg-default disabled:opacity-50"
                        disabled={!canAsk}
                        onClick={() => setQuestion(tr(uk, en))}
                      >
                        {tr(uk, en)}
                      </button>
                    ))}
                  </div>
                }
              />
            ) : (
              turns.map((turn) => <TurnView key={turn.key} turn={turn} canFetch={canAsk} tr={tr} />)
            )}
            <div ref={bottom} />
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
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    send();
                  }
                }}
                placeholder={turns.length ? tr("Наступне запитання…", "Next question…") : tr("Чи висихає південь України влітку?", "Is southern Ukraine drying in summer?")}
                disabled={!canAsk}
              />
              <div className="flex flex-col gap-2">
                <Button variant="primary" onPress={send} isDisabled={!canAsk || !question.trim() || busy} aria-label={tr("Надіслати", "Send")}>
                  <Send size={16} /> {tr("Надіслати", "Send")}
                </Button>
                <Button size="sm" variant="ghost" onPress={sendWithoutStream} isDisabled={!canAsk || !question.trim() || busy}>
                  {tr("Без стріму", "No stream")}
                </Button>
              </div>
            </div>
          </div>
        </Panel>

        <Panel className="h-fit">
          <div className="flex items-start justify-between gap-2">
            <SectionTitle icon={<History size={18} />}>{tr("Історія", "History")}</SectionTitle>
            <Button size="sm" variant="ghost" isIconOnly onPress={newChat} isDisabled={busy || turns.length === 0} aria-label={tr("Новий чат", "New chat")}>
              <MessageSquarePlus size={16} />
            </Button>
          </div>
          {(history.data?.exchanges ?? []).length > 0 ? (
            <ul className="flex flex-col gap-1">
              {(history.data?.exchanges ?? []).map((item) => (
                <li key={item.exchange_id}>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => openPast(item)}
                    className={`w-full rounded-lg px-3 py-2 text-left text-sm transition-colors ${openId === item.exchange_id ? "bg-accent-soft text-foreground" : "text-muted hover:bg-default hover:text-foreground"}`}
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

function TurnView({ turn, canFetch, tr }: { turn: Turn; canFetch: boolean; tr: Translate }) {
  const fetched = useQuery({
    queryKey: ["exchange", turn.exchangeId],
    enabled: Boolean(canFetch && turn.exchangeId && !turn.data && !turn.pending),
    queryFn: () => call(api.GET("/api/v1/assistant/exchanges/{exchange_id}", { params: { path: { exchange_id: turn.exchangeId ?? "" } } })),
  });
  const shown: Answer | undefined = turn.data ?? fetched.data;
  const text = turn.live || shown?.answer;

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <p className="bg-gradient-brand max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-md px-4 py-3 text-white">{turn.question}</p>
      </div>
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
      {(text || turn.pending || fetched.isFetching) && (
        <div className="flex gap-3">
          <span className="bg-gradient-brand flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-white"><Bot size={16} /></span>
          <div className="max-w-[85%] rounded-2xl rounded-tl-md border border-[var(--glass-border)] bg-surface/60 px-4 py-3">
            <p className="whitespace-pre-wrap leading-relaxed text-foreground">
              {text || <span className="animate-pulse text-muted">{tr("Думаю…", "Thinking…")}</span>}
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
      {!text && !turn.pending && !fetched.isFetching && (
        <p className="pl-11 text-sm text-muted">{tr("Відповіді немає — спробуй ще раз.", "No answer — try again.")}</p>
      )}
    </div>
  );
}
