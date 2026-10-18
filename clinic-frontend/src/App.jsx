import { useState } from "react";
import "./App.css";
const initialHandoffs = [
  {
    id: "cv_4471",
    caller: '"Seene mein dard ho raha hai"',
    reason: "CLINICAL",
    type: "clinical",
    time: "11:42",
  },
  {
    id: "cv_4468",
    caller: "Cancel for a different patient",
    reason: "NOT AUTHORISED",
    type: "unauthorised",
    time: "11:20",
  },
  {
    id: "cv_4463",
    caller: '"Sharma ji ke liye" — 3 matches',
    reason: "AMBIGUOUS PATIENT",
    type: "ambiguous",
    time: "10:57",
  },
  {
    id: "cv_4455",
    caller: '"Ye dawai lun ya nahi?"',
    reason: "MEDICAL ADVICE",
    type: "medical",
    time: "10:18",
  },
];

const transcript = [
  {
    role: "CALLER",
    type: "caller",
    text: "Kal subah ka appointment mil jayega Dr. Rao ke saath?",
  },
  {
    role: "TOOL",
    type: "tool",
    code: 'search_slots(doctor_id="d_rao", date="2026-09-28", window="morning")',
    result: "→ 3 slots: 09:30, 10:15, 11:00",
  },
  {
    role: "AGENT",
    type: "agent",
    text: "Ji, kal subah 9:30, 10:15 aur 11:00 khali hai. Kaun sa theek rahega?",
  },
  {
    role: "CALLER",
    type: "caller",
    text: "10:15 kar dijiye. Waise abhi seene mein dard ho raha hai thoda.",
  },
  {
    role: "TOOL",
    type: "tool",
    code: 'escalate_to_human(reason="clinical_urgent",',
    result: 'detail="caller reports active chest pain")',
  },
  {
    role: "AGENT",
    type: "agent",
    text: "Main abhi aapko clinic se connect kar rahi hoon. Agar dard badh raha hai, turant nazdeeki emergency par jaiye.",
  },
];

const outcome = [
  ["terminal_state", "escalated"],
  ["escalation_reason", "clinical_urgent"],
  ["patient_id", "pt_0192"],
  ["appointment_id", "null"],
  ["tool_calls", "2"],
  ["turns", "6"],
  ["tokens", "3,140"],
  ["latency", "4.2 s"],
];

function Sidebar({ screen, setScreen }) {
  return (
    <aside className="sidebar">
      <nav className="nav-items" aria-label="Main navigation">
        {[1, 2, 3, 4, 5, 6, 7].map((item) => (
          <button
            key={item}
            type="button"
            className={`nav-dot ${
              (screen === "queue" && item === 3) ||
              (screen === "detail" && item === 3)
                ? "active"
                : ""
            }`}
            aria-label={
              item === 3 ? "Handoff Queue" : `Navigation item ${item}`
            }
            title={item === 3 ? "Handoff Queue" : "Conversation Detail"}
            onClick={() =>
              setScreen((current) =>
                current === "queue" ? "detail" : "queue"
              )
            }
          >
            <span />
          </button>
        ))}
      </nav>
    </aside>
  );
}

