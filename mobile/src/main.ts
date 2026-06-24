import './style.css';
import { allQuestions, bankCount, listCategories, listTopics, scoreQuiz, startQuiz } from './quiz';
import { exportDatabase, importDatabasePayload, listSessions, saveSession, storedQuestions } from './storage';
import type { Quiz, QuizOptions, QuizResponse, ScoreResult } from './types';

type View = 'setup' | 'quiz' | 'result' | 'history';

const app = document.querySelector<HTMLDivElement>('#app');
if (!app) throw new Error('App root not found');
const appRoot = app;

const state: {
  categories: string[];
  topics: string[];
  options: QuizOptions;
  quiz: Quiz | null;
  current: number;
  answers: Record<string, number | null>;
  questionEnterMs: number;
  timeSpent: Record<string, number>;
  remainingSeconds: number;
  timer: number | null;
  result: ScoreResult | null;
  view: View;
} = {
  categories: [],
  topics: [],
  options: {
    category: 'All',
    difficulty: 'All',
    topics: [],
    num_questions: 10,
    duration_minutes: 15,
  },
  quiz: null,
  current: 0,
  answers: {},
  questionEnterMs: Date.now(),
  timeSpent: {},
  remainingSeconds: 0,
  timer: null,
  result: null,
  view: 'setup',
};

