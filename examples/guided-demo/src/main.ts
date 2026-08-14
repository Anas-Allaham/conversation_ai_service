import { Room, RoomEvent, Track } from "livekit-client";

import "./style.css";

type Level = "A1" | "A2" | "B1" | "B2";
type GuidedState =
  | "assistant_speaking"
  | "user_prompt_visible"
  | "awaiting_retry_decision"
  | "paused"
  | "completed"
  | "stopped";

interface ScenarioSummary {
  scenario_id: string;
  domain_id: string;
  domain_title: string;
  title: string;
  required_level: Level;
  estimated_minutes: number;
  is_locked: boolean;
  lock_reason: string | null;
}

interface DomainSummary {
  domain_id: string;
  title: string;
  description: string;
  scenario_count: number;
  available_scenario_count: number;
  scenarios: ScenarioSummary[];
}

interface GuidedTurn {
  turn_id: string;
  turn_number: number;
  total_turns: number;
  assistant_display_text: string;
  learner_display_text: string;
  arabic_hint: string | null;
}

interface GuidedSession {
  session_id: string;
  status: "in_progress" | "completed" | "stopped";
  state: GuidedState;
  domain_id: string;
  domain_title: string;
  scenario_title: string;
  scenario_level: Level;
  current_turn: GuidedTurn | null;
  completed_turns: number;
  total_turns: number;
  retries: number;
  allowed_actions: string[];
}

interface Bootstrap {
  practice_session_id: string;
  mode: "guided";
  server_url: string;
  participant_token: string;
  result_url: string;
  guided_session: GuidedSession;
}

interface WordFeedback {
  text: string;
  recognition_confidence_percent: number | null;
  color_band: "red" | "orange" | "white";
}

interface ConversationTurnFeedback {
  attempt_id: string;
  turn_id: string;
  assistant_text: string;
  expected_learner_text: string;
  learner_transcript: string;
  words: WordFeedback[];
  recognition_confidence_interpretation: string;
}

interface GuidedEvent {
  type: string;
  data: Record<string, unknown>;
}

interface HistoryEntry {
  key: string;
  role: "assistant" | "learner";
  text: string;
  words?: WordFeedback[];
}

const app = document.querySelector<HTMLElement>("#app");
if (!app) throw new Error("App element was not found");

app.innerHTML = `
  <section class="shell">
    <header>
      <p class="eyebrow">Real-Time English Tutor · 0.6.0</p>
      <h1>Guided conversation test</h1>
      <p class="intro">Choose a domain, select a level-approved scenario, and keep the complete conversation visible while you practise.</p>
    </header>

    <section class="setup card">
      <label>User ID <input id="user-id" value="local-test-user" /></label>
      <label>Placement level
        <select id="level"><option>A1</option><option>A2</option><option>B1</option><option>B2</option></select>
      </label>
      <label>Domain <select id="domain"></select></label>
      <label>Scenario <select id="scenario"></select></label>
      <button id="start" class="primary">Start guided conversation</button>
      <p id="status" class="status" aria-live="polite">Loading domains…</p>
    </section>

    <section id="conversation" class="card hidden" aria-live="polite">
      <div class="progress-row"><span id="scenario-title"></span><span id="progress"></span></div>
      <h2 class="conversation-heading">Conversation</h2>
      <div id="history" class="history" aria-label="Complete conversation history"></div>
      <div id="next-turn" class="next-turn">
        <div class="line character"><span>Character</span><p id="character-line"></p></div>
        <div class="line learner"><span>Your next line</span><p id="learner-line"></p><p id="arabic-hint" lang="ar"></p></div>
      </div>
      <div class="controls">
        <button data-command="replay">Replay character</button>
        <button data-command="replay_slow">Play slowly</button>
        <button data-command="retry">Retry</button>
        <button data-command="continue">Continue</button>
        <button data-command="pause">Pause</button>
        <button data-command="resume">Resume</button>
        <button data-command="stop" class="danger">Stop</button>
      </div>
      <p class="confidence-legend"><span class="legend white"></span>75–100% <span class="legend orange"></span>25–74% <span class="legend red"></span>0–24% STT recognition confidence</p>
      <p class="microphone">These colors debug what speech recognition trusted; they are not pronunciation grades.</p>
      <div class="end-actions">
        <button id="repeat-all" class="hidden">Replay full conversation</button>
        <button id="report" class="primary hidden">View result and debug details</button>
      </div>
    </section>

    <section id="result" class="card hidden"><h2>Session result</h2><div id="result-body"></div></section>
    <audio id="agent-audio" autoplay></audio>
  </section>
`;

