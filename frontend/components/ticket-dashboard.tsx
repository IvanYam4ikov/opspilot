"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  AuditEvent,
  Customer,
  Recommendation,
  Ticket,
  TicketPriority,
  TicketStatus,
} from "@/lib/api";

const statuses: TicketStatus[] = ["open", "in_progress", "resolved", "closed"];
const priorities: TicketPriority[] = ["low", "medium", "high", "urgent"];

const labels: Record<TicketStatus, string> = {
  open: "Open",
  in_progress: "In progress",
  resolved: "Resolved",
  closed: "Closed",
};

export function TicketDashboard() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [filter, setFilter] = useState<TicketStatus | "all">("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [investigating, setInvestigating] = useState(false);

  const loadData = useCallback(async () => {
    try {
      setError(null);
      const [ticketData, customerData] = await Promise.all([
        api.getTickets(),
        api.getCustomers(),
      ]);
      setTickets(ticketData);
      setCustomers(customerData);
      setSelectedId((current) => current ?? ticketData[0]?.id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not connect to OpsPilot API");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  useEffect(() => {
    if (selectedId === null) return;
    let active = true;
    Promise.all([api.getRecommendations(selectedId), api.getEvents(selectedId)])
      .then(([recommendations, auditEvents]) => {
        if (!active) return;
        setRecommendation(recommendations[0] ?? null);
        setEvents(auditEvents);
      })
      .catch((err) => active && setError(err instanceof Error ? err.message : "Could not load investigation"));
    return () => { active = false; };
  }, [selectedId]);

  const filteredTickets = useMemo(
    () => tickets.filter((ticket) => filter === "all" || ticket.status === filter),
    [filter, tickets],
  );
  const selected = tickets.find((ticket) => ticket.id === selectedId) ?? null;
  const customer = customers.find((item) => item.id === selected?.customer_id);

  async function updateTicket(changes: Partial<Pick<Ticket, "status" | "priority">>) {
    if (!selected) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateTicket(selected.id, changes);
      setTickets((current) => current.map((ticket) => (ticket.id === updated.id ? updated : ticket)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ticket update failed");
    } finally {
      setSaving(false);
    }
  }

  async function createTicket(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaving(true);
    setError(null);
    try {
      const created = await api.createTicket({
        customer_id: Number(form.get("customer_id")),
        title: String(form.get("title")),
        description: String(form.get("description")),
        status: "open",
        priority: String(form.get("priority")) as TicketPriority,
      });
      setTickets((current) => [created, ...current]);
      setSelectedId(created.id);
      setFilter("all");
      setShowCreate(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ticket creation failed");
    } finally {
      setSaving(false);
    }
  }

  async function investigate() {
    if (!selected) return;
    setInvestigating(true);
    setError(null);
    try {
      const result = await api.investigateTicket(selected.id);
      setRecommendation(result);
      setEvents(await api.getEvents(selected.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Investigation failed");
    } finally {
      setInvestigating(false);
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-mark">OP</div>
        <div className="sidebar-items">
          <button className="nav-item active" aria-label="Tickets">⌁</button>
          <button className="nav-item" aria-label="Knowledge base">◇</button>
          <button className="nav-item" aria-label="Analytics">⌗</button>
        </div>
        <div className="avatar">IY</div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">OPERATIONS CONTROL</p>
            <h1>Ticket queue</h1>
          </div>
          <button className="primary-button" onClick={() => setShowCreate(true)}>+ New ticket</button>
        </header>

        {error && <div className="error-banner"><span>{error}</span><button onClick={loadData}>Retry</button></div>}

        <div className="dashboard-grid">
          <section className="queue-panel">
            <div className="queue-toolbar">
              <div className="filter-row">
                {(["all", ...statuses] as const).map((status) => (
                  <button
                    key={status}
                    className={filter === status ? "filter active" : "filter"}
                    onClick={() => setFilter(status)}
                  >
                    {status === "all" ? "All" : labels[status]}
                    <span>{status === "all" ? tickets.length : tickets.filter((t) => t.status === status).length}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="ticket-list">
              {loading && <div className="empty-state">Loading tickets…</div>}
              {!loading && filteredTickets.length === 0 && <div className="empty-state">No tickets in this view.</div>}
              {filteredTickets.map((ticket) => (
                <button
                  key={ticket.id}
                  className={selectedId === ticket.id ? "ticket-card selected" : "ticket-card"}
                  onClick={() => setSelectedId(ticket.id)}
                >
                  <div className="ticket-card-top">
                    <span className={`priority-dot ${ticket.priority}`} />
                    <span className="ticket-number">#{String(ticket.id).padStart(3, "0")}</span>
                    <span className={`status-chip ${ticket.status}`}>{labels[ticket.status]}</span>
                  </div>
                  <strong>{ticket.title}</strong>
                  <p>{ticket.description}</p>
                  <div className="ticket-meta">
                    <span>{customers.find((c) => c.id === ticket.customer_id)?.name ?? `Customer ${ticket.customer_id}`}</span>
                    <time>{formatDate(ticket.created_at)}</time>
                  </div>
                </button>
              ))}
            </div>
          </section>

          <section className="detail-panel">
            {!selected ? (
              <div className="detail-empty"><div>⌁</div><h2>Select a ticket</h2><p>Choose a request from the queue to review its details.</p></div>
            ) : (
              <>
                <div className="detail-heading">
                  <div>
                    <p className="eyebrow">TICKET #{String(selected.id).padStart(3, "0")}</p>
                    <h2>{selected.title}</h2>
                  </div>
                  <span className={`priority-badge ${selected.priority}`}>{selected.priority}</span>
                </div>

                <div className="detail-section">
                  <p className="section-label">Customer</p>
                  <div className="customer-card">
                    <div className="customer-icon">{customer?.name.slice(0, 2).toUpperCase() ?? "?"}</div>
                    <div><strong>{customer?.name ?? "Unknown customer"}</strong><span>{customer?.email}</span></div>
                    <span className="account-ref">{customer?.account_reference}</span>
                  </div>
                </div>

                <div className="detail-section">
                  <p className="section-label">Request</p>
                  <p className="description">{selected.description}</p>
                </div>

                <div className="detail-section split-fields">
                  <label>
                    <span className="section-label">Status</span>
                    <select value={selected.status} disabled={saving} onChange={(e) => void updateTicket({ status: e.target.value as TicketStatus })}>
                      {statuses.map((status) => <option key={status} value={status}>{labels[status]}</option>)}
                    </select>
                  </label>
                  <label>
                    <span className="section-label">Priority</span>
                    <select value={selected.priority} disabled={saving} onChange={(e) => void updateTicket({ priority: e.target.value as TicketPriority })}>
                      {priorities.map((priority) => <option key={priority} value={priority}>{capitalize(priority)}</option>)}
                    </select>
                  </label>
                </div>

                {recommendation ? (
                  <div className="recommendation-card">
                    <div className="recommendation-header">
                      <div><p className="eyebrow">INVESTIGATION RESULT</p><h3>{humanize(recommendation.category)}</h3></div>
                      <div className="confidence"><strong>{Math.round(recommendation.confidence * 100)}%</strong><span>confidence</span></div>
                    </div>
                    <p className="recommendation-summary">{recommendation.summary}</p>
                    <p className="section-label">Evidence</p>
                    <div className="evidence-list">
                      {recommendation.evidence.map((item, index) => (
                        <div className="evidence-item" key={`${item.source_id}-${index}`}>
                          <span>{index + 1}</span>
                          <div><strong>{humanize(item.source_type)} · {item.source_id}</strong><p>{item.detail}</p></div>
                        </div>
                      ))}
                    </div>
                    <div className="recommended-action">
                      <div><span>Recommended action</span><strong>{humanize(recommendation.recommended_action)}</strong></div>
                      {recommendation.requires_approval && <span className="approval-chip">Approval required</span>}
                    </div>
                    <div className="recommendation-footer"><span>Generated via {recommendation.provider}</span><button onClick={() => void investigate()} disabled={investigating}>{investigating ? "Investigating…" : "Run again"}</button></div>
                  </div>
                ) : (
                  <div className="investigation-card">
                    <div className="spark">✦</div>
                    <div><strong>AI investigation</strong><p>Retrieve account, invoice, and policy evidence to generate a structured recommendation.</p></div>
                    <button onClick={() => void investigate()} disabled={investigating}>{investigating ? "Investigating…" : "Investigate"}</button>
                  </div>
                )}

                {events.length > 0 && (
                  <div className="timeline">
                    <p className="section-label">Activity</p>
                    {events.map((event) => (
                      <div className="timeline-event" key={event.id}>
                        <span className="timeline-dot" />
                        <div><strong>{event.message}</strong><time>{formatDate(event.created_at)}</time></div>
                      </div>
                    ))}
                  </div>
                )}

                <div className="timestamps">
                  <span>Created {formatDate(selected.created_at)}</span>
                  <span>Updated {formatDate(selected.updated_at)}</span>
                </div>
              </>
            )}
          </section>
        </div>
      </section>

      {showCreate && (
        <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && setShowCreate(false)}>
          <form className="modal" onSubmit={createTicket}>
            <div className="modal-heading"><div><p className="eyebrow">NEW REQUEST</p><h2>Create ticket</h2></div><button type="button" className="close-button" onClick={() => setShowCreate(false)}>×</button></div>
            <label>Customer<select name="customer_id" required defaultValue=""><option value="" disabled>Select a customer</option>{customers.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
            <label>Title<input name="title" required maxLength={200} placeholder="Briefly describe the issue" /></label>
            <label>Description<textarea name="description" required rows={5} placeholder="Include the details needed to investigate…" /></label>
            <label>Priority<select name="priority" defaultValue="medium">{priorities.map((priority) => <option value={priority} key={priority}>{capitalize(priority)}</option>)}</select></label>
            <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowCreate(false)}>Cancel</button><button className="primary-button" disabled={saving}>{saving ? "Creating…" : "Create ticket"}</button></div>
          </form>
        </div>
      )}
    </main>
  );
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function humanize(value: string) {
  return value.split("_").map(capitalize).join(" ");
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(new Date(value));
}
