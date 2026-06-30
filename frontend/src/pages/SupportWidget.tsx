import { useState, useEffect, useRef } from "react";

const AUTH_KEY = "auth_token"; // primary; matches TimeTracker convention

// Resolve the backend API base the same way the rest of the app does, so calls
// hit the Django service — NOT the frontend origin. A relative "/api/..." path
// would resolve against the frontend domain and 404.
const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;

// Role-aware starter questions. Each maps to a strong KB doc so the first
// answer is a good one. The widget picks a set based on the user's role.
const PROMPTS_BY_ROLE = {
  member: [
    "How does the Daily Review work?",
    "How do I move time to another client?",
    "My time was categorized to the wrong client — what do I do?",
    "How do I submit my timesheet?",
    "How do I install the desktop agent?",
  ],
  manager: [
    "How do I approve timesheets?",
    "How does the Daily Review work?",
    "How do I assign team members to a client?",
    "How do I move time to another client?",
    "How do I add a client?",
  ],
  owner: [
    "How do I reduce my seat count?",
    "How do I change or upgrade my plan?",
    "What does the AI sensitivity slider do?",
    "How do I invite a team member?",
    "How do I set billing rates?",
  ],
};
// admin sees the same set as owner
PROMPTS_BY_ROLE.admin = PROMPTS_BY_ROLE.owner;

function promptsForRole(role) {
  return PROMPTS_BY_ROLE[role] || PROMPTS_BY_ROLE.member;
}