const elements = {
  userId: document.querySelector<HTMLInputElement>("#user-id")!,
  level: document.querySelector<HTMLSelectElement>("#level")!,
  domain: document.querySelector<HTMLSelectElement>("#domain")!,
  scenario: document.querySelector<HTMLSelectElement>("#scenario")!,
  start: document.querySelector<HTMLButtonElement>("#start")!,
  status: document.querySelector<HTMLElement>("#status")!,
  conversation: document.querySelector<HTMLElement>("#conversation")!,
  scenarioTitle: document.querySelector<HTMLElement>("#scenario-title")!,
  progress: document.querySelector<HTMLElement>("#progress")!,
  history: document.querySelector<HTMLElement>("#history")!,
  nextTurn: document.querySelector<HTMLElement>("#next-turn")!,
  characterLine: document.querySelector<HTMLElement>("#character-line")!,
  learnerLine: document.querySelector<HTMLElement>("#learner-line")!,
  arabicHint: document.querySelector<HTMLElement>("#arabic-hint")!,
  repeatAll: document.querySelector<HTMLButtonElement>("#repeat-all")!,
  report: document.querySelector<HTMLButtonElement>("#report")!,
  result: document.querySelector<HTMLElement>("#result")!,
  resultBody: document.querySelector<HTMLElement>("#result-body")!,
  audio: document.querySelector<HTMLAudioElement>("#agent-audio")!,
};

