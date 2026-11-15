import { api } from "./client";
import { call } from "./http";
import { useStore } from "../store/useStore";

export async function adoptToken(token: string) {
  useStore.getState().setSession({ token, userId: "", role: "" });
  const me = await call(api.GET("/api/v1/session"));
  useStore.getState().setSession({ token, userId: me.user_id, role: me.role });
  return me;
}
