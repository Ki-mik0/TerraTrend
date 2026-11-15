import { authFetch } from "./refresh";

/** Read a server-sent stream. Fetch is used so the bearer token can be sent. */
export async function readSse(
  path: string,
  init: RequestInit,
  onEvent: (event: string, data: unknown) => void,
): Promise<void> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "text/event-stream");
  const response = await authFetch(path, { ...init, headers });
  if (!response.ok || !response.body) {
    throw new Error(`Stream failed (${response.status})`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      let event = "message";
      const dataLines: string[] = [];
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length === 0) continue;
      const raw = dataLines.join("\n");
      try {
        onEvent(event, JSON.parse(raw));
      } catch {
        onEvent(event, raw);
      }
    }
  }
}

/** The file name a server put in Content-Disposition, if any. */
function dispositionName(header: string | null): string | null {
  if (!header) return null;
  const encoded = /filename*=UTF-8''([^;]+)/i.exec(header);
  if (encoded) return decodeURIComponent(encoded[1]);
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1] : null;
}

/** Download a protected file with the bearer token. The server's file name wins over `filename`. */
export async function downloadFile(path: string, filename: string): Promise<string> {
  const response = await authFetch(path);
  if (!response.ok) throw new Error(`Download failed (${response.status})`);
  const name = dispositionName(response.headers.get("Content-Disposition")) ?? filename;
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return name;
}