let room: Room | null = null;
let bootstrap: Bootstrap | null = null;
let domains: DomainSummary[] = [];
let history: HistoryEntry[] = [];
const historyKeys = new Set<string>();
const encoder = new TextEncoder();
const decoder = new TextDecoder();

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function backend<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/backend${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed with HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function renderScenarioOptions(): void {
  const domain = domains.find((item) => item.domain_id === elements.domain.value);
  const scenarios = domain?.scenarios ?? [];
  elements.scenario.innerHTML = scenarios
    .map(
      (scenario) =>
        `<option value="${escapeHtml(scenario.scenario_id)}" ${scenario.is_locked ? "disabled" : ""}>${escapeHtml(scenario.title)} · ${scenario.required_level} · ${scenario.estimated_minutes} min${scenario.is_locked ? ` · ${escapeHtml(scenario.lock_reason)}` : ""}</option>`,
    )
    .join("");
}

async function loadDomains(): Promise<void> {
  elements.status.textContent = "Loading domains…";
  const level = elements.level.value as Level;
  domains = await backend<DomainSummary[]>(
    `/v1/guided-conversations/domains?placement_completed=true&placement_level=${level}`,
  );
  elements.domain.innerHTML = domains
    .map(
      (domain) =>
        `<option value="${escapeHtml(domain.domain_id)}">${escapeHtml(domain.title)} · ${domain.available_scenario_count}/${domain.scenario_count} available</option>`,
    )
    .join("");
  renderScenarioOptions();
  const available = domains.reduce((sum, domain) => sum + domain.available_scenario_count, 0);
  elements.status.textContent = `${available} scenario${available === 1 ? "" : "s"} available for ${level}.`;
}

function extractSession(event: GuidedEvent): GuidedSession | null {
  const nested = event.data.session as GuidedSession | undefined;
  if (nested?.session_id) return nested;
  const direct = event.data as unknown as GuidedSession;
  return direct.session_id ? direct : null;
}

function addHistory(entry: HistoryEntry): void {
  if (historyKeys.has(entry.key)) return;
  historyKeys.add(entry.key);
  history.push(entry);
  renderHistory();
}

function wordMarkup(word: WordFeedback): string {
  const confidence = word.recognition_confidence_percent;
  const title = confidence === null ? "Recognition confidence unavailable" : `Recognition confidence: ${confidence}%`;
  return `<span class="spoken-word ${word.color_band}" title="${escapeHtml(title)}">${escapeHtml(word.text)}</span>`;
}

function renderHistory(): void {
  elements.history.innerHTML = history
    .map((entry) => {
      const body = entry.words?.length
        ? entry.words.map(wordMarkup).join(" ")
        : escapeHtml(entry.text);
      return `<article class="message ${entry.role}"><span>${entry.role === "assistant" ? "Tutor" : "You"}</span><p>${body}</p></article>`;
    })
    .join("");
  elements.history.scrollTop = elements.history.scrollHeight;
}

function ensureCurrentAssistant(session: GuidedSession): void {
  const turn = session.current_turn;
  if (!turn) return;
  addHistory({
    key: `assistant:${turn.turn_id}`,
    role: "assistant",
    text: turn.assistant_display_text,
  });
}

function captureConversationEvent(event: GuidedEvent, session: GuidedSession | null): void {
  const feedback = event.data.conversation_turn as ConversationTurnFeedback | undefined;
  if (feedback?.attempt_id) {
    addHistory({
      key: `learner:${feedback.attempt_id}`,
      role: "learner",
      text: feedback.learner_transcript,
      words: feedback.words,
    });
  }
  const reply = String(event.data.assistant_reply || "").trim();
  const shouldAddReply =
    reply &&
    (event.type !== "guided.turn_evaluated" ||
      Boolean(event.data.retry_recommended) ||
      session?.status !== "in_progress");
  if (shouldAddReply) {
    addHistory({
      key: `assistant-reply:${event.type}:${feedback?.attempt_id ?? history.length}`,
      role: "assistant",
      text: reply,
    });
  }
}

function renderSession(session: GuidedSession): void {
  const turn = session.current_turn;
  elements.conversation.classList.remove("hidden");
  elements.scenarioTitle.textContent = `${session.domain_title} · ${session.scenario_title}`;
  elements.progress.textContent = `${session.completed_turns}/${session.total_turns} complete`;
  elements.characterLine.textContent = turn?.assistant_display_text || "Scenario finished.";
  elements.learnerLine.textContent = turn?.learner_display_text || "";
  elements.arabicHint.textContent = turn?.arabic_hint || "";
  elements.arabicHint.classList.toggle("hidden", !turn?.arabic_hint);
  elements.nextTurn.classList.toggle("hidden", !turn);
  ensureCurrentAssistant(session);
  document.querySelectorAll<HTMLButtonElement>("[data-command]").forEach((button) => {
    const command = button.dataset.command || "";
    button.disabled = !session.allowed_actions.includes(command);
  });
  const finished = session.status !== "in_progress";
  elements.report.classList.toggle("hidden", !finished);
  elements.repeatAll.classList.toggle("hidden", !finished);
  if (session.state === "paused") elements.status.textContent = "Conversation paused. Your microphone is off.";
  if (finished) elements.status.textContent = "Conversation ended. The live session is closing cleanly.";
}

async function startGuided(): Promise<void> {
  elements.start.disabled = true;
  elements.status.textContent = "Creating guided session…";
  history = [];
  historyKeys.clear();
  renderHistory();
  elements.result.classList.add("hidden");
  try {
    bootstrap = await backend<Bootstrap>("/v1/practice-sessions", {
      method: "POST",
      body: JSON.stringify({
        user_id: elements.userId.value.trim() || "local-test-user",
        participant_name: "Guided Demo Learner",
        mode: "guided",
        scenario_id: elements.scenario.value,
        placement_completed: true,
        placement_level: elements.level.value,
        interface_language: "en",
        confidence_before: 50,
        recording_consent: false,
      }),
    });
    renderSession(bootstrap.guided_session);
    room = new Room();
    room.on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === Track.Kind.Audio) track.attach(elements.audio);
    });
    room.on(RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
      if (topic !== "guided.events") return;
      const event = JSON.parse(decoder.decode(payload)) as GuidedEvent;
      const next = extractSession(event);
      captureConversationEvent(event, next);
      if (next) renderSession(next);
      if (event.type === "guided.session_closed") {
        void room?.localParticipant.setMicrophoneEnabled(false);
        void room?.disconnect();
        elements.start.disabled = false;
        elements.status.textContent = "Guided session closed. The worker is ready for another user.";
      } else if (next?.state !== "paused") {
        elements.status.textContent = event.type.replaceAll(".", " · ");
      }
    });
    room.on(RoomEvent.Disconnected, () => {
      elements.start.disabled = false;
      if (!elements.report.classList.contains("hidden")) {
        elements.status.textContent = "Guided session closed. You can inspect or replay it below.";
      } else {
        elements.status.textContent = "LiveKit disconnected before the scenario finished.";
      }
    });
    await room.connect(bootstrap.server_url, bootstrap.participant_token);
    await room.localParticipant.setMicrophoneEnabled(true);
    elements.status.textContent = "Connected. Listen, then say the displayed learner line.";
  } catch (error) {
    elements.status.textContent = error instanceof Error ? error.message : String(error);
    elements.start.disabled = false;
  }
}

async function sendCommand(command: string): Promise<void> {
  if (!room) return;
  if (command === "pause") await room.localParticipant.setMicrophoneEnabled(false);
  await room.localParticipant.publishData(encoder.encode(JSON.stringify({ command })), {
    reliable: true,
    topic: "guided.command",
  });
  if (command === "resume") await room.localParticipant.setMicrophoneEnabled(true);
}

