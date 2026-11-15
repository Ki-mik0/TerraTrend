import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { ApiFailure, call } from "../api/http";
import { REFRESH_AHEAD, needsRefresh, refreshSession, tokenExpiry } from "../api/refresh";
import { adoptToken } from "../api/session";
import { useStore } from "../store/useStore";

/**
 * Keeps the stored session valid. Without a session the visitor gets a guest one, because demos,
 * the glossary, quizzes and the radar are open to guests but every API call still needs a token.
 * A token lives an hour: it is renewed a couple of minutes before it runs out, when the tab comes
 * back into view, and (in the API client) after any 401. If the server no longer knows the user,
 * the session is dropped and a guest one takes its place.
 */
export function SessionSync() {
  const token = useStore((state) => state.token);
  const setSession = useStore((state) => state.setSession);
  const clearSession = useStore((state) => state.clearSession);
  const creatingGuest = useRef(false);
  const [attempt, setAttempt] = useState(0);

  // The API may still be starting (the dev proxy answers 502), so a failed guest session is retried.
  useEffect(() => {
    if (token || creatingGuest.current) return;
    creatingGuest.current = true;
    let retry: number | undefined;
    call(api.POST("/api/v1/session/guest"))
      .then((created) => adoptToken(created.token))
      .catch(() => {
        retry = window.setTimeout(() => setAttempt((value) => value + 1), 3000);
      })
      .finally(() => {
        creatingGuest.current = false;
      });
    return () => window.clearTimeout(retry);
  }, [token, attempt]);

  // Renew ahead of expiry. A failed renewal (API down) is tried again a little later.
  useEffect(() => {
    if (!token) return;
    const exp = tokenExpiry(token);
    let timer: number | undefined;
    const renew = () => {
      refreshSession().catch(() => {
        timer = window.setTimeout(renew, 30_000);
      });
    };
    if (exp === null) renew();
    else timer = window.setTimeout(renew, Math.max(0, (exp - REFRESH_AHEAD) * 1000 - Date.now()));
    // Timers stall while a laptop sleeps, so check again whenever the tab is shown.
    const onVisible = () => {
      if (document.visibilityState === "visible" && needsRefresh(useStore.getState().token)) renew();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
  }, [token]);

  // Who the token belongs to. The client has already tried a refresh on 401, so a 401 here is final;
  // a network error keeps the session for the next try.
  const userId = useStore((state) => state.userId);
  useQuery({
    queryKey: ["session", userId],
    enabled: Boolean(token),
    retry: false,
    queryFn: async () => {
      try {
        const me = await call(api.GET("/api/v1/session"));
        const current = useStore.getState().token;
        if (current) setSession({ token: current, userId: me.user_id, role: me.role });
        return me;
      } catch (error) {
        if (error instanceof ApiFailure && error.status === 401) clearSession();
        throw error;
      }
    },
  });

  return null;
}
