"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const ROLE_LABEL = { employee: "Employee", hr_manager: "HR manager", admin: "Admin" };

// Read and immediately clear the login result the API put in the URL fragment.
function takeLoginFragment() {
  if (typeof window === "undefined" || !window.location.hash) return {};
  const params = new URLSearchParams(window.location.hash.slice(1));
  window.history.replaceState(null, "", window.location.pathname);
  return {
    token: params.get("access_token"),
    expiresIn: Number(params.get("expires_in") || 0),
    error: params.get("error"),
  };
}

export default function Home() {
  // The access token lives in memory only: not localStorage, not a cookie.
  const [token, setToken] = useState(null);
  const [expiresAt, setExpiresAt] = useState(null);
  const [me, setMe] = useState(null);
  const [notice, setNotice] = useState(null);
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  const logOut = useCallback((reason) => {
    setToken(null);
    setExpiresAt(null);
    setMe(null);
    setMessages([]);
    setNotice(reason || null);
  }, []);

  useEffect(() => {
    const { token, expiresIn, error } = takeLoginFragment();
    if (error) setNotice(`Login failed: ${error}`);
    if (!token) return;
    setToken(token);
    setExpiresAt(Date.now() + expiresIn * 1000);
  }, []);

  // Drop the token when it expires (15 minutes) rather than waiting for a 401.
  useEffect(() => {
    if (!token || !expiresAt) return;
    const timer = setTimeout(() => logOut("Your session expired. Please log in again."), expiresAt - Date.now());
    return () => clearTimeout(timer);
  }, [token, expiresAt, logOut]);

  useEffect(() => {
    if (!token) return;
    fetch(`${API}/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then(async (r) => (r.ok ? setMe(await r.json()) : logOut((await r.json()).detail)))
      .catch(() => setNotice("Can't reach the Gatekeeper API."));
  }, [token, logOut]);

  useEffect(() => {
    // Braces matter: scrollIntoView can return a Promise, and an effect may only return a cleanup function.
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function ask(e) {
    e.preventDefault();
    const q = question.trim();
    if (!q || busy) return;
    setQuestion("");
    setMessages((m) => [...m, { from: "user", text: q }]);
    setBusy(true);
    try {
      const r = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      const body = await r.json();
      if (r.status === 401) {
        // Deactivated in the IdP, demoted, or expired: the API said no.
        logOut(`Access ended: ${body.detail}. Please log in again.`);
        return;
      }
      if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
      const sources = [...new Set(body.chunks.map((c) => c.reference))];
      setMessages((m) => [...m, { from: "bot", text: body.answer, sources, forbidden: body.forbidden_retrieved }]);
    } catch (err) {
      setMessages((m) => [...m, { from: "bot", text: `Something went wrong: ${err.message}`, error: true }]);
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <main className="login">
        <h1>Gatekeeper</h1>
        <p className="tagline">Ask about your company's documents. You only ever see what you're allowed to.</p>
        {notice && <p className="notice" role="alert">{notice}</p>}
        <div className="buttons">
          <a className="button" href={`${API}/auth/okta/login?next=app`}>
            Log in with Okta <span>Acme Corp</span>
          </a>
          <a className="button" href={`${API}/auth/saml/login?next=app`}>
            Log in with SAML <span>Globex</span>
          </a>
        </div>
      </main>
    );
  }

  return (
    <main className="chat">
      <header>
        <h1>Gatekeeper</h1>
        {me && (
          <div className="badge" title={me.email}>
            <strong>{me.tenant}</strong>
            <span>{ROLE_LABEL[me.role] || me.role}</span>
            <span className="email">{me.email}</span>
          </div>
        )}
        <button className="link" onClick={() => logOut()}>Log out</button>
      </header>

      <section className="messages" aria-live="polite">
        {messages.length === 0 && (
          <p className="empty">Try “How many PTO days do I get?” or “What are the senior engineer salary bands?”</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`message ${m.from}${m.error ? " error" : ""}`}>
            <p>{m.text}</p>
            {m.sources && (
              <p className="meta">
                {m.sources.length ? `Sources: ${m.sources.join(", ")}` : "No documents"}
                <span className={m.forbidden ? "pill bad" : "pill"}>forbidden retrieved: {m.forbidden}</span>
              </p>
            )}
          </div>
        ))}
        {busy && <div className="message bot"><p className="thinking">Searching documents…</p></div>}
        <div ref={endRef} />
      </section>

      <form onSubmit={ask}>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask a question about your company's documents"
          aria-label="Question"
          disabled={busy}
          autoFocus
        />
        <button type="submit" disabled={busy || !question.trim()}>Send</button>
      </form>
    </main>
  );
}
