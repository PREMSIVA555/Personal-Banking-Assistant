import React, {
  useState,
  useEffect,
  useRef,
  FormEvent,
  ReactNode,
} from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowUpRight,
  ArrowDownLeft,
  ArrowRight,
  Send,
  Plus,
  ShieldCheck,
  LayoutDashboard,
  MessageSquare,
  ArrowLeftRight,
  FileCheck,
  BookOpen,
  Activity,
  LogOut,
  Search,
  X,
  Check,
  ChevronRight,
  Headphones,
  Wallet,
  Leaf,
  LockKeyhole,
  LoaderCircle,
  RefreshCw,
  Clock,
  AlertCircle,
  Menu,
  CheckCircle2,
} from "lucide-react";
import "./style.css";

type Customer = { id: string; name: string; email: string };
type Account = {
  id: string;
  label: string;
  last_four: string;
  balance_minor: number;
  currency: string;
};
type Transaction = {
  id: string;
  merchant: string;
  amount_minor: number;
  currency: string;
  posted_at: string;
  category: string;
  account_label: string;
  last_four: string;
};
type Policy = {
  id: string;
  title: string;
  content: string;
  version: string;
  effective_from: string;
};
type Action = {
  id: string;
  kind: string;
  status: string;
  payload: {
    transaction_id: string;
    merchant: string;
    amount_minor: number;
    currency: string;
    reason: string;
    last_four: string;
  };
  version: number;
  expires_at: string;
  created_at: string;
  bank_ref: string | null;
  last_error: string | null;
};
type Data = {
  kind?: string;
  items?: unknown[];
  dispute_mode?: boolean;
  retrieval?: string;
};
type Message = {
  role: string;
  content: string;
  data?: { data?: Data; steps?: string[]; model?: string };
};
type Conversation = {
  id: string;
  title: string;
  revision: number;
  messages?: Message[];
};
type System = {
  chat_model: string;
  embedding_model: string;
  embedding_dim: number;
  providers: { provider: string; outcome: string; model: string }[];
  policies: { total: number; indexed: number };
  audit: { event: string; resource: string; created_at: string }[];
};
let csrf = "";
async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const r = await fetch("/api" + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrf,
      ...options.headers,
    },
  });
  const data = await r.json();
  if (!r.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Please check the entered details.",
    );
  return data;
}
const post = <T,>(path: string, body: unknown = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });
const money = (amount: number, currency = "INR") =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(amount / 100);
const date = (s: string) =>
  new Date(s).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
