export type TicketStatus = "open" | "in_progress" | "resolved" | "closed";
export type TicketPriority = "low" | "medium" | "high" | "urgent";
export type UserRole = "operator" | "approver" | "admin";
export type JobStatus = "queued" | "running" | "completed" | "failed";

export interface User { id: number; email: string; display_name: string; role: UserRole; }
export interface TokenResponse { access_token: string; token_type: "bearer"; expires_in: number; user: User; }
export interface Job {
  id: number; job_type: "investigation" | "action_execution"; status: JobStatus;
  ticket_id: number | null; recommendation_id: number | null; requested_by_id: number;
  idempotency_key: string | null; result: Record<string, unknown>; error: string | null;
  attempts: number; max_attempts: number; created_at: string; started_at: string | null;
  completed_at: string | null;
}
export interface Customer { id: number; name: string; email: string; account_reference: string | null; created_at: string; }
export interface Ticket {
  id: number; customer_id: number; title: string; description: string; status: TicketStatus;
  priority: TicketPriority; created_at: string; updated_at: string;
}
export interface EvidenceItem {
  source_type: "ticket" | "customer" | "account" | "invoice" | "knowledge_article";
  source_id: string; detail: string;
}
export type WorkflowState = "pending_approval" | "ready" | "approved" | "rejected" | "executing" | "completed" | "failed";
export interface ApprovalDecision {
  id: number; recommendation_id: number; ticket_id: number; decision: "approved" | "rejected";
  reviewer: string; note: string | null; created_at: string;
}
export interface ActionExecution {
  id: number; recommendation_id: number; ticket_id: number; action: string; idempotency_key: string;
  status: "executing" | "completed" | "failed"; attempts: number; external_reference: string | null;
  result: Record<string, unknown>; error: string | null; created_at: string; completed_at: string | null;
}
export interface Recommendation {
  id: number; ticket_id: number; category: string; summary: string; confidence: number;
  evidence: EvidenceItem[]; recommended_action: string; requires_approval: boolean; provider: string;
  created_at: string; workflow_state: WorkflowState; approval: ApprovalDecision | null;
  execution: ActionExecution | null;
}
export interface AuditEvent {
  id: number; ticket_id: number; event_type: string; message: string;
  event_metadata: Record<string, unknown>; created_at: string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "opspilot_access_token";

export function setAccessToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

export function getAccessToken() {
  return typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getAccessToken();
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    if (response.status === 401) setAccessToken(null);
    throw new Error(body?.detail ?? `Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function waitForJob(initial: Job): Promise<Job> {
  let job = initial;
  for (let attempt = 0; attempt < 120; attempt += 1) {
    if (job.status === "completed") return job;
    if (job.status === "failed") throw new Error(job.error ?? "Background job failed");
    await new Promise((resolve) => window.setTimeout(resolve, 500));
    job = await api.getJob(job.id);
  }
  throw new Error("The background job is still running. Check again shortly.");
}

export const api = {
  login: (email: string, password: string) => request<TokenResponse>("/auth/login", {
    method: "POST", body: JSON.stringify({ email, password }),
  }),
  getMe: () => request<User>("/auth/me"),
  getTickets: () => request<Ticket[]>("/tickets"),
  getCustomers: () => request<Customer[]>("/customers"),
  getJob: (id: number) => request<Job>(`/jobs/${id}`),
  updateTicket: (id: number, changes: Partial<Pick<Ticket, "status" | "priority">>) =>
    request<Ticket>(`/tickets/${id}`, { method: "PATCH", body: JSON.stringify(changes) }),
  createTicket: (ticket: Omit<Ticket, "id" | "created_at" | "updated_at">) =>
    request<Ticket>("/tickets", { method: "POST", body: JSON.stringify(ticket) }),
  investigateTicket: (id: number) => request<Job>(`/tickets/${id}/investigate`, { method: "POST" }),
  getRecommendations: (id: number) => request<Recommendation[]>(`/tickets/${id}/recommendations`),
  approveRecommendation: (ticketId: number, recommendationId: number, note: string) =>
    request<Recommendation>(`/tickets/${ticketId}/recommendations/${recommendationId}/approve`, {
      method: "POST", body: JSON.stringify({ note: note || null }),
    }),
  rejectRecommendation: (ticketId: number, recommendationId: number, note: string) =>
    request<Recommendation>(`/tickets/${ticketId}/recommendations/${recommendationId}/reject`, {
      method: "POST", body: JSON.stringify({ note: note || null }),
    }),
  executeRecommendation: (ticketId: number, recommendationId: number, idempotencyKey: string) =>
    request<Job>(`/tickets/${ticketId}/recommendations/${recommendationId}/execute`, {
      method: "POST", headers: { "Idempotency-Key": idempotencyKey },
    }),
  getEvents: (id: number) => request<AuditEvent[]>(`/tickets/${id}/events`),
};
