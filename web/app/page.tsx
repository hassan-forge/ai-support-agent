"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import { api, type ChatResult } from "@/lib/api";

type Message =
  | { role: "customer"; text: string }
  | { role: "agent"; result: ChatResult };

const SUGGESTIONS = [
  "How long does shipping take?",
  "Where is my order ORD-1042?",
  "Please refund ORD-1044, the chair broke",
  "Do you sell gift cards?",
];

const STATUS_LABEL: Record<string, string> = {
  done: "done",
  pending_approval: "waiting for a person",
  failed: "failed",
};

function AgentMessage({ result }: { result: ChatResult }) {
  return (
    <div className="bubble agent">
      <p>{result.answer}</p>
      {result.actions.length > 0 && (
        <div className="chips">
          {result.actions.map((a, i) => (
            <span key={i} className={`chip ${a.status}`} title={a.detail ?? ""}>
              {a.tool} · {STATUS_LABEL[a.status] ?? a.status}
            </span>
          ))}
        </div>
      )}
      {result.citations.length > 0 && (
        <ol className="citations">
          {result.citations.map((c) => (
            <li key={c.n} value={c.n}>
              {c.title} <span className="muted">({c.source})</span>
            </li>
          ))}
        </ol>
      )}
      {result.handed_off && <p className="handoff">Passed to the support team.</p>}
    </div>
  );
}

export default function CustomerChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Braces matter: newer browsers return a Promise from scrollIntoView, and
    // React would treat that return value as a cleanup function.
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    setMessages((m) => [...m, { role: "customer", text: message }]);
    setInput("");
    setBusy(true);
    setError(null);
    try {
      const result = await api.chat(message, conversationId);
      setConversationId(result.conversation_id);
      setMessages((m) => [...m, { role: "agent", result }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void send(input);
  }

  return (
    <main className="page narrow">
      <section className="card chat">
        <header>
          <h1>Customer chat</h1>
          <p className="muted">Answers come from the help center. Refunds wait for a person.</p>
        </header>

        <div className="messages">
          {messages.length === 0 && (
            <div className="bubble agent">
              <p>Hi! Ask me about shipping, returns, billing or an order.</p>
            </div>
          )}
          {messages.map((m, i) =>
            m.role === "customer" ? (
              <div key={i} className="bubble customer">
                {m.text}
              </div>
            ) : (
              <AgentMessage key={i} result={m.result} />
            ),
          )}
          {busy && <div className="bubble agent thinking">Checking…</div>}
          {error && <p className="error">{error}</p>}
          <div ref={bottomRef} />
        </div>

        {messages.length === 0 && (
          <div className="suggestions">
            {SUGGESTIONS.map((s) => (
              <button key={s} type="button" onClick={() => void send(s)}>
                {s}
              </button>
            ))}
          </div>
        )}

        <form className="composer" onSubmit={onSubmit}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type your question…"
            maxLength={4000}
            disabled={busy}
          />
          <button type="submit" disabled={busy || !input.trim()}>
            Send
          </button>
        </form>
      </section>
    </main>
  );
}