function repeatConversation(): void {
  if (!("speechSynthesis" in window) || !history.length) {
    elements.status.textContent = "Full-conversation replay is unavailable in this browser.";
    return;
  }
  window.speechSynthesis.cancel();
  elements.status.textContent = "Replaying the complete conversation from the visible history…";
  history.forEach((entry, index) => {
    const utterance = new SpeechSynthesisUtterance(entry.text);
    utterance.lang = "en-US";
    utterance.pitch = entry.role === "assistant" ? 1.05 : 0.95;
    utterance.rate = 0.92;
    if (index === history.length - 1) {
      utterance.onend = () => {
        elements.status.textContent = "Full-conversation replay finished.";
      };
    }
    window.speechSynthesis.speak(utterance);
  });
}

async function showReport(): Promise<void> {
  if (!bootstrap) return;
  const envelope = await backend<any>(bootstrap.result_url);
  const report = envelope.result;
  const fluency = report.guided_speaking_fluency;
  const evidence = fluency.evidence_count;
  const scores = fluency.subscores;
  const debug = report.result_debug;
  const threshold = debug.thresholds;
  const diagnosticRows = debug.lines
    .map(
      (line: any) => `<tr>
        <td>${line.line_number}</td><td>${line.eligible ? "Included" : "Excluded"}</td>
        <td>${line.timed_word_count}/${line.expected_word_count}</td>
        <td>${Number(line.response_duration_seconds).toFixed(2)} s</td>
        <td>${escapeHtml(line.timing_source)}</td>
        <td>${line.asr_confidence_percent ?? "—"}${line.asr_confidence_percent === null ? "" : "%"}</td>
        <td>${escapeHtml(line.insufficiency_reasons.join(" ") || "—")}</td>
      </tr>`,
    )
    .join("");
  elements.resultBody.innerHTML = `
    <div class="metrics">
      <article><span>Fluency index</span><strong>${fluency.fluency_index ?? "Not enough evidence"}</strong></article>
      <article><span>Evidence confidence</span><strong>${escapeHtml(fluency.confidence)}</strong></article>
      <article><span>Eligible lines</span><strong>${evidence.eligible_turns}/${evidence.total_turns}</strong></article>
      <article><span>Learner speech</span><strong>${evidence.learner_speech_seconds.toFixed(1)} s</strong></article>
      <article><span>Delivery</span><strong>${escapeHtml(report.delivery_stability.label.replaceAll("_", " "))}</strong></article>
      <article><span>Retries</span><strong>${report.delivery_stability.total_retries}</strong></article>
    </div>
    ${scores ? `<div class="subscores"><span>Speed ${scores.speed}</span><span>Breakdown ${scores.breakdown}</span><span>Continuity ${scores.continuity}</span><span>Repair ${scores.repair}</span></div>` : ""}
    <h3>Feedback</h3>
    <ul>${fluency.feedback.map((item: string) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
    <details class="debug" open>
      <summary>Why did I get this result?</summary>
      <p>${escapeHtml(debug.summary)}</p>
      <p class="note">Guided thresholds: at least ${threshold.minimum_timed_words_per_line} timed words and ${threshold.minimum_timed_seconds_per_line.toFixed(1)} s per line; then ${threshold.minimum_eligible_lines} eligible lines, with a target of ${threshold.target_eligible_lines} lines or ${threshold.minimum_speech_seconds_when_below_target.toFixed(0)} s.</p>
      <div class="table-wrap"><table><thead><tr><th>Line</th><th>Decision</th><th>Timed/expected words</th><th>Duration</th><th>Timing</th><th>ASR confidence</th><th>Reason</th></tr></thead><tbody>${diagnosticRows}</tbody></table></div>
      <ul>${debug.guidance.map((item: string) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
    </details>
    <p class="note">CEFR result: none. Guided practice never changes placement.</p>
  `;
  elements.result.classList.remove("hidden");
  elements.result.scrollIntoView({ behavior: "smooth" });
}

elements.level.addEventListener("change", () => void loadDomains());
elements.domain.addEventListener("change", renderScenarioOptions);
elements.start.addEventListener("click", () => void startGuided());
elements.report.addEventListener("click", () => void showReport());
elements.repeatAll.addEventListener("click", repeatConversation);
document.querySelectorAll<HTMLButtonElement>("[data-command]").forEach((button) => {
  button.addEventListener("click", () => void sendCommand(button.dataset.command || ""));
});

void loadDomains().catch((error) => {
  elements.status.textContent = error instanceof Error ? error.message : String(error);
});
