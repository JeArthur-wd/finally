"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { fmtPrice, fmtQty } from "@/lib/format";
import type { ChatAction, ChatMessage } from "@/lib/types";

type Props = {
  open: boolean;
  onToggle: () => void;
  /** Called after a response that carried actions (refresh portfolio/watchlist). */
  onActions: (actions: ChatAction[]) => void;
};

export const GREETING =
  "Hi, I'm FinAlly, your AI trading assistant. Ask me about your portfolio, or tell me to buy, sell or watch a ticker.";

export function actionLabel(a: ChatAction): string {
  if (a.type === "trade") {
    const verb = a.status === "executed" ? (a.side === "buy" ? "Bought" : "Sold") : a.side === "buy" ? "Buy" : "Sell";
    const at = a.status === "executed" && a.price != null ? ` @ ${fmtPrice(a.price)}` : "";
    return `${verb} ${fmtQty(a.quantity)} ${a.ticker}${at}`;
  }
  const verb = a.action === "add" ? (a.status === "executed" ? "Added" : "Add") : a.status === "executed" ? "Removed" : "Remove";
  return `${verb} ${a.ticker} ${a.action === "add" ? "to" : "from"} watchlist`;
}

export function ActionChip({ action }: { action: ChatAction }) {
  const ok = action.status === "executed";
  return (
    <li
      data-testid="chat-action"
      data-status={action.status}
      className={`num rounded-[3px] border px-2 py-1 text-[11px] leading-snug ${
        ok ? "border-up/40 bg-up/10 text-up" : "border-down/40 bg-down/10 text-down"
      }`}
    >
      <span className="mr-1">{ok ? "✓" : "✕"}</span>
      {actionLabel(action)}
      {!ok && action.error && <span className="block font-sans text-down/90">{action.error}</span>}
    </li>
  );
}

export function MessageBubble({ msg }: { msg: ChatMessage }) {
  const user = msg.role === "user";
  return (
    <div data-testid="chat-message" data-role={msg.role} className={`flex flex-col gap-1.5 ${user ? "items-end" : "items-start"}`}>
      <div
        className={`max-w-[92%] whitespace-pre-wrap rounded-[4px] px-3 py-2 text-[12.5px] leading-relaxed ${
          user ? "bg-blue/15 text-text ring-1 ring-blue/30" : "bg-panel-2 text-text ring-1 ring-border-soft"
        }`}
      >
        {msg.content}
      </div>
      {msg.actions && msg.actions.length > 0 && (
        <ul className="flex max-w-[92%] flex-wrap gap-1.5">
          {msg.actions.map((a, i) => (
            <ActionChip key={i} action={a} />
          ))}
        </ul>
      )}
    </div>
  );
}

let localId = 0;
const localMessage = (role: ChatMessage["role"], content: string): ChatMessage => ({
  id: `local-${++localId}`,
  role,
  content,
  actions: null,
  created_at: new Date().toISOString(),
});

export function ChatPanel({ open, onToggle, onActions }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .chatHistory()
      .then((h) => {
        if (!cancelled && Array.isArray(h)) setMessages((cur) => (cur.length ? cur : h));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, loading, open]);

  const send = async (e?: FormEvent) => {
    e?.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setMessages((m) => [...m, localMessage("user", text)]);
    setLoading(true);
    try {
      const res = await api.chat(text);
      setMessages((m) => [...m, res.message]);
      if (res.actions?.length) onActions(res.actions);
    } catch (err) {
      const why = err instanceof Error ? err.message : "unknown error";
      setMessages((m) => [...m, localMessage("assistant", `Sorry — I couldn't reach the server (${why}). Please try again.`)]);
    } finally {
      setLoading(false);
    }
  };

  if (!open) {
    return (
      <aside data-testid="chat-panel" data-open="false" className="flex w-10 shrink-0 flex-col items-center border-l border-border bg-panel py-3">
        <button
          type="button"
          onClick={onToggle}
          aria-label="Open AI chat"
          className="flex flex-col items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-accent hover:text-text"
        >
          <span aria-hidden>‹</span>
          <span className="[writing-mode:vertical-rl]">FinAlly AI</span>
        </button>
      </aside>
    );
  }

  return (
    <aside
      data-testid="chat-panel"
      data-open="true"
      className="flex w-[340px] shrink-0 flex-col border-l border-border bg-panel xl:w-[380px]"
    >
      <header className="flex h-10 shrink-0 items-center justify-between border-b border-border-soft px-3">
        <div className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-accent shadow-[0_0_6px_#ecad0a]" aria-hidden />
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.09em] text-muted">FinAlly AI</h2>
        </div>
        <button
          type="button"
          onClick={onToggle}
          aria-label="Collapse AI chat"
          className="rounded-[3px] px-1.5 text-[14px] text-faint hover:bg-panel-2 hover:text-text"
        >
          ›
        </button>
      </header>

      <div ref={scroller} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {messages.length === 0 && (
          <div data-testid="chat-greeting" className="rounded-[4px] bg-panel-2 px-3 py-2.5 text-[12.5px] leading-relaxed text-muted ring-1 ring-border-soft">
            {GREETING}
            <div className="mt-2 flex flex-wrap gap-1.5">
              {["How is my portfolio doing?", "buy 5 AAPL", "add PYPL"].map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setInput(s)}
                  className="rounded-[3px] border border-border px-2 py-0.5 text-[11px] text-muted hover:border-blue hover:text-blue"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.id} msg={m} />
        ))}
        {loading && (
          <div data-testid="chat-loading" className="flex items-center gap-1.5 px-1 text-[11px] text-muted" aria-live="polite">
            <span className="flex gap-1" aria-hidden>
              <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-accent" />
              <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-accent [animation-delay:200ms]" />
              <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-accent [animation-delay:400ms]" />
            </span>
            FinAlly is thinking…
          </div>
        )}
      </div>

      <form onSubmit={send} className="shrink-0 border-t border-border-soft p-2.5">
        <div className="flex gap-1.5">
          <input
            data-testid="chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask FinAlly or say “buy 10 NVDA”…"
            autoComplete="off"
            className="min-w-0 flex-1 rounded-[3px] border border-border bg-bg px-2.5 py-2 text-[12.5px] text-text placeholder:text-faint focus:border-blue focus:outline-none"
          />
          <button
            type="submit"
            data-testid="chat-send"
            disabled={loading || !input.trim()}
            className="rounded-[3px] bg-purple px-3.5 text-[12px] font-semibold text-white transition hover:bg-purple-hi disabled:opacity-40"
          >
            Send
          </button>
        </div>
      </form>
    </aside>
  );
}
