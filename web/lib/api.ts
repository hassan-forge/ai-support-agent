export interface Citation {
  n: number;
  source: string;
  title: string;
  score: number;
}

export interface Action {
  tool: string;
  status: "done" | "pending_approval" | "failed" | string;
  approval_id: string | null;
  detail: string | null;
}

export interface ChatResult {
  conversation_id: string;
  answer: string;
  citations: Citation[];
  actions: Action[];
  handed_off: boolean;
}

export interface Approval {
  id: string;
  conversation_id: string;
  tool: string;
  arguments: Record<string, unknown>;
  reason: string;
  status: "pending" | "approved" | "rejected";
  result: unknown;
  created_at: string;
  decided_at: string | null;
  decided_by: string | null;
}

export interface Ticket {
  id: string;
  [key: string]: unknown;
}

export interface AuditEntry {
  at: string;
  actor: string;
  action: string;
  [key: string]: unknown;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  chat: (message: string, conversationId: string | null) =>
    request<ChatResult>("/chat", {
      method: "POST",
      body: JSON.stringify({ message, conversation_id: conversationId }),
    }),
  approvals: (status: "pending" | "all") =>
    request<Approval[]>(`/approvals?status=${status}`),
  decide: (id: string, approve: boolean, reviewer: string) =>
    request<Record<string, unknown>>(`/approvals/${id}/${approve ? "approve" : "reject"}`, {
      method: "POST",
      body: JSON.stringify({ reviewer }),
    }),
  tickets: () => request<Ticket[]>("/tickets"),
  audit: (limit = 50) => request<AuditEntry[]>(`/audit?limit=${limit}`),
};
