import type { ChatEvent, HistoryTurn, Suggestions } from "./chat-types";

// Same base URL the dashboards use, so one env var configures both.
const BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

export async function fetchSuggestions(): Promise<Suggestions> {
  const res = await fetch(`${BASE}/api/chat/suggestions`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json() as Promise<Suggestions>;
}

/**
 * POST a question and read the answer as it streams (server-sent events).
 * EventSource cannot POST, so this reads the response body directly.
 * Resolves when the stream ends; rejects with a user-readable Error.
 */
export async function streamChat(
  question: string,
  history: HistoryTurn[],
  onEvent: (e: ChatEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ question, history }),
      signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new Error("I can't reach the server right now. Please check that the backend is running.");
  }
  if (res.status === 429) {
    throw new Error("Too many questions in a short time. Please wait a moment and try again.");
  }
  if (!res.ok || !res.body) {
    throw new Error(`The server returned an error (${res.status}). Please try again.`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const flush = (frame: string) => {
    let event = "message";
    const data: string[] = [];
    for (const line of frame.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (!data.length) return;                       // comment / keep-alive frame
    onEvent({ event, data: JSON.parse(data.join("\n")) } as ChatEvent);
  };

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      flush(buffer.slice(0, idx));
      buffer = buffer.slice(idx + 2);
    }
  }
  if (buffer.trim()) flush(buffer);
}