function escapeHtml(value: unknown): string {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function optionHtml(value: string, label = value): string {
  return `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`;
}

function secondsLabel(total: number): string {
  const minutes = Math.floor(total / 60).toString().padStart(2, '0');
  const seconds = Math.floor(total % 60).toString().padStart(2, '0');
  return `${minutes}:${seconds}`;
}

function setupShell(): void {
  appRoot.innerHTML = `
    <main class="app-shell">
      <header class="topbar">
        <div>
          <p class="eyebrow">SSC CGL Buddy</p>
          <h1>Practice kit</h1>
        </div>
        <button id="history-btn" class="ghost" type="button">History</button>
      </header>
      <section id="screen"></section>
    </main>
  `;
  document.querySelector('#history-btn')?.addEventListener('click', async () => {
    stopTimer();
    await renderHistory();
  });
}

function stopTimer(): void {
  if (state.timer !== null) window.clearInterval(state.timer);
  state.timer = null;
}

function persistCurrentTime(): void {
  const question = state.quiz?.questions[state.current];
  if (!question) return;
  const elapsed = Math.max(0, Math.round((Date.now() - state.questionEnterMs) / 1000));
  state.timeSpent[question.id] = (state.timeSpent[question.id] || 0) + elapsed;
  state.questionEnterMs = Date.now();
}

function render(): void {
  if (!document.querySelector('#screen')) setupShell();
  if (state.view === 'setup') renderSetup();
  if (state.view === 'quiz') renderQuiz();
  if (state.view === 'result') renderResult();
}

function setView(view: View): void {
  state.view = view;
  render();
}

async function refreshSetupData(): Promise<void> {
  state.categories = await listCategories();
  state.topics = await listTopics(state.options.category);
  const count = await bankCount(state.options);
  const total = (await allQuestions()).length;
  const userCount = (await storedQuestions()).length;
  renderSetupControlsOnly();
  const countEl = document.querySelector<HTMLElement>('#bank-count');
  if (countEl) {
    countEl.textContent = `${count} match${count === 1 ? '' : 'es'} / ${total} total (${userCount} imported)`;
  }
}

function renderSetupControlsOnly(): void {
  const category = document.querySelector<HTMLSelectElement>('#category');
  const topicList = document.querySelector<HTMLElement>('#topics-list');
  if (category) {
    category.innerHTML = state.categories.map((item) => optionHtml(item, item === 'All' ? 'All subjects' : item)).join('');
    category.value = state.options.category;
  }
  if (topicList) {
    topicList.innerHTML = state.topics.length ? state.topics.map((topic) => `
      <label class="topic-chip">
        <input type="checkbox" value="${escapeHtml(topic)}" ${state.options.topics.includes(topic) ? 'checked' : ''}>
        <span>${escapeHtml(topic)}</span>
      </label>
    `).join('') : '<p class="hint">Choose a subject to filter by topic.</p>';
    topicList.querySelectorAll<HTMLInputElement>('input').forEach((input) => {
      input.addEventListener('change', async () => {
        state.options.topics = [...topicList.querySelectorAll<HTMLInputElement>('input:checked')].map((item) => item.value);
        await refreshSetupData();
      });
    });
  }
}

function renderSetup(): void {
  stopTimer();
  const screen = document.querySelector<HTMLElement>('#screen');
  if (!screen) return;
  screen.innerHTML = `
    <section class="panel setup-grid">
      <div class="setup-main">
        <h2>Build a quiz</h2>
        <p class="hint">Uses the same <code>data/mcq_bank.json</code> schema as desktop. Imported JSON databases stay compatible both ways.</p>
        <div class="form-grid">
          <label>Subject<select id="category"></select></label>
          <label>Difficulty<select id="difficulty">
            ${['All', 'easy', 'medium', 'hard'].map((item) => optionHtml(item)).join('')}
          </select></label>
          <label>Questions<input id="num" type="number" min="1" max="50" value="${state.options.num_questions}"></label>
          <label>Minutes<input id="duration" type="number" min="1" max="180" value="${state.options.duration_minutes}"></label>
        </div>
        <div class="topics-head">
          <span>Topics</span>
          <span id="bank-count" class="hint">Loading...</span>
        </div>
        <div id="topics-list" class="topics-list"></div>
        <button id="start" class="primary" type="button">Start quiz</button>
      </div>
      <aside class="db-card">
        <h2>Portable JSON DB</h2>
        <p class="hint">Import/export the same <code>cgl-buddy-mcq-db</code> format used by desktop.</p>
        <input id="db-file" type="file" accept="application/json,.json">
        <div class="button-row">
          <button id="import-db" type="button">Import JSON</button>
          <button id="export-db" type="button">Export JSON</button>
        </div>
        <p id="db-status" class="hint"></p>
      </aside>
    </section>
  `;
  const category = document.querySelector<HTMLSelectElement>('#category');
  const difficulty = document.querySelector<HTMLSelectElement>('#difficulty');
  const num = document.querySelector<HTMLInputElement>('#num');
  const duration = document.querySelector<HTMLInputElement>('#duration');
  if (difficulty) difficulty.value = state.options.difficulty;
  category?.addEventListener('change', async () => {
    state.options.category = category.value;
    state.options.topics = [];
    await refreshSetupData();
  });
  difficulty?.addEventListener('change', async () => {
    state.options.difficulty = difficulty.value as QuizOptions['difficulty'];
    await refreshSetupData();
  });
  num?.addEventListener('change', () => {
    state.options.num_questions = Math.max(1, Math.min(50, Number(num.value) || 10));
  });
  duration?.addEventListener('change', () => {
    state.options.duration_minutes = Math.max(1, Math.min(180, Number(duration.value) || 15));
  });
  document.querySelector('#start')?.addEventListener('click', beginQuiz);
  document.querySelector('#import-db')?.addEventListener('click', importDbFromInput);
  document.querySelector('#export-db')?.addEventListener('click', exportDbToFile);
  void refreshSetupData();
}

async function beginQuiz(): Promise<void> {
  state.quiz = await startQuiz(state.options);
  if (!state.quiz.questions.length) {
    const status = document.querySelector<HTMLElement>('#db-status');
    if (status) status.textContent = 'No questions found for those filters.';
    return;
  }
  state.current = 0;
  state.answers = {};
  state.timeSpent = {};
  state.remainingSeconds = state.quiz.duration_minutes * 60;
  state.questionEnterMs = Date.now();
  state.result = null;
  state.view = 'quiz';
  startTimer();
  renderQuiz();
}

function startTimer(): void {
  stopTimer();
  state.timer = window.setInterval(() => {
    state.remainingSeconds -= 1;
    const timer = document.querySelector<HTMLElement>('#timer');
    if (timer) timer.textContent = secondsLabel(Math.max(0, state.remainingSeconds));
    if (state.remainingSeconds <= 0) void submitQuiz();
  }, 1000);
}

function renderQuiz(): void {
  const screen = document.querySelector<HTMLElement>('#screen');
  const quiz = state.quiz;
  if (!screen || !quiz) return;
  const question = quiz.questions[state.current];
  const selected = state.answers[question.id] ?? null;
  screen.innerHTML = `
    <section class="panel quiz-panel">
      <div class="quiz-meta">
        <span>Question ${state.current + 1} of ${quiz.questions.length}</span>
        <strong id="timer">${secondsLabel(Math.max(0, state.remainingSeconds))}</strong>
      </div>
      ${quiz.warnings.length ? `<div class="warning">${quiz.warnings.map(escapeHtml).join('<br>')}</div>` : ''}
      <h2>${escapeHtml(question.question)}</h2>
      <p class="hint">${escapeHtml(question.subject)}${question.topic ? ` · ${escapeHtml(question.topic)}` : ''}</p>
      <div class="options">
        ${question.options.map((option, index) => `
          <button class="option ${selected === index ? 'selected' : ''}" data-index="${index}" type="button">
            <span>${String.fromCharCode(65 + index)}</span>${escapeHtml(option)}
          </button>
        `).join('')}
      </div>
      <div class="quiz-actions">
        <button id="prev" type="button" ${state.current === 0 ? 'disabled' : ''}>Previous</button>
        <button id="clear" type="button">Clear</button>
        <button id="next" type="button">${state.current === quiz.questions.length - 1 ? 'Review' : 'Next'}</button>
        <button id="submit" class="primary" type="button">Submit</button>
      </div>
    </section>
  `;
  document.querySelectorAll<HTMLButtonElement>('.option').forEach((button) => {
    button.addEventListener('click', () => {
      state.answers[question.id] = Number(button.dataset.index);
      renderQuiz();
    });
  });
  document.querySelector('#prev')?.addEventListener('click', () => moveQuestion(-1));
  document.querySelector('#next')?.addEventListener('click', () => moveQuestion(1));
  document.querySelector('#clear')?.addEventListener('click', () => {
    state.answers[question.id] = null;
    renderQuiz();
  });
  document.querySelector('#submit')?.addEventListener('click', () => void submitQuiz());
}

function moveQuestion(delta: number): void {
  if (!state.quiz) return;
  persistCurrentTime();
  state.current = Math.max(0, Math.min(state.quiz.questions.length - 1, state.current + delta));
  state.questionEnterMs = Date.now();
  renderQuiz();
}

async function submitQuiz(): Promise<void> {
  const quiz = state.quiz;
  if (!quiz) return;
  persistCurrentTime();
  stopTimer();
  const responses: QuizResponse[] = quiz.questions.map((question) => ({
    id: question.id,
    selected_index: state.answers[question.id] ?? null,
    time_spent_seconds: state.timeSpent[question.id] || 0,
  }));
  state.result = scoreQuiz(quiz.answer_key, responses);
  await saveSession({
    mode: 'bank',
    subject: state.options.category,
    topics: state.options.topics,
    difficulty: state.options.difficulty,
    duration_minutes: state.options.duration_minutes,
    score: state.result.score,
    total: state.result.total,
    accuracy: state.result.accuracy,
    attempted: state.result.attempted,
    skipped: state.result.skipped,
    time_taken_seconds: state.result.total_time_seconds,
    avg_time_seconds: state.result.avg_time_seconds,
    category_accuracy: state.result.category_accuracy,
    difficulty_accuracy: state.result.difficulty_accuracy,
    topic_accuracy: state.result.topic_accuracy,
    questions: state.result.review.map((item) => ({
      question: item.question,
      options: item.options,
      correct_index: item.correct_index,
      selected_index: item.selected_index,
      is_correct: item.is_correct,
      attempted: item.attempted,
      subject: item.subject,
      topic: item.topic,
      difficulty: item.difficulty,
      explanation: item.explanation,
      time_spent_seconds: item.time_spent_seconds,
    })),
  });
  setView('result');
}

function renderResult(): void {
  const screen = document.querySelector<HTMLElement>('#screen');
  const result = state.result;
  if (!screen || !result) return;
  screen.innerHTML = `
    <section class="panel result-panel">
      <div class="score-card">
        <p class="eyebrow">Result</p>
        <h2>${result.score}/${result.total}</h2>
        <p>${result.accuracy}% accuracy · ${result.attempted} attempted · ${secondsLabel(Math.round(result.total_time_seconds))}</p>
      </div>
      <div class="button-row">
        <button id="new-quiz" class="primary" type="button">New quiz</button>
        <button id="history-inline" type="button">History</button>
      </div>
      <div class="review-list">
        ${result.review.map((item, index) => `
          <article class="review-card ${item.is_correct ? 'correct' : item.attempted ? 'wrong' : 'skipped'}">
            <h3>${index + 1}. ${escapeHtml(item.question)}</h3>
            <p class="hint">Your answer: ${item.selected_index === null ? 'Not attempted' : escapeHtml(item.options[item.selected_index])}</p>
            <p>Correct: <strong>${escapeHtml(item.options[item.correct_index])}</strong></p>
            ${item.explanation ? `<p class="hint">${escapeHtml(item.explanation)}</p>` : ''}
          </article>
        `).join('')}
      </div>
    </section>
  `;
  document.querySelector('#new-quiz')?.addEventListener('click', () => setView('setup'));
  document.querySelector('#history-inline')?.addEventListener('click', () => void renderHistory());
}

async function renderHistory(): Promise<void> {
  state.view = 'history';
  const screen = document.querySelector<HTMLElement>('#screen');
  if (!screen) return;
  const sessions = await listSessions();
  screen.innerHTML = `
    <section class="panel">
      <div class="topics-head">
        <h2>History</h2>
        <button id="back-setup" type="button">Back</button>
      </div>
      <div class="history-list">
        ${sessions.length ? sessions.map((session) => `
          <article class="history-card">
            <strong>${session.score}/${session.total} · ${Math.round(session.accuracy)}%</strong>
            <span>${escapeHtml(session.subject)} · ${escapeHtml(session.difficulty)}</span>
            <span>${new Date(session.timestamp || '').toLocaleString()}</span>
          </article>
        `).join('') : '<p class="hint">No completed quizzes yet.</p>'}
      </div>
    </section>
  `;
  document.querySelector('#back-setup')?.addEventListener('click', () => setView('setup'));
}

async function importDbFromInput(): Promise<void> {
  const input = document.querySelector<HTMLInputElement>('#db-file');
  const status = document.querySelector<HTMLElement>('#db-status');
  const file = input?.files?.[0];
  if (!file) {
    if (status) status.textContent = 'Choose a JSON file first.';
    return;
  }
  try {
    const payload = JSON.parse(await file.text());
    const result = await importDatabasePayload(payload);
    if (status) status.textContent = `Found ${result.found}; added ${result.added}, skipped ${result.skipped}.`;
    await refreshSetupData();
  } catch (error) {
    if (status) status.textContent = error instanceof Error ? error.message : 'Could not import that JSON.';
  }
}

async function exportDbToFile(): Promise<void> {
  const payload = await exportDatabase();
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `cgl-buddy-mcq-db-${new Date().toISOString().slice(0, 10)}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
  const status = document.querySelector<HTMLElement>('#db-status');
  if (status) status.textContent = `Exported ${payload.question_count} imported question${payload.question_count === 1 ? '' : 's'}.`;
}

setupShell();
void refreshSetupData().then(() => renderSetup());
