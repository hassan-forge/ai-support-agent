"use client";

import { useCallback, useEffect, useState } from "react";

import { api, type Approval, type AuditEntry, type Ticket } from "@/lib/api";

const REFRESH_MS = 5000;

function time(iso: string | null) {
  return iso ? new Date(iso).toLocaleString() : "";
}

function ApprovalCard({
  approval,
  reviewer,
  onDecide,
}: {
  approval: Approval;
  reviewer: string;
  onDecide: (id: string, approve: boolean) => void;
}) {
  return (
    <div className="approval">
      <div className="approval-head">
        <strong>{approval.tool}</strong>
        <span className="muted">
          {approval.id} · {time(approval.created_at)}
        </span>
      </div>
      <p>{approval.reason}</p>
      <pre>{JSON.stringify(approval.arguments, null, 2)}</pre>
      <div className="approval-actions">
        <button
          className="approve"
          disabled={!reviewer.trim()}
          onClick={() => onDecide(approval.id, true)}
        >
          Approve
        </button>
        <button
          className="reject"
          disabled={!reviewer.trim()}
          onClick={() => onDecide(approval.id, false)}
        >
          Reject
        </button>
      </div>
    </div>
  );
}

export default function Console() {
  const [pending, setPending] = useState<Approval[]>([]);
  const [history, setHistory] = useState<Approval[]>([]);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [reviewer, setReviewer] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, all, t, a] = await Promise.all([
        api.approvals("pending"),
        api.approvals("all"),
        api.tickets(),
        api.audit(50),
      ]);
      setPending(p);
      setHistory(all.filter((x) => x.status !== "pending"));
      setTickets(t);
      setAudit([...a].reverse());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reach the API");
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  async function decide(id: string, approve: boolean) {
    try {
      await api.decide(id, approve, reviewer.trim());
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Decision failed");
    }
  }

  return (
    <main className="page console">
      {error && <p className="error">{error}</p>}

      <section className="card">
        <div className="section-head">
          <h2>Waiting for approval ({pending.length})</h2>
          <input
            className="reviewer"
            placeholder="Your name (required to decide)"
            value={reviewer}
            onChange={(e) => setReviewer(e.target.value)}
            maxLength={100}
          />
        </div>
        {pending.length === 0 ? (
          <p className="muted">Nothing waiting. Risky actions from the chat show up here.</p>
        ) : (
          pending.map((a) => (
            <ApprovalCard key={a.id} approval={a} reviewer={reviewer} onDecide={decide} />
          ))
        )}
        {history.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Approval</th>
                <th>Tool</th>
                <th>Decision</th>
                <th>By</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {history.map((a) => (
                <tr key={a.id}>
                  <td>{a.id}</td>
                  <td>{a.tool}</td>
                  <td className={a.status}>{a.status}</td>
                  <td>{a.decided_by}</td>
                  <td>{time(a.decided_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h2>Tickets ({tickets.length})</h2>
        {tickets.length === 0 ? (
          <p className="muted">No tickets yet. The agent opens one when the docs can't answer.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Ticket</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {tickets.map((t) => (
                <tr key={t.id}>
                  <td>{t.id}</td>
                  <td>
                    {Object.entries(t)
                      .filter(([k]) => k !== "id")
                      .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
                      .join(" · ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h2>Audit log (latest 50)</h2>
        <table className="audit">
          <thead>
            <tr>
              <th>When</th>
              <th>Actor</th>
              <th>Action</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {audit.map((e, i) => {
              const { at, actor, action, ...rest } = e;
              return (
                <tr key={i}>
                  <td>{time(at)}</td>
                  <td>{actor}</td>
                  <td>{action}</td>
                  <td className="details">{JSON.stringify(rest)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </main>
  );
}
