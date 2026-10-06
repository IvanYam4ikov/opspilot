export type TicketStatus = "open" | "in_progress" | "resolved" | "closed";
export type TicketPriority = "low" | "medium" | "high" | "urgent";

export interface Customer {
  id: number;
  name: string;
  email: string;
  account_reference: string | null;
  created_at: string;
}

export interface Ticket {
  id: number;
  customer_id: number;
  title: string;
  description: string;
  status: TicketStatus;
  priority: TicketPriority;
  created_at: string;
  updated_at: string;
}

export interface EvidenceItem {
  source_type: "ticket" | "customer" | "account" | "invoice" | "knowledge_article";
  source_id: string;
  detail: string;
}

export type WorkflowState =
  | "pending_approval"
  | "ready"
  | "approved"
  | "rejected"
  | "executing"
  | "completed"
  | "failed";

export interface ApprovalDecision {
  id: number;
  recommendation_id: number;
  ticket_id: number;
  decision: "approved" | "rejected";
  reviewer: string;
  note: string | null;
  created_at: string;
}

export interface ActionExecution {
  id: number;
  recommendation_id: number;
  ticket_id: number;
  action: string;
  idempotency_key: string;
  status: "executing" | "completed" | "failed";
  attempts: number;
  external_reference: string | null;
  result: Record<string, unknown>;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface Recommendation {
  id: number;
  ticket_id: number;
  category: string;
  summary: string;
  confidence: number;
  evidence: EvidenceItem[];
  recommended_action: string;
  requires_approval: boolean;
  provider: string;
  created_at: string;
  workflow_state: WorkflowState;
  approval: ApprovalDecision | null;
  execution: ActionExecution | null;
}

export interface AuditEvent {
  id: number;
  ticket_id: number;
  event_type: string;
  message: string;
  event_metadata: Record<string, unknown>;
  created_at: string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  getTickets: () => request<Ticket[]>("/tickets"),
  getCustomers: () => request<Customer[]>("/customers"),
  updateTicket: (id: number, changes: Partial<Pick<Ticket, "status" | "priority">>) =>
    request<Ticket>(`/tickets/${id}`, { method: "PATCH", body: JSON.stringify(changes) }),
  createTicket: (ticket: Omit<Ticket, "id" | "created_at" | "updated_at">) =>
    request<Ticket>("/tickets", { method: "POST", body: JSON.stringify(ticket) }),
  investigateTicket: (id: number) =>
    request<Recommendation>(`/tickets/${id}/investigate`, { method: "POST" }),
  getRecommendations: (id: number) =>
    request<Recommendation[]>(`/tickets/${id}/recommendations`),
  approveRecommendation: (ticketId: number, recommendationId: number, reviewer: string, note: string) =>
    request<Recommendation>(`/tickets/${ticketId}/recommendations/${recommendationId}/approve`, {
      method: "POST",
      body: JSON.stringify({ reviewer, note: note || null }),
    }),
  rejectRecommendation: (ticketId: number, recommendationId: number, reviewer: string, note: string) =>
    request<Recommendation>(`/tickets/${ticketId}/recommendations/${recommendationId}/reject`, {
      method: "POST",
      body: JSON.stringify({ reviewer, note: note || null }),
    }),
  executeRecommendation: (ticketId: number, recommendationId: number, idempotencyKey: string) =>
    request<ActionExecution>(`/tickets/${ticketId}/recommendations/${recommendationId}/execute`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
    }),
  getEvents: (id: number) => request<AuditEvent[]>(`/tickets/${id}/events`),
};