const labels: Record<string, string> = {
  awaiting_confirmation: "Needs your confirmation",
  queued: "Queued",
  processing: "Submitting",
  submitted: "Submitted",
  reconciling: "Verifying submission",
  retry_scheduled: "Retry scheduled",
  manual_review: "Needs manual review",
  failed: "Unable to submit",
  cancelled: "Cancelled",
  expired: "Expired",
};
function Brand() {
  return (
    <div className="brand">
      <div className="brand-mark">
        <Leaf size={23} />
      </div>
      <span>
        aurora<span className="brand-dot">.</span>
      </span>
    </div>
  );
}
function Pill({ status }: { status: string }) {
  return (
    <span className={"pill " + status}>
      <span />
      {labels[status] || status}
    </span>
  );
}
function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog ref={ref} onCancel={onClose}>
      <div className="modal-head">
        <h2>{title}</h2>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label="Close dialog"
        >
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
function App({ onReset }: { onReset: () => void }) {
  const [customer, setCustomer] = useState<Customer | null>(null),
    [boot, setBoot] = useState(true),
    [page, setPage] = useState("overview"),
    [mobile, setMobile] = useState(false);
  const [accounts, setAccounts] = useState<Account[]>([]),
    [transactions, setTransactions] = useState<Transaction[]>([]),
    [actions, setActions] = useState<Action[]>([]),
    [policies, setPolicies] = useState<Policy[]>([]),
    [system, setSystem] = useState<System | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]),
    [conversation, setConversation] = useState<Conversation | null>(null),
    [messages, setMessages] = useState<Message[]>([]),
    [input, setInput] = useState(""),
    [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(""),
    [error, setError] = useState(""),
    [search, setSearch] = useState(""),
    [loading, setLoading] = useState(false);
  const [draftTx, setDraftTx] = useState<Transaction | null>(null),
    [reason, setReason] = useState(""),
    [proposal, setProposal] = useState<Action | null>(null),
    [confirmKey, setConfirmKey] = useState(""),
    [modalBusy, setModalBusy] = useState(false),
    [modalError, setModalError] = useState("");
  const [supportOpen, setSupportOpen] = useState(false),
    [summary, setSummary] = useState(""),
    [consent, setConsent] = useState(false),
    [cases, setCases] = useState<
      { id: string; summary: string; status: string; created_at: string }[]
    >([]);
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    api<{ customer: Customer; csrf_token: string }>("/me")
      .then((r) => {
        csrf = r.csrf_token;
        setCustomer(r.customer);
      })
      .catch(() => {})
      .finally(() => setBoot(false));
  }, []);
  useEffect(() => {
    if (customer) void refresh();
  }, [customer]);
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(""), 6000);
      return () => clearTimeout(t);
    }
  }, [toast]);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);
  useEffect(() => {
    if (
      !customer ||
      !actions.some((a) =>
        ["queued", "processing", "reconciling", "retry_scheduled"].includes(
          a.status,
        ),
      )
    )
      return;
    const t = setInterval(() => {
      api<Action[]>("/actions")
        .then(setActions)
        .catch(() => {});
    }, 2500);
    return () => clearInterval(t);
  }, [customer, actions]);
  async function refresh() {
    setLoading(true);
    setError("");
    const results = await Promise.allSettled([
      api<Account[]>("/accounts"),
      api<Transaction[]>("/transactions"),
      api<Action[]>("/actions"),
      api<Policy[]>("/policies"),
      api<Conversation[]>("/conversations"),
      api<System>("/system"),
      api<typeof cases>("/support"),
    ]);
    const setters = [
      setAccounts,
      setTransactions,
      setActions,
      setPolicies,
      setConversations,
      setSystem,
      setCases,
    ];
    results.forEach((r, i) => {
      if (r.status === "fulfilled")
        (setters[i] as (v: unknown) => void)(r.value);
      else setError(r.reason.message);
    });
    setLoading(false);
  }
  async function ensureConversation() {
    if (conversation) return conversation;
    const c = await post<Conversation>("/conversations");
    setConversation(c);
    return c;
  }
  async function openConversation(c: Conversation) {
    try {
      const full = await api<Conversation>("/conversations/" + c.id);
      setConversation(full);
      setMessages(full.messages || []);
      setPage("assistant");
      setMobile(false);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function send(text = input) {
    if (!text.trim() || busy) return;
    setPage("assistant");
    setInput("");
    setBusy(true);
    setError("");
    try {
      const c = await ensureConversation();
      setMessages((prev) => [...prev, { role: "user", content: text }]);
      const r = await post<{
        answer: string;
        data: Data;
        steps: string[];
        model: string;
        revision: number;
      }>("/conversations/" + c.id + "/messages", {
        message: text,
        client_id: crypto.randomUUID(),
        expected_revision: c.revision,
      });
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: r.answer, data: r },
      ]);
      setConversation({ ...c, revision: r.revision });
      api<Conversation[]>("/conversations")
        .then(setConversations)
        .catch(() => {});
    } catch (e) {
      setError((e as Error).message);
      if (conversation) {
        const full = await api<Conversation>(
          "/conversations/" + conversation.id,
        ).catch(() => null);
        if (full) {
          setConversation(full);
          setMessages(full.messages || []);
        }
      }
    } finally {
      setBusy(false);
    }
  }
  function startDispute(tx: Transaction) {
    setDraftTx(tx);
    setReason("");
    setModalError("");
  }
  async function prepare(e: FormEvent) {
    e.preventDefault();
    if (!draftTx) return;
    setModalBusy(true);
    setModalError("");
    try {
      const c = await ensureConversation();
      const a = await post<Action>("/actions", {
        conversation_id: c.id,
        transaction_id: draftTx.id,
        reason,
      });
      setProposal(a);
      setConfirmKey(crypto.randomUUID());
      setDraftTx(null);
      api<Action[]>("/actions")
        .then(setActions)
        .catch(() => {});
    } catch (e) {
      setModalError((e as Error).message);
    } finally {
      setModalBusy(false);
    }
  }
  async function confirm() {
    if (!proposal) return;
    setModalBusy(true);
    setModalError("");
    try {
      await post("/actions/" + proposal.id + "/confirm", {
        version: proposal.version,
        idempotency_key: confirmKey,
      });
      setProposal(null);
      setPage("requests");
      setToast("Request confirmed and queued for submission.");
      await refresh();
    } catch (e) {
      setModalError((e as Error).message);
    } finally {
      setModalBusy(false);
    }
  }
  async function cancel(a: Action) {
    try {
      await post("/actions/" + a.id + "/cancel");
      setProposal(null);
      await refresh();
      setToast("Proposal cancelled.");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function handoff(e: FormEvent) {
    e.preventDefault();
    setModalBusy(true);
    setModalError("");
    try {
      const r = await post<{ id: string; message: string }>("/support", {
        summary,
        consent,
      });
      setSupportOpen(false);
      setSummary("");
      setConsent(false);
      setPage("requests");
      setToast(r.message);
      await refresh();
    } catch (e) {
      setModalError((e as Error).message);
    } finally {
      setModalBusy(false);
    }
  }
  function navigate(next: string) {
    setPage(next);
    setMobile(false);
    setError("");
  }
  if (boot)
    return (
      <div className="boot">
        <Brand />
        <LoaderCircle className="spin" />
      </div>
    );
  if (!customer)
    return (
      <LoginScreen
        onLogin={(c, t) => {
          csrf = t;
          setCustomer(c);
        }}
      />
    );
  const total = accounts.reduce((sum, a) => sum + a.balance_minor, 0);
  const debit = transactions.filter((t) => t.amount_minor < 0);
  const spend = debit.reduce((sum, t) => sum - t.amount_minor, 0);
  const nav = [
    ["overview", "Overview", LayoutDashboard],
    ["assistant", "Assistant", MessageSquare],
    ["transactions", "Transactions", ArrowLeftRight],
    ["requests", "Requests", FileCheck],
    ["policies", "Policy library", BookOpen],
    ["activity", "Activity & system", Activity],
  ] as const;
  const chips = [
    "What is my balance?",
    "Show my recent transactions",
    "How do I dispute a charge?",
  ];
  function transactionTable(items: Transaction[], compact = false) {
    return (
      <div className={"transaction-list " + (compact ? "compact" : "")}>
        {items.length === 0 ? (
          <div className="empty-small">No matching transactions.</div>
        ) : (
          items.map((t) => (
            <div className="transaction-row" key={t.id}>
              <div
                className={
                  "merchant-icon " + (t.amount_minor > 0 ? "credit" : "")
                }
              >
                {t.amount_minor > 0 ? (
                  <ArrowDownLeft size={20} />
                ) : (
                  <ArrowUpRight size={20} />
                )}
              </div>
              <div className="merchant">
                <strong>{t.merchant}</strong>
                <span>
                  {compact
                    ? t.category
                    : date(t.posted_at) +
                      " · " +
                      t.account_label +
                      " • " +
                      t.last_four}
                </span>
              </div>
              <div
                className={"amount " + (t.amount_minor > 0 ? "positive" : "")}
              >
                {t.amount_minor > 0 ? "+" : ""}
                {money(t.amount_minor, t.currency)}
                <span>{t.amount_minor > 0 ? "Received" : "Posted"}</span>
              </div>
              {!compact && t.amount_minor < 0 && (
                <button className="text-button" onClick={() => startDispute(t)}>
                  Dispute <ChevronRight size={14} />
                </button>
              )}
            </div>
          ))
        )}
      </div>
    );
  }
  function rich(data?: Data) {
    if (!data) return null;
    if (data.kind === "accounts")
      return (
        <div className="chat-account-list">
          {((data.items as Account[]) || []).map((a) => (
            <div key={a.id}>
              <span>
                {a.label} • {a.last_four}
              </span>
              <strong>{money(a.balance_minor, a.currency)}</strong>
            </div>
          ))}
        </div>
      );
    if (data.kind === "transactions")
      return transactionTable((data.items as Transaction[]) || []);
    if (data.kind === "policies")
      return (
        <div>
          {((data.items as Policy[]) || []).map((p) => (
            <div className="citation" key={p.id}>
              <BookOpen size={17} />
              <div>
                <strong>{p.title}</strong>
                <p>{p.content}</p>
                <small>
                  Approved demo policy · {p.version} · Effective{" "}
                  {date(p.effective_from)}
                </small>
              </div>
            </div>
          ))}
        </div>
      );
    if (data.kind === "actions")
      return (
        <div>
          {((data.items as Action[]) || []).map((a) => (
            <div className="chat-action" key={a.id}>
              <span>{a.payload.merchant}</span>
              <Pill status={a.status} />
            </div>
          ))}
        </div>
      );
    if (data.kind === "handoff")
      return (
        <button
          className="secondary"
          onClick={() => {
            setModalError("");
            setSupportOpen(true);
          }}
        >
          Review support summary <ArrowRight size={15} />
        </button>
      );
    return null;
  }
  return (
    <div className="app-shell">
      <aside className={mobile ? "sidebar open" : "sidebar"}>
        <Brand />
        <div className="workspace-label">
          PERSONAL BANKING <span>DEMO</span>
        </div>
        <nav aria-label="Main navigation">
          {nav.map(([id, label, Icon]) => (
            <button
              key={id}
              className={page === id ? "nav-item active" : "nav-item"}
              onClick={() => navigate(id)}
            >
              <Icon size={19} />
              {label}
              {id === "assistant" && <span className="nav-new">AI</span>}
              {id === "requests" &&
                actions.filter((a) => a.status === "awaiting_confirmation")
                  .length > 0 && (
                  <span className="count">
                    {
                      actions.filter(
                        (a) => a.status === "awaiting_confirmation",
                      ).length
                    }
                  </span>
                )}
            </button>
          ))}
        </nav>
        <div className="sidebar-help">
          <div className="support-icon">
            <Headphones size={21} />
          </div>
          <strong>A little human help?</strong>
          <p>Create a demo support case with a summary you approve.</p>
          <button
            onClick={() => {
              setModalError("");
              setSupportOpen(true);
            }}
          >
            Contact support <ArrowUpRight size={15} />
          </button>
        </div>
        <div className="profile">
          <div className="avatar">
            {customer.name
              .split(" ")
              .map((n) => n[0])
              .join("")}
          </div>
          <div>
            <strong>{customer.name}</strong>
            <span>Synthetic customer</span>
          </div>
          <button
            className="icon-button"
            aria-label="Sign out"
            onClick={async () => {
              try {
                await post("/logout");
                onReset();
                setCustomer(null);
                setConversation(null);
                setMessages([]);
                setAccounts([]);
                setTransactions([]);
                setActions([]);
                setPage("overview");
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            <LogOut size={17} />
          </button>
        </div>
      </aside>
      {mobile && (
        <button
          className="scrim"
          aria-label="Close navigation"
          onClick={() => setMobile(false)}
        />
      )}
      <main>
        <header className="topbar">
          <div>
            <button
              className="icon-button mobile-menu"
              aria-label="Open navigation"
              onClick={() => setMobile(!mobile)}
            >
              <Menu />
            </button>
            <span>Personal workspace</span>
            <ChevronRight size={14} />
            <strong>{nav.find((n) => n[0] === page)?.[1]}</strong>
          </div>
          <div className="top-right">
            <span className="synthetic-badge">
              <span />
              Synthetic data only
            </span>
            <button
              className="icon-button"
              onClick={refresh}
              aria-label="Refresh data"
              disabled={loading}
            >
              <RefreshCw size={17} className={loading ? "spin" : ""} />
            </button>
          </div>
        </header>
        <div className="content">
          {error && (
            <div className="error-banner" role="alert">
              <AlertCircle size={18} />
              {error}
              <button onClick={() => setError("")} aria-label="Dismiss error">
                <X size={16} />
              </button>
            </div>
          )}
          {page === "overview" && (
            <>
              <div className="page-title">
                <div>
                  <div className="eyebrow">YOUR MONEY, AT A GLANCE</div>
                  <h1>
                    Good to see you, {customer.name.split(" ")[0]}
                    <span className="green-dot">.</span>
                  </h1>
                  <p>
                    A clearer picture of your accounts. A little less to think
                    about.
                  </p>
                </div>
                <div className="date-tag">
                  <Clock size={16} />
                  {new Date().toLocaleDateString("en-IN", {
                    day: "numeric",
                    month: "long",
                    year: "numeric",
                  })}
                </div>
              </div>
              <div className="overview-grid">
                <section className="balance-card">
                  <div className="balance-top">
                    <span>Total available balance</span>
                    <Wallet size={22} />
                  </div>
                  <div className="balance-value">{money(total)}</div>
                  <div className="balance-meta">
                    <span className="light-dot" />
                    Across {accounts.length} accounts <span>INR</span>
                  </div>
                  <div className="balance-divider" />
                  <div className="account-mini">
                    {accounts.map((a) => (
                      <div key={a.id}>
                        <span>
                          {a.label} <small>•• {a.last_four}</small>
                        </span>
                        <strong>{money(a.balance_minor, a.currency)}</strong>
                      </div>
                    ))}
                  </div>
                  <div className="card-decoration" aria-hidden="true" />
                </section>
                <section className="assistant-promo">
                  <div className="assistant-emblem">
                    <MessageSquare size={27} />
                    <span>✦</span>
                  </div>
                  <div className="eyebrow">MEET YOUR BANKING ASSISTANT</div>
                  <h2>
                    A question about your money?
                    <br />
                    Let’s make it clear.
                  </h2>
                  <p>
                    Find a transaction, understand a policy, or get help with an
                    unfamiliar charge.
                  </p>
                  <button
                    className="primary"
                    onClick={() => navigate("assistant")}
                  >
                    Start a conversation <ArrowUpRight size={18} />
                  </button>
                </section>
              </div>
              <div className="lower-grid">
                <section className="panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Recent activity</h2>
                      <p>Your latest account movements</p>
                    </div>
                    <button
                      className="text-button"
                      onClick={() => navigate("transactions")}
                    >
                      View all <ArrowRight size={16} />
                    </button>
                  </div>
                  {transactionTable(transactions.slice(0, 5), true)}
                </section>
                <div className="right-stack">
                  <section className="panel spend-panel">
                    <div className="panel-heading">
                      <h2>Recent spending</h2>
                      <span className="muted">{debit.length} transactions</span>
                    </div>
                    <strong className="spend-value">{money(spend)}</strong>
                    <p className="muted">Across the transactions shown</p>
                    <div className="category-bars">
                      {Object.entries(
                        debit.reduce<Record<string, number>>(
                          (a, t) => ({
                            ...a,
                            [t.category]: (a[t.category] || 0) - t.amount_minor,
                          }),
                          {},
                        ),
                      )
                        .sort((a, b) => b[1] - a[1])
                        .slice(0, 4)
                        .map(([category, value], i) => (
                          <div key={category}>
                            <div>
                              <span>
                                <i className={"category-dot c" + i} />
                                {category}
                              </span>
                              <strong>{money(value)}</strong>
                            </div>
                            <div className="bar-track">
                              <div
                                className={"bar c" + i}
                                style={{
                                  width:
                                    (spend ? (value / spend) * 100 : 0) + "%",
                                }}
                              />
                            </div>
                          </div>
                        ))}
                    </div>
                  </section>
                  <div className="trust-card">
                    <ShieldCheck size={26} />
                    <div>
                      <strong>You stay in control.</strong>
                      <p>
                        Every service request needs your review and explicit
                        confirmation.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </>
          )}
          {page === "assistant" && (
            <div className="assistant-layout">
              <section className="chat-panel">
                <div className="chat-heading">
                  <div className="chat-logo">
                    <MessageSquare size={21} />
                  </div>
                  <div>
                    <h2>Aurora assistant</h2>
                    <span>Grounded in your demo bank’s records</span>
                  </div>
                  <button
                    className="secondary small"
                    disabled={busy}
                    onClick={() => {
                      setConversation(null);
                      setMessages([]);
                      setError("");
                    }}
                  >
                    <Plus size={16} />
                    New chat
                  </button>
                </div>
                <div className="chat-body" aria-live="polite">
                  {messages.length === 0 ? (
                    <div className="chat-welcome">
                      <div className="welcome-orb">
                        <Leaf size={35} />
                      </div>
                      <div className="eyebrow">
                        A LITTLE CLARITY GOES A LONG WAY
                      </div>
                      <h1>
                        What can we help
                        <br />
                        you understand?
                      </h1>
                      <p>
                        Ask naturally. We’ll check your records, find the right
                        policy,
                        <br className="desktop-only" /> and help you take the
                        next step.
                      </p>
                      <div className="prompt-grid">
                        {chips.map((s, i) => (
                          <button key={s} onClick={() => send(s)}>
                            {
                              [
                                <Wallet size={20} />,
                                <ArrowLeftRight size={20} />,
                                <ShieldCheck size={20} />,
                              ][i]
                            }
                            <span>{s}</span>
                            <ArrowUpRight size={16} />
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : (
                    messages.map((m, i) => (
                      <div className={"message " + m.role} key={i}>
                        <div className="message-avatar">
                          {m.role === "user" ? (
                            customer.name[0]
                          ) : (
                            <Leaf size={17} />
                          )}
                        </div>
                        <div className="message-content">
                          <div className="message-author">
                            {m.role === "user" ? "You" : "Aurora"}
                          </div>
                          <p>{m.content}</p>
                          {rich(m.data?.data)}
                          {m.data?.steps && m.data.steps.length > 0 && (
                            <details className="evidence">
                              <summary>
                                <ShieldCheck size={13} /> Verified workflow ·{" "}
                                {m.data.steps.length} steps
                              </summary>
                              <ol>
                                {m.data.steps.map((s) => (
                                  <li key={s}>{s}</li>
                                ))}
                              </ol>
                              <small>Routing model: {m.data.model}</small>
                            </details>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                  {busy && (
                    <div className="thinking">
                      <LoaderCircle size={17} className="spin" />
                      Checking your request and retrieving verified information…
                    </div>
                  )}
                  <div ref={endRef} />
                </div>
                <form
                  className="composer"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void send();
                  }}
                >
                  <textarea
                    aria-label="Message your banking assistant"
                    placeholder="Ask about your accounts, transactions, or a charge…"
                    value={input}
                    maxLength={2000}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        void send();
                      }
                    }}
                  />
                  <button
                    className="send-button"
                    disabled={busy || !input.trim()}
                    aria-label="Send message"
                  >
                    <Send size={19} />
                  </button>
                </form>
                <p className="chat-disclaimer">
                  <LockKeyhole size={12} />
                  Synthetic demo. Chat may be processed by Groq and Voyage. Do
                  not enter real personal data.
                </p>
              </section>
              <aside className="chat-context">
                <div className="context-label">YOUR WORKSPACE</div>
                <h3>Conversation history</h3>
                {conversations.length === 0 ? (
                  <p className="muted">Your conversations will appear here.</p>
                ) : (
                  conversations.map((c) => (
                    <button
                      disabled={busy}
                      className={
                        "history-item " +
                        (c.id === conversation?.id ? "selected" : "")
                      }
                      key={c.id}
                      onClick={() => openConversation(c)}
                    >
                      <MessageSquare size={15} />
                      <span>{c.title}</span>
                    </button>
                  ))
                )}
                <div className="context-note">
                  <ShieldCheck size={22} />
                  <h3>Built around your permission</h3>
                  <p>
                    The assistant can retrieve information and prepare requests.
                    You confirm every submission.
                  </p>
                </div>
              </aside>
            </div>
          )}
          {page === "transactions" && (
            <>
              <div className="page-title">
                <div>
                  <div className="eyebrow">FOLLOW THE DETAILS</div>
                  <h1>Your transactions</h1>
                  <p>
                    Explore recent activity or get help with an unfamiliar
                    charge.
                  </p>
                </div>
              </div>
              <div className="panel">
                <div className="filter-bar">
                  <label className="search-field">
                    <Search size={18} />
                    <input
                      aria-label="Search transactions by merchant"
                      placeholder="Search by merchant"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                    />
                  </label>
                  <span className="muted">
                    {
                      transactions.filter((t) =>
                        t.merchant.toLowerCase().includes(search.toLowerCase()),
                      ).length
                    }{" "}
                    transactions
                  </span>
                </div>
                {transactionTable(
                  transactions.filter((t) =>
                    t.merchant.toLowerCase().includes(search.toLowerCase()),
                  ),
                )}
              </div>
            </>
          )}
          {page === "requests" && (
            <>
              <div className="page-title">
                <div>
                  <div className="eyebrow">EVERY STEP, ACCOUNTED FOR</div>
                  <h1>Your requests</h1>
                  <p>
                    Review pending proposals and follow your submitted requests.
                  </p>
                </div>
                <button className="secondary" onClick={refresh}>
                  <RefreshCw size={16} />
                  Refresh status
                </button>
              </div>
              {actions.length === 0 ? (
                <div className="empty-state panel">
                  <FileCheck size={38} />
                  <h2>No service requests yet</h2>
                  <p>
                    When you prepare a dispute, you can review and track it
                    here.
                  </p>
                  <button
                    className="primary"
                    onClick={() => navigate("transactions")}
                  >
                    View transactions <ArrowRight size={16} />
                  </button>
                </div>
              ) : (
                <div className="request-grid">
                  {actions.map((a) => (
                    <section className="panel request-card" key={a.id}>
                      <div className="request-top">
                        <div className="merchant-icon">
                          <FileCheck size={21} />
                        </div>
                        <Pill status={a.status} />
                      </div>
                      <span className="eyebrow">TRANSACTION DISPUTE</span>
                      <h2>{a.payload.merchant}</h2>
                      <div className="request-amount">
                        {money(a.payload.amount_minor, a.payload.currency)}
                      </div>
                      <p>{a.payload.reason}</p>
                      <div className="request-meta">
                        <span>{date(a.created_at)}</span>
                        <span>Account •• {a.payload.last_four}</span>
                      </div>
                      {a.bank_ref && (
                        <div className="bank-ref">
                          <CheckCircle2 size={16} />
                          {a.bank_ref} · Received by demo bank
                        </div>
                      )}
                      {a.status === "awaiting_confirmation" && (
                        <button
                          className="primary full"
                          onClick={() => {
                            setModalError("");
                            setProposal(a);
                            setConfirmKey(crypto.randomUUID());
                          }}
                        >
                          Review and confirm <ArrowRight size={16} />
                        </button>
                      )}
                      {a.status === "manual_review" && (
                        <p className="warning-copy">
                          Submission needs manual reconciliation. Do not submit
                          again.
                        </p>
                      )}
                      {a.status === "failed" && (
                        <p className="warning-copy">
                          The demo bank rejected this request. Contact demo
                          support for help.
                        </p>
                      )}
                      <small className="request-id">{a.id}</small>
                    </section>
                  ))}
                </div>
              )}
              {cases.length > 0 && (
                <section className="panel support-list">
                  <h2>Support cases</h2>
                  {cases.map((c) => (
                    <div key={c.id}>
                      <strong>{c.summary}</strong>
                      <span>
                        {date(c.created_at)} · {c.status}
                      </span>
                      <small>{c.id}</small>
                    </div>
                  ))}
                </section>
              )}
            </>
          )}
          {page === "policies" && (
            <>
              <div className="page-title">
                <div>
                  <div className="eyebrow">KNOW WHERE YOU STAND</div>
                  <h1>Policy library</h1>
                  <p>
                    Approved sample policies, with clear sources and version
                    history.
                  </p>
                </div>
                <span className="synthetic-badge">
                  <BookOpen size={14} />
                  {policies.length} approved documents
                </span>
              </div>
              <div className="policy-grid">
                {policies.map((p, i) => (
                  <article className="panel policy-card" key={p.id}>
                    <div className="policy-index">
                      0{i + 1}
                      <BookOpen size={21} />
                    </div>
                    <h2>{p.title}</h2>
                    <p>{p.content}</p>
                    <footer>
                      <span>
                        <Check size={14} />
                        Approved · {p.version}
                      </span>
                      <span>Effective {date(p.effective_from)}</span>
                    </footer>
                  </article>
                ))}
              </div>
            </>
          )}
          {page === "activity" && (
            <>
              <div className="page-title">
                <div>
                  <div className="eyebrow">TRANSPARENT BY DESIGN</div>
                  <h1>Activity & system</h1>
                  <p>
                    Your audit events and the current development configuration.
                  </p>
                </div>
              </div>
              <div className="system-grid">
                <section className="panel">
                  <h2>Model configuration</h2>
                  <dl>
                    <dt>Chat routing</dt>
                    <dd>{system?.chat_model}</dd>
                    <dt>Policy embeddings</dt>
                    <dd>{system?.embedding_model}</dd>
                    <dt>Vector dimensions</dt>
                    <dd>{system?.embedding_dim}</dd>
                    <dt>Indexed policies</dt>
                    <dd>
                      {system?.policies.indexed} of {system?.policies.total}
                    </dd>
                  </dl>
                  {system?.providers.map((p) => (
                    <div className="provider-row" key={p.provider}>
                      <strong>{p.provider}</strong>
                      <Pill
                        status={p.outcome === "ok" ? "submitted" : "failed"}
                      />
                      <span>Last API attempt</span>
                    </div>
                  ))}
                  <p className="muted">
                    Provider status reflects the most recent API attempt.
                    Configuration alone does not verify connectivity.
                  </p>
                </section>
                <section className="panel">
                  <h2>Your recent audit events</h2>
                  <div className="audit-list">
                    {system?.audit.map((a, i) => (
                      <div key={i}>
                        <div className="audit-dot" />
                        <div>
                          <strong>{a.event.replaceAll(".", " · ")}</strong>
                          <span>{new Date(a.created_at).toLocaleString()}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              </div>
              <div className="trust-card wide">
                <ShieldCheck size={25} />
                <div>
                  <strong>Development boundary</strong>
                  <p>
                    Local synthetic environment with demo login. Production
                    identity, immutable external audit storage, residency
                    review, and operational approval remain rollout
                    requirements.
                  </p>
                </div>
              </div>
            </>
          )}
          <footer className="workspace-footer">
            <span>
              <ShieldCheck size={14} />
              You approve. Aurora assists.
            </span>
            <span>Development workspace · No real banking activity</span>
          </footer>
        </div>
      </main>
      {toast && (
        <div className="toast" role="status">
          <CheckCircle2 size={19} />
          {toast}
          <button
            className="icon-button"
            aria-label="Dismiss notification"
            onClick={() => setToast("")}
          >
            <X size={15} />
          </button>
        </div>
      )}
      {draftTx && (
        <Modal
          title="Tell us about this charge"
          onClose={() => !modalBusy && setDraftTx(null)}
        >
          <form onSubmit={prepare}>
            <div className="review-transaction">
              <div>
                <strong>{draftTx.merchant}</strong>
                <span>
                  {date(draftTx.posted_at)} · Account •• {draftTx.last_four}
                </span>
              </div>
              <strong>
                {money(Math.abs(draftTx.amount_minor), draftTx.currency)}
              </strong>
            </div>
            <label className="field">
              Why do you want to dispute this transaction?
              <textarea
                required
                minLength={10}
                maxLength={1000}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="For example: I do not recognize this purchase and did not authorize it."
              />
            </label>
            <p className="helper">
              Use synthetic details only. You’ll review everything before
              submitting.
            </p>
            {modalError && (
              <p className="form-error" role="alert">
                {modalError}
              </p>
            )}
            <button
              className="primary full"
              disabled={modalBusy || reason.trim().length < 10}
            >
              {modalBusy ? (
                <LoaderCircle size={17} className="spin" />
              ) : (
                <>
                  Prepare for review <ArrowRight size={17} />
                </>
              )}
            </button>
          </form>
        </Modal>
      )}
      {proposal && (
        <Modal
          title="Review your dispute"
          onClose={() => !modalBusy && setProposal(null)}
        >
          <div className="review-notice">
            <ShieldCheck size={21} />
            <p>
              Check these details carefully. Confirming will queue a request
              with the synthetic bank.
            </p>
          </div>
          <dl className="review-details">
            <dt>Merchant</dt>
            <dd>{proposal.payload.merchant}</dd>
            <dt>Amount</dt>
            <dd>
              {money(proposal.payload.amount_minor, proposal.payload.currency)}
            </dd>
            <dt>Account</dt>
            <dd>•• {proposal.payload.last_four}</dd>
            <dt>Your reason</dt>
            <dd>{proposal.payload.reason}</dd>
            <dt>Review expires</dt>
            <dd>{new Date(proposal.expires_at).toLocaleTimeString()}</dd>
          </dl>
          <p className="helper">
            Submitting a dispute does not guarantee a refund. Your request will
            be tracked in Requests.
          </p>
          {modalError && (
            <p className="form-error" role="alert">
              {modalError}
            </p>
          )}
          <div className="modal-actions">
            <button
              className="secondary"
              disabled={modalBusy}
              onClick={() => cancel(proposal)}
            >
              Cancel proposal
            </button>
            <button className="primary" disabled={modalBusy} onClick={confirm}>
              {modalBusy ? (
                <LoaderCircle size={17} className="spin" />
              ) : (
                <>
                  <Check size={17} />
                  Confirm submission
                </>
              )}
            </button>
          </div>
        </Modal>
      )}
      {supportOpen && (
        <Modal
          title="Create a demo support case"
          onClose={() => !modalBusy && setSupportOpen(false)}
        >
          <form onSubmit={handoff}>
            <p className="helper">
              Only the summary below will be shared with the demo support queue.
              No external staff are notified.
            </p>
            <label className="field">
              Summary
              <textarea
                required
                minLength={10}
                maxLength={1000}
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
                placeholder="Describe what you need help with using synthetic details."
              />
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                required
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
              />
              I agree to share this summary with demo support.
            </label>
            {modalError && (
              <p className="form-error" role="alert">
                {modalError}
              </p>
            )}
            <button className="primary full" disabled={modalBusy || !consent}>
              Create support case <ArrowRight size={17} />
            </button>
          </form>
        </Modal>
      )}
    </div>
  );
}

function LoginScreen({
  onLogin,
}: {
  onLogin: (customer: Customer, csrf: string) => void;
}) {
  const [email, setEmail] = useState("ava@demo.bank"),
    [password, setPassword] = useState("DemoBank!2026"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await post<{ customer: Customer; csrf_token: string }>(
        "/login",
        { email, password },
      );
      onLogin(r.customer, r.csrf_token);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login">
      <section className="login-story">
        <Brand />
        <div className="story-main">
          <div className="eyebrow">YOUR BANKING, MADE CLEAR</div>
          <h1>
            Less searching.
            <br />
            More understanding.
          </h1>
          <p>
            A thoughtful assistant for your everyday banking questions. Clear
            answers, useful context, and you in control.
          </p>
          <div className="story-chat">
            <span>
              <Leaf size={18} />
              AURORA ASSISTANT
            </span>
            <p>“I don’t recognize this charge.”</p>
            <div>
              Let’s check the transaction together. You’ll review every detail
              before taking the next step.
            </div>
          </div>
        </div>
        <div className="story-footer">
          <ShieldCheck size={18} />
          Designed around permission, clarity, and trust.
        </div>
        <div className="login-orbit" />
      </section>
      <section className="login-form">
        <div className="login-card">
          <span className="synthetic-badge">
            <span />
            Synthetic development environment
          </span>
          <h2>A clearer view starts here.</h2>
          <p>Sign in to explore your demo banking workspace.</p>
          <form onSubmit={submit}>
            <label className="field">
              Email address
              <input
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label className="field">
              Password
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
            <button className="primary full" disabled={busy}>
              {busy ? (
                <LoaderCircle className="spin" size={18} />
              ) : (
                <>
                  Sign in to workspace <ArrowRight size={18} />
                </>
              )}
            </button>
          </form>
          <div className="demo-accounts">
            <strong>Choose a demo customer</strong>
            <div>
              <button
                className={email === "ava@demo.bank" ? "selected" : ""}
                onClick={() => {
                  setEmail("ava@demo.bank");
                  setPassword("DemoBank!2026");
                }}
              >
                AM <span>Ava Morgan</span>
              </button>
              <button
                className={email === "noah@demo.bank" ? "selected" : ""}
                onClick={() => {
                  setEmail("noah@demo.bank");
                  setPassword("DemoBank!2026");
                }}
              >
                NP <span>Noah Patel</span>
              </button>
            </div>
            <small>
              Both use <code>DemoBank!2026</code>. These are public demo
              credentials.
            </small>
          </div>
          <p className="login-disclaimer">
            <LockKeyhole size={15} />
            All records are fictional. Chat uses Groq and policy search uses
            Voyage. Please do not enter real personal or financial information.
          </p>
        </div>
      </section>
    </div>
  );
}
function Root() {
  const [epoch, setEpoch] = useState(0);
  return (
    <App
      key={epoch}
      onReset={() => {
        csrf = "";
        setEpoch((e) => e + 1);
      }}
    />
  );
}
createRoot(document.getElementById("root")!).render(<Root />);
