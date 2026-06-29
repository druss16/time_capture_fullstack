import { useState, useEffect, useRef } from "react";

const AUTH_KEY = "auth_token"; // primary; matches TimeTracker convention

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
  const scrollRef = useRef(null);

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [messages]);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setEscalate(false);
    setMessages((m) => [...m, { role: "user", content: text }]);
    setLoading(true);
    try {
      const res = await fetch("/api/support/chat/", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ conversation_id: convId, message: text }),
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
        { role: "assistant", content: "Something went wrong. Try email support below." },
      ]);
      setEscalate(true);
    } finally {
      setLoading(false);
    }
  }

  async function openTicket() {
    const subject = messages.find((m) => m.role === "user")?.content?.slice(0, 60) || "Support request";
    const body = messages.map((m) => `${m.role.toUpperCase()}: ${m.content}`).join("\n\n");
    await fetch("/api/support/ticket/", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ subject, body, conversation_id: convId }),
    });
    setEscalate(false);
    setMessages((m) => [
      ...m,
      { role: "assistant", content: "Thanks — I've opened an email ticket. The team will reply to your account email." },
    ]);
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
        {messages.length === 0 && (
          <p style={{ color: "#64748b", fontSize: 14 }}>
            Ask anything about TimeTracker — agent setup, billing workflow, classification, calendar sync.
          </p>
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
        {escalate && (
          <button onClick={openTicket} style={{ alignSelf: "flex-start", padding: "8px 14px", background: "#2563eb", color: "white", border: "none", borderRadius: 8, cursor: "pointer", fontSize: 13 }}>
            Email the team instead
          </button>
        )}
      </div>

      <div style={{ borderTop: "1px solid #e2e8f0", padding: 12, display: "flex", gap: 8 }}>
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
    </div>
  );
}