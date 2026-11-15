import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@heroui/react";
import { KeyRound, LogOut, UserRound } from "lucide-react";
import { api } from "../api/client";
import { call, failureText } from "../api/http";
import { adoptToken } from "../api/session";
import { Chip, Field, Input, Notice, Panel, Segmented } from "../components/ui";
import { useTr } from "../i18n";
import { useStore } from "../store/useStore";

export function Session() {
  const token = useStore((state) => state.token);
  const userId = useStore((state) => state.userId);
  const role = useStore((state) => state.role);
  const clearSession = useStore((state) => state.clearSession);
  const tr = useTr();
  const signedIn = Boolean(token) && role !== "guest";
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const guest = useMutation({
    mutationFn: async () => adoptToken((await call(api.POST("/api/v1/session/guest"))).token),
    onSuccess: () => setError(null),
    onError: (reason) => setError(failureText(reason)),
  });
  const submit = useMutation({
    mutationFn: async () => {
      const created =
        mode === "login"
          ? await call(api.POST("/api/v1/session", { body: { username, password } }))
          : await call(api.POST("/api/v1/session/register", { body: { username, password } }));
      return adoptToken(created.token);
    },
    onSuccess: () => {
      setError(null);
      setPassword("");
    },
    onError: (reason) => setError(failureText(reason)),
  });

  return (
    <div className="mx-auto flex w-full max-w-md flex-col px-4 py-16">
      <div className="mb-8 text-center">
        <div className="bg-gradient-brand mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl text-white shadow-lg shadow-brand-from/30">
          <KeyRound size={26} />
        </div>
        <h1 className="text-3xl font-bold tracking-tight text-foreground">{signedIn ? tr("Ти в системі", "You are signed in") : tr("Вхід детектива", "Detective sign-in")}</h1>
        <p className="mt-2 text-muted">
          {tr("Гість бачить демо, словник, вікторини і радар. Увійди, щоб вести журнал, приєднуватися до класу і питати асистента.", "A guest sees demos, the glossary, quizzes and the radar. Sign in to keep a journal, join a class and ask the assistant.")}
        </p>
      </div>

      {signedIn ? (
        <Panel className="flex flex-col gap-4">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-full bg-default text-foreground"><UserRound size={20} /></span>
            <div>
              <p className="font-semibold text-foreground">{userId}</p>
              <Chip tone="success">{role}</Chip>
            </div>
          </div>
          <Button variant="secondary" onClick={clearSession}>
            <LogOut size={16} /> {tr("Вийти (залишишся гостем)", "Sign out (you stay a guest)")}
          </Button>
        </Panel>
      ) : (
        <Panel className="flex flex-col gap-5">
          <Segmented<"login" | "register">
            className="w-full justify-center"
            value={mode}
            onChange={setMode}
            options={[
              { value: "login", label: tr("Увійти", "Sign in") },
              { value: "register", label: tr("Реєстрація", "Register") },
            ]}
          />
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (username && password) submit.mutate();
            }}
          >
            <Field label={tr("Ім’я користувача", "Username")}>
              <Input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} />
            </Field>
            <Field label={tr("Пароль", "Password")}>
              <Input type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} />
            </Field>
            <Notice text={error} />
            <Button type="submit" variant="primary" isDisabled={!username || !password || submit.isPending}>
              {mode === "login" ? tr("Увійти", "Sign in") : tr("Створити акаунт", "Create account")}
            </Button>
          </form>
          <div className="flex items-center gap-3 text-xs text-muted">
            <span className="h-px flex-1 bg-[var(--glass-border)]" />
            {tr("або", "or")}
            <span className="h-px flex-1 bg-[var(--glass-border)]" />
          </div>
          <Button variant="ghost" onClick={() => guest.mutate()} isDisabled={guest.isPending || role === "guest"}>
            {role === "guest" ? tr("Ти зараз гість", "You are a guest now") : tr("Продовжити як гість", "Continue as guest")}
          </Button>
        </Panel>
      )}
    </div>
  );
}