function authHeaders() {
  const token =
    localStorage.getItem("auth_token") ||
    localStorage.getItem("tt_auth_token") ||
    localStorage.getItem("authToken") ||
    localStorage.getItem("token");
  return { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
}

export default function SupportWidget() {
  const [open, setOpen] = useState(false);
  const [convId, setConvId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [escalate, setEscalate] = useState(false);
  const [role, setRole] = useState("member");
  const [ticketMode, setTicketMode] = useState(false); // showing the report form
  const [ticketText, setTicketText] = useState("");
  const [ticketSending, setTicketSending] = useState(false);
  const scrollRef = useRef(null);

  // Fetch the user's role once, when the widget first opens.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    fetch(`${API_BASE}/whoami/`, { headers: authHeaders() })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (!cancelled && d?.role) setRole(d.role); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [open]);

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [messages, ticketMode]);

  // Core send — takes explicit text so suggested-prompt chips can call it
  // directly without waiting on input state to update.
  async function sendMessage(text) {
    const trimmed = (text ?? "").trim();
    if (!trimmed || loading) return;
    setInput("");
    setEscalate(false);
    setMessages((m) => [...m, { role: "user", content: trimmed }]);
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/support/chat/`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ conversation_id: convId, message: trimmed }),
      });
      const data = await res.json();
      setConvId(data.conversation_id);
      setMessages((m) => [
        ...m,
        { role: "assistant", content: data.reply, sources: data.sources },
      ]);
      setEscalate(data.escalate);
    } catch {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: "Something went wrong. You can report this to our team below." },
      ]);
      setEscalate(true);
    } finally {
      setLoading(false);
    }
  }

  // Send what's currently typed in the input box.
  function send() {
    sendMessage(input);
  }

  // Submit a support ticket. Sends the chat transcript (if any) plus whatever
  // the user typed in the report box. The server attaches org/user from the
  // auth token; we also pass role to help triage.
  async function submitTicket() {
    const note = ticketText.trim();
    if (!note && messages.length === 0) return;
    setTicketSending(true);

    const transcript = messages
      .map((m) => `${m.role.toUpperCase()}: ${m.content}`)
      .join("\n\n");
    const firstUser = messages.find((m) => m.role === "user")?.content;
    const subject = (note || firstUser || "Support request").slice(0, 60);
    const body = [
      note ? `User message:\n${note}` : null,
      transcript ? `Conversation:\n${transcript}` : null,
      `Role: ${role}`,
    ]
      .filter(Boolean)
      .join("\n\n");

    try {
      await fetch(`${API_BASE}/support/ticket/`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ subject, body, conversation_id: convId, role }),
      });
      setEscalate(false);
      setTicketMode(false);
      setTicketText("");
      setMessages((m) => [
        ...m,
        { role: "assistant", content: "Thanks — your message has been sent to our support team. We'll reply to your account email." },
      ]);
    } catch {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: "Couldn't send that just now. Please email support@mavops.ai directly." },
      ]);
    } finally {
      setTicketSending(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        style={{
          position: "fixed", bottom: 24, right: 24, borderRadius: 9999,
          padding: "12px 20px", background: "#1e293b", color: "white",
          border: "none", cursor: "pointer", fontWeight: 600,
        }}
      >
        Help
      </button>
    );
  }

  return (
    <div
      style={{
        position: "fixed", bottom: 24, right: 24, width: 380, height: 540,
        background: "white", borderRadius: 12, boxShadow: "0 10px 40px rgba(0,0,0,.2)",
        display: "flex", flexDirection: "column", overflow: "hidden",
        border: "1px solid #e2e8f0",
      }}
    >
      <div style={{ background: "#1e293b", color: "white", padding: "12px 16px", display: "flex", justifyContent: "space-between" }}>
        <strong>TimeTracker Support</strong>
        <button onClick={() => setOpen(false)} style={{ background: "none", border: "none", color: "white", cursor: "pointer" }}>×</button>
      </div>

      <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
        {messages.length === 0 && !ticketMode && (
          <>
            <p style={{ color: "#64748b", fontSize: 14, margin: 0 }}>
              Hi! Ask anything about TimeTracker — or pick a question below to get started.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 4 }}>
              {promptsForRole(role).map((q) => (
                <button
                  key={q}
                  onClick={() => sendMessage(q)}
                  disabled={loading}
                  style={{
                    textAlign: "left", padding: "8px 12px", fontSize: 13,
                    background: "#f8fafc", color: "#0f172a",
                    border: "1px solid #e2e8f0", borderRadius: 8,
                    cursor: loading ? "default" : "pointer",
                  }}
                >
                  {q}
                </button>
              ))}
            </div>
          </>
        )}

        {messages.map((m, i) => (
          <div key={i} style={{ alignSelf: m.role === "user" ? "flex-end" : "flex-start", maxWidth: "85%" }}>
            <div style={{
              padding: "8px 12px", borderRadius: 12, fontSize: 14, whiteSpace: "pre-wrap",
              background: m.role === "user" ? "#1e293b" : "#f1f5f9",
              color: m.role === "user" ? "white" : "#0f172a",
            }}>
              {m.content}
            </div>
            {m.sources?.length > 0 && (
              <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4 }}>
                Sources: {m.sources.map((s) => s.title).join(", ")}
              </div>
            )}
          </div>
        ))}

        {loading && <div style={{ color: "#94a3b8", fontSize: 14 }}>Thinking…</div>}

        {escalate && !ticketMode && (
          <button onClick={() => setTicketMode(true)} style={{ alignSelf: "flex-start", padding: "8px 14px", background: "#2563eb", color: "white", border: "none", borderRadius: 8, cursor: "pointer", fontSize: 13 }}>
            Report this to our team
          </button>
        )}

        {/* Ticket / report form */}
        {ticketMode && (
          <div style={{ border: "1px solid #e2e8f0", borderRadius: 10, padding: 12, background: "#f8fafc" }}>
            <p style={{ margin: "0 0 8px", fontSize: 13, fontWeight: 600, color: "#0f172a" }}>
              Report an issue to support
            </p>
            <p style={{ margin: "0 0 8px", fontSize: 12, color: "#64748b" }}>
              Describe what happened — e.g. a Daily Review bug or time categorized to the wrong client. We'll include this chat and your account details so we can look into it.
            </p>
            <textarea
              value={ticketText}
              onChange={(e) => setTicketText(e.target.value)}
              placeholder="What's going on?"
              rows={4}
              style={{ width: "100%", boxSizing: "border-box", padding: "8px 10px", border: "1px solid #cbd5e1", borderRadius: 8, fontSize: 13, resize: "vertical" }}
            />
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <button
                onClick={submitTicket}
                disabled={ticketSending || (!ticketText.trim() && messages.length === 0)}
                style={{ padding: "8px 14px", background: "#2563eb", color: "white", border: "none", borderRadius: 8, cursor: "pointer", fontSize: 13, opacity: ticketSending ? 0.6 : 1 }}
              >
                {ticketSending ? "Sending…" : "Send to support"}
              </button>
              <button
                onClick={() => { setTicketMode(false); setTicketText(""); }}
                style={{ padding: "8px 14px", background: "white", color: "#475569", border: "1px solid #cbd5e1", borderRadius: 8, cursor: "pointer", fontSize: 13 }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Footer: input + persistent report link */}
      <div style={{ borderTop: "1px solid #e2e8f0", padding: 12, display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="Type your question…"
            style={{ flex: 1, padding: "8px 12px", border: "1px solid #cbd5e1", borderRadius: 8, fontSize: 14 }}
          />
          <button onClick={send} disabled={loading} style={{ padding: "8px 16px", background: "#1e293b", color: "white", border: "none", borderRadius: 8, cursor: "pointer" }}>
            Send
          </button>
        </div>
        {!ticketMode && (
          <button
            onClick={() => setTicketMode(true)}
            style={{ background: "none", border: "none", color: "#2563eb", fontSize: 12, cursor: "pointer", alignSelf: "center", padding: 0 }}
          >
            Report an issue to support
          </button>
        )}
      </div>
    </div>
  );
}