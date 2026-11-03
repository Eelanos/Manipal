"use client";

import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchSuggestions, streamChat } from "@/lib/chat-api";
import type {
  AssistantMessage, ChatEvent, ChatMessage, HistoryTurn, Suggestions,
} from "@/lib/chat-types";
import {
  ChatIcon, MinimizeIcon, PlusIcon, SendIcon, SparkIcon, StopIcon,
} from "./icons";
import MessageView from "./MessageView";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const monthYear = (iso: string) => {
  const [y, m] = iso.split("-").map(Number);
  return `${MONTHS[m - 1]} ${y}`;
};

/**
 * "Ask QBER": a floating button (bottom-right) and the sidebar's Ask QBER item open the chat.
 * The chat fills the whole page area to the right of the sidebar (the sidebar stays usable),
 * so charts and tables have room. Closing keeps the conversation.
 * It lives in app/layout.tsx, so the conversation survives moving between dashboards.
 */
export default function ChatDock() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [meta, setMeta] = useState<Suggestions | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const idRef = useRef(0);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const patch = useCallback((id: number, fn: (m: AssistantMessage) => AssistantMessage) => {
    setMessages((all) => all.map((m) => (m.role === "assistant" && m.id === id ? fn(m) : m)));
  }, []);

  // Only the data range in the header is needed from this call now.
  const metaRequested = useRef(false);
  const openDock = useCallback(() => {
    setOpen(true);                       // idempotent: opening an open panel is a no-op
    if (!metaRequested.current) {
      metaRequested.current = true;
      fetchSuggestions().then(setMeta).catch(() => { metaRequested.current = false; });
    }
    setTimeout(() => inputRef.current?.focus(), 50);
  }, []);

  // The sidebar's "Ask QBER" button opens the panel via this window event. The listener is
  // registered once (stable handler), so no click can ever land in a re-subscribe gap.
  useEffect(() => {
    window.addEventListener("qber:open-chat", openDock);
    return () => window.removeEventListener("qber:open-chat", openDock);
  }, [openDock]);

  // The sidebar tells the chat to close when any page is chosen (also the page already underneath,
  // where the route - and so the effect below - does not change).
  useEffect(() => {
    const onClose = () => setOpen(false);
    window.addEventListener("qber:close-chat", onClose);
    return () => window.removeEventListener("qber:close-chat", onClose);
  }, []);

  // Tell the sidebar whether the chat is open, so it highlights the right item.
  useEffect(() => {
    window.dispatchEvent(new CustomEvent("qber:chat-state", { detail: { open } }));
  }, [open]);

  // Picking another page in the sidebar leaves the chat, so the chat never sits over the page
  // the user just chose. (Compared with the previous path so it does not fire on first render.)
  const lastPath = useRef(pathname);
  useEffect(() => {
    if (lastPath.current !== pathname) {
      lastPath.current = pathname;
      setOpen(false);
    }
  }, [pathname]);

  // Esc closes the panel.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      // Esc belongs to an open dialog (drill-down, save-to-workspace) first.
      if (e.key === "Escape" && !document.querySelector('[aria-modal="true"]')) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const scrollDown = () =>
    setTimeout(() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }), 30);

  const ask = useCallback(async (raw: string) => {
    const question = raw.trim();
    if (!question || busy) return;

    // Earlier completed turns become the model's memory ("and for Goa?").
    const history: HistoryTurn[] = messages
      .filter((m): m is AssistantMessage => m.role === "assistant" && m.status === "done" && m.blocks.length > 0)
      .slice(-6)
      .map((m) => ({
        question: m.question,
        specs: m.blocks.map((b) => b.spec),
        answer: m.narrative?.headline ?? "",
      }));

    const aid = ++idRef.current;
    const uid = ++idRef.current;
    setMessages((all) => [
      ...all,
      { id: uid, role: "user", text: question },
      { id: aid, role: "assistant", question, status: "working", stage: "Understanding your question…",
        blocks: [], narrative: null, notice: null },
    ]);
    setInput("");
    setBusy(true);
    scrollDown();

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const onEvent = (e: ChatEvent) => {
      switch (e.event) {
        case "status": patch(aid, (m) => ({ ...m, stage: e.data.text })); break;
        case "result": patch(aid, (m) => ({ ...m, blocks: [...m.blocks, e.data.block] })); break;
        case "narrative": patch(aid, (m) => ({ ...m, narrative: e.data })); break;
        case "message": patch(aid, (m) => ({ ...m, notice: { kind: e.data.kind, text: e.data.text } })); break;
        case "error": patch(aid, (m) => ({ ...m, notice: { kind: "error", text: e.data.text } })); break;
        case "done": patch(aid, (m) => ({ ...m, status: "done" })); break;
      }
    };
    try {
      await streamChat(question, history, onEvent, ctrl.signal);
      patch(aid, (m) => ({ ...m, status: "done" }));          // stream ended without a "done"
    } catch (err) {
      const aborted = (err as Error).name === "AbortError";
      patch(aid, (m) => ({
        ...m, status: "done",
        notice: m.notice ?? { kind: aborted ? "chat" : "error", text: aborted ? "Stopped." : (err as Error).message },
      }));
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  }, [busy, messages, patch]);

  const clear = () => { abortRef.current?.abort(); setMessages([]); setBusy(false); };

  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
  const dataRange = meta?.data ? `${monthYear(meta.data.from)} – ${monthYear(meta.data.to)}` : null;

  return (
    <>
      {/* Floating button. Takes no layout space; hidden while the panel is open. */}
      <button
        type="button"
        onClick={openDock}
        aria-label="Open Ask QBER"
        className={`group fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-brand to-brand-dark text-white shadow-lg shadow-red-900/30 ring-4 ring-white/70 transition duration-200 hover:scale-105 hover:shadow-xl ${open ? "pointer-events-none scale-50 opacity-0" : "scale-100 opacity-100"}`}
      >
        <ChatIcon size={24} />
        <span className="pointer-events-none absolute right-16 whitespace-nowrap rounded-lg bg-slate-900 px-2.5 py-1 text-xs font-medium text-white opacity-0 shadow transition group-hover:opacity-100">
          Ask QBER
        </span>
      </button>

      {/* The chat page. Covers everything right of the sidebar (left-64 = the sidebar's w-64 in
          Sidebar.tsx), so the dashboard behind it is not visible. Stays mounted so the conversation
          and scroll position survive closing. No transform on this element: a transformed parent
          would trap the position:fixed drill-down / save dialogs inside it. */}
      <section
        role="dialog"
        aria-label="Ask QBER"
        aria-hidden={!open}
        inert={!open}
        className={`fixed inset-y-0 right-0 left-64 z-50 flex flex-col overflow-hidden bg-canvas transition-opacity duration-200 max-sm:left-0
          ${open ? "opacity-100" : "pointer-events-none opacity-0"}`}
      >
        <header className="flex items-center gap-3 bg-gradient-to-r from-brand to-brand-dark px-6 py-3 text-white">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/15 ring-1 ring-white/25">
            <SparkIcon size={18} />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold leading-tight">Ask QBER</h2>
            <p className="truncate text-[11px] text-red-100">
              {dataRange ? `Data: ${dataRange}` : "Pharmacy & inventory data"}
            </p>
          </div>
          <div className="flex items-center gap-0.5">
            {messages.length > 0 && (
              <HeaderButton label="New chat" onClick={clear}><PlusIcon /></HeaderButton>
            )}
            <HeaderButton label="Close Ask QBER" onClick={() => setOpen(false)}><MinimizeIcon /></HeaderButton>
          </div>
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto overflow-x-hidden px-6 py-6">
          <div className="@container mx-auto w-full max-w-6xl space-y-5">
          {messages.length === 0 && (
            <div className="space-y-5">
              <div className="rounded-2xl rounded-tl-md border border-slate-200 bg-white p-4 shadow-sm">
                <p className="text-[15px] font-medium text-slate-900">Hi! What would you like to know?</p>
                <p className="mt-1 text-[13px] leading-relaxed text-slate-500">
                  Ask about consumption, formulary and SOB compliance, stock, purchases or budgets. I&apos;ll answer
                  with a summary, charts and a table you can export.
                </p>
              </div>
            </div>
          )}

          {messages.map((m) =>
            m.role === "user" ? (
              <div key={m.id} className="flex justify-end">
                <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-nav px-3.5 py-2 text-sm leading-relaxed text-white shadow-sm">{m.text}</p>
              </div>
            ) : (
              <MessageView key={m.id} message={m} onAsk={ask} isLast={m.id === lastAssistant?.id} />
            ),
          )}
          </div>
        </div>

        <footer className="border-t border-slate-200 bg-white px-6 py-3">
          <form
            onSubmit={(e) => { e.preventDefault(); ask(input); }}
            className="mx-auto flex max-w-6xl items-end gap-2 rounded-2xl border border-slate-300 bg-white py-1.5 pl-3.5 pr-1.5 transition focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/20"
          >
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input); }
              }}
              rows={Math.min(4, Math.max(1, input.split("\n").length))}
              maxLength={600}
              placeholder="Ask about the data…"
              className="max-h-28 flex-1 resize-none bg-transparent py-1.5 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none"
            />
            {busy ? (
              <button type="button" onClick={() => abortRef.current?.abort()} aria-label="Stop"
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-nav text-white hover:bg-nav-dark">
                <StopIcon />
              </button>
            ) : (
              <button type="submit" disabled={!input.trim()} aria-label="Send"
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand text-white transition hover:bg-brand-dark disabled:bg-slate-200 disabled:text-slate-400">
                <SendIcon />
              </button>
            )}
          </form>
          <p className="mx-auto mt-2 max-w-6xl px-1 text-[10px] leading-snug text-slate-400">
            Numbers are calculated directly from the dataset; AI only interprets your question and writes the summary.
          </p>
        </footer>
      </section>
    </>
  );
}

function HeaderButton({ label, onClick, children, hideOnMobile }: {
  label: string; onClick: () => void; children: React.ReactNode; hideOnMobile?: boolean;
}) {
  return (
    <button type="button" onClick={onClick} aria-label={label} title={label}
            className={`flex h-8 w-8 items-center justify-center rounded-lg text-red-50 transition hover:bg-white/15 ${hideOnMobile ? "max-sm:hidden" : ""}`}>
      {children}
    </button>
  );
}