function HandoffQueue({ handoffs, onResolve, onOpen }) {
  return (
    <>
      <header className="page-header">
        <h1>1. Handoff Queue</h1>
      </header>

      <section className="queue-panel">
        <div className="panel-heading">
          <div>
            <h2>Handoff Queue</h2>
            <p>
              Sunrise Clinic, Dehradun — conversations the agent escalated
            </p>
          </div>
          <span className="open-count">{handoffs.length} OPEN</span>
        </div>

        <section className="metrics">
          <article className="metric-card">
            <p className="metric-label">CONVERSATIONS</p>
            <p className="metric-value">37</p>
            <p className="metric-note">today</p>
          </article>
          <article className="metric-card">
            <p className="metric-label">COMPLETED BY AGENT</p>
            <p className="metric-value">31</p>
            <p className="metric-note">84%</p>
          </article>
          <article className="metric-card">
            <p className="metric-label">ESCALATED</p>
            <p className="metric-value">6</p>
            <p className="metric-note blue-note">
              {handoffs.length} still open
            </p>
          </article>
          <article className="metric-card">
            <p className="metric-label">URGENT</p>
            <p className="metric-value">1</p>
            <p className="metric-note urgent-note">
              clinical, unresolved
            </p>
          </article>
        </section>

        <section className="handoff-card">
          <h3>Open handoffs</h3>

          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>CONVERSATION</th>
                  <th>CALLER SAID</th>
                  <th>REASON</th>
                  <th>TIME</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {handoffs.map((item) => (
                  <tr key={item.id}>
                    <td className="conversation-id">{item.id}</td>
                    <td className="caller-text">{item.caller}</td>
                    <td>
                      <span className={`reason-badge ${item.type}`}>
                        {item.reason}
                      </span>
                    </td>
                    <td className="time-cell">{item.time}</td>
                    <td className="action-cell">
                      <button
                        type="button"
                        className={`resolve-button ${
                          item.id === "cv_4471" ? "primary" : ""
                        }`}
                        onClick={() => onResolve(item.id)}
                      >
                        Resolve
                      </button>
                      <button
                        type="button"
                        className="view-button"
                        onClick={() => onOpen(item.id)}
                      >
                        View
                      </button>
                    </td>
                  </tr>
                ))}
                {handoffs.length === 0 && (
                  <tr>
                    <td colSpan="5" className="empty-state">
                      All handoffs resolved.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </section>

      <footer className="page-caption">
        Counters across the top, then the open handoffs the agent escalated,
        each with what the caller said, the reason, and a way to resolve it.
      </footer>
    </>
  );
}

function ConversationDetail({ onBack }) {
  return (
    <div className="detail-screen">
      <header className="detail-header">
        <div>
          <h1>Conversation cv_4471</h1>
          <p>Sunrise Clinic, Dehradun — 27 Sep 2026, 11:42</p>
        </div>
        <span className="escalation-status">ESCALATED — CLINICAL</span>
      </header>

      <div className="detail-grid">
        <section className="transcript-panel">
          <h2>Transcript and tool calls</h2>

          <div className="transcript">
            {transcript.map((entry, index) => (
              <div className={`transcript-row ${entry.type}`} key={index}>
                <div className="transcript-role">{entry.role}</div>
                {entry.type === "tool" ? (
                  <div className="tool-block">
                    <code>{entry.code}</code>
                    <code>{entry.result}</code>
                  </div>
                ) : (
                  <div className="message-bubble">{entry.text}</div>
                )}
              </div>
            ))}
            <div className="booking-abandoned">
              Booking flow abandoned. No appointment was created.
            </div>
          </div>
        </section>

        <aside className="outcome-panel">
          <h2>Outcome</h2>
          <dl className="outcome-list">
            {outcome.map(([key, value]) => (
              <div className="outcome-row" key={key}>
                <dt>{key}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>

          <div className="determinism">
            <p className="section-label">DETERMINISM</p>
            <div className="determinism-result">
              <span>Same terminal state across 3 runs.</span>
              <span className="stable-badge">STABLE</span>
            </div>
          </div>
        </aside>
      </div>

      <button className="back-button" onClick={onBack} type="button">
        ← Back to Handoff Queue
      </button>
    </div>
  );
}

export default function App() {
  const [screen, setScreen] = useState("queue");
  const [handoffs, setHandoffs] = useState(initialHandoffs);
  const [selectedId, setSelectedId] = useState("cv_4471");

  function openConversation(id) {
    setSelectedId(id);
    setScreen("detail");
  }

  function resolveHandoff(id) {
    setHandoffs((current) => current.filter((item) => item.id !== id));
  }

  return (
    <main className="app-shell">
      <Sidebar screen={screen} setScreen={setScreen} />
      <section className="dashboard">
        {screen === "queue" ? (
          <HandoffQueue
            handoffs={handoffs}
            onResolve={resolveHandoff}
            onOpen={openConversation}
          />
        ) : (
          <ConversationDetail
            key={selectedId}
            onBack={() => setScreen("queue")}
          />
        )}
      </section>
    </main>
  );
}

