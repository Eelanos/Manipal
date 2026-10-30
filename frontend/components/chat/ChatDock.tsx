"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchSuggestions, streamChat } from "@/lib/chat-api";
import type {
  AssistantMessage, ChatEvent, ChatMessage, HistoryTurn, Suggestions,
} from "@/lib/chat-types";
import {
  ArrowIcon, ChatIcon, CompressIcon, ExpandIcon, MinimizeIcon, PlusIcon, SendIcon, SparkIcon, StopIcon,
} from "./icons";
import MessageView from "./MessageView";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const monthYear = (iso: string) => {
  const [y, m] = iso.split("-").map(Number);
  return `${MONTHS[m - 1]} ${y}`;
};

/**
 * "Ask Manipal": a floating button (bottom-right) that opens a floating chat card.
 * Minimising keeps the conversation; expanding gives charts and tables room to breathe.
 * It lives in app/layout.tsx, so the conversation survives moving between dashboards.
 */
export default function ChatDock() {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
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

  const openDock = () => {
    setOpen(true);
    if (!meta) fetchSuggestions().then(setMeta).catch(() => setMeta({ suggestions: [] }));
    setTimeout(() => inputRef.current?.focus(), 220);
  };

  // The sidebar's "Ask QBER" button opens the panel via this window event.
  useEffect(() => {
    const onOpen = () => openDock();
    window.addEventListener("qber:open-chat", onOpen);
    return () => window.removeEventListener("qber:open-chat", onOpen);
  });

  // Esc minimises the panel.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
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
  const size = expanded
    ? "sm:w-[min(1000px,calc(100vw-3rem))] sm:h-[calc(100vh-3rem)]"
    : "sm:w-[430px] sm:h-[min(700px,calc(100vh-3rem))]";

  return (
    <>
      {/* Floating button. Takes no layout space; hidden while the panel is open. */}
      <button
        type="button"
        onClick={openDock}
        aria-label="Open Ask Manipal"
        className={`group fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-brand to-brand-dark text-white shadow-lg shadow-red-900/30 ring-4 ring-white/70 transition duration-200 hover:scale-105 hover:shadow-xl ${open ? "pointer-events-none scale-50 opacity-0" : "scale-100 opacity-100"}`}
      >
        <ChatIcon size={24} />
        <span className="pointer-events-none absolute right-16 whitespace-nowrap rounded-lg bg-slate-900 px-2.5 py-1 text-xs font-medium text-white opacity-0 shadow transition group-hover:opacity-100">
          Ask Manipal
        </span>
      </button>

      {/* Floating panel. Stays mounted so the conversation and scroll position survive minimising. */}
      <section
        role="dialog"
        aria-label="Ask Manipal"
        aria-hidden={!open}
        inert={!open}
        className={`fixed z-50 flex origin-bottom-right flex-col overflow-hidden border border-slate-200 bg-canvas shadow-2xl shadow-slate-900/25 transition duration-200
          max-sm:inset-0 sm:bottom-6 sm:right-6 sm:rounded-2xl ${size}
          ${open ? "translate-y-0 scale-100 opacity-100" : "pointer-events-none translate-y-3 scale-95 opacity-0"}`}
      >
        <header className="flex items-center gap-3 bg-gradient-to-r from-brand to-brand-dark px-4 py-3 text-white">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/15 ring-1 ring-white/25">
            <SparkIcon size={18} />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold leading-tight">Ask Manipal</h2>
            <p className="truncate text-[11px] text-red-100">
              {dataRange ? `Data: ${dataRange}` : "Pharmacy & inventory data"}
            </p>
          </div>
          <div className="flex items-center gap-0.5">
            {messages.length > 0 && (
              <HeaderButton label="New chat" onClick={clear}><PlusIcon /></HeaderButton>
            )}
            <HeaderButton label={expanded ? "Smaller" : "Larger"} onClick={() => setExpanded(!expanded)} hideOnMobile>
              {expanded ? <CompressIcon /> : <ExpandIcon />}
            </HeaderButton>
            <HeaderButton label="Minimise" onClick={() => setOpen(false)}><MinimizeIcon /></HeaderButton>
          </div>
        </header>

        <div ref={scrollRef} className="@container flex-1 space-y-5 overflow-y-auto overflow-x-hidden px-4 py-5">
          {messages.length === 0 && (
            <div className="space-y-5">
              <div className="rounded-2xl rounded-tl-md border border-slate-200 bg-white p-4 shadow-sm">
                <p className="text-[15px] font-medium text-slate-900">Hi! What would you like to know?</p>
                <p className="mt-1 text-[13px] leading-relaxed text-slate-500">
                  Ask about consumption, formulary and SOB compliance, stock, purchases or budgets. I&apos;ll answer
                  with a summary, charts and a table you can export.
                </p>
              </div>
              {(meta?.suggestions?.length ?? 0) > 0 && (
                <div>
                  <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Try asking</p>
                  <div className="grid grid-cols-1 gap-2 @2xl:grid-cols-2">
                    {meta!.suggestions.map((s) => (
                      <button key={s} type="button" onClick={() => ask(s)}
                              className="group flex items-center justify-between gap-2 rounded-xl bg-white px-3.5 py-2.5 text-left text-[13px] text-slate-700 shadow-sm ring-1 ring-slate-200 transition hover:text-brand hover:ring-brand/40">
                        {s}
                        <span className="text-slate-300 transition group-hover:text-brand"><ArrowIcon /></span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
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

        <footer className="border-t border-slate-200 bg-white p-3">
          <form
            onSubmit={(e) => { e.preventDefault(); ask(input); }}
            className="flex items-end gap-2 rounded-2xl border border-slate-300 bg-white py-1.5 pl-3.5 pr-1.5 transition focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/20"
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
          <p className="mt-2 px-1 text-[10px] leading-snug text-slate-400">
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
