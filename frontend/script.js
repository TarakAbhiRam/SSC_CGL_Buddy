/* CGL Buddy — frontend controller (vanilla JS).
 * Talks to the Python backend via window.pywebview.api.*
 * Single-page: toggles #view-setup / #view-quiz / #view-analysis.
 */

(() => {
  "use strict";

  // ---- State ----
  const state = {
    quizId: null,
    questions: [],
    current: 0,
    answers: {},        // questionId -> selected_index
    times: {},          // questionId -> seconds
    questionEnterTs: 0,
    durationMinutes: 15,
    timerInterval: null,
    remainingSeconds: 0,
    charts: {},
    submitting: false,
    keys: { groq: false, gemini: false },
    paused: false,
    syllabus: {},       // subject -> [topics]
    sessions: [],       // cached past attempts (for the detail view)
    lastQuizId: null,   // most recently submitted quiz (for AI-save button)
    autoSaveAi: false,  // mirror of the settings toggle
    chartData: null,    // most recent analysis chart payload for theme redraws
  };

  const $ = (id) => document.getElementById(id);
  const api = () => (window.pywebview && window.pywebview.api) || null;
  const THEME_STORAGE_KEY = "cgl_buddy_theme";

  function storedTheme() {
    try {
      return localStorage.getItem(THEME_STORAGE_KEY) === "dark" ? "dark" : "light";
    } catch (_) {
      return "light";
    }
  }

  function setTheme(theme, persist) {
    const next = theme === "dark" ? "dark" : "light";
    document.body.dataset.theme = next;
    const btn = $("theme-toggle-btn");
    if (btn) {
      const label = next === "dark" ? "Switch to light mode" : "Switch to dark mode";
      btn.textContent = next === "dark" ? "☀" : "☾";
      btn.title = label;
      btn.setAttribute("aria-label", label);
      btn.setAttribute("aria-pressed", next === "dark" ? "true" : "false");
    }
    syncChartColors();
    if (persist) {
      try { localStorage.setItem(THEME_STORAGE_KEY, next); } catch (_) {}
    }

    const activeView = document.querySelector(".view.active");
    if (activeView && activeView.id === "view-analysis" && state.chartData) drawCharts(state.chartData);
    if (activeView && activeView.id === "view-history" && state.sessions.length) renderHistory(state.sessions);
  }

  function toggleTheme() {
    const current = document.body.dataset.theme === "dark" ? "dark" : "light";
    setTheme(current === "dark" ? "light" : "dark", true);
  }

  // pywebview injects the api asynchronously; wait for it.
  function whenReady(cb) {
    let fired = false;
    const run = () => {
      if (fired) return;
      fired = true;
      cb();
    };
    if (api()) return run();
    window.addEventListener("pywebviewready", run, { once: true });
    // Fallback poll in case the event was missed.
    let tries = 0;
    const t = setInterval(() => {
      if (api() || tries++ > 50) {
        clearInterval(t);
        if (api()) run();
      }
    }, 100);
  }

  function showView(name) {
    ["setup", "quiz", "analysis", "history", "database", "browse"].forEach((v) => {
      $("view-" + v).classList.toggle("active", v === name);
    });
  }

  function closeNavMenu() {
    const menu = document.querySelector(".nav-menu");
    if (menu) menu.open = false;
  }

  // ---- Setup screen ----
  async function loadCategories() {
    try {
      // Pull the SSC CGL taxonomy (subjects + subtopics) once.
      try {
        const syl = await api().get_syllabus();
        state.syllabus = (syl && syl.topics) || {};
      } catch (e) {
        state.syllabus = {};
      }
      const cats = await api().list_categories();
      const sel = $("category");
      const pdfSel = $("pdf-subject");
      sel.innerHTML = "";
      pdfSel.innerHTML = "";
      cats.forEach((c) => {
        const opt = document.createElement("option");
        opt.value = c;
        opt.textContent = c === "All" ? "All subjects (full mock)" : c;
        sel.appendChild(opt);
        if (c !== "All") {
          const pdfOpt = document.createElement("option");
          pdfOpt.value = c;
          pdfOpt.textContent = c;
          pdfSel.appendChild(pdfOpt);
        }
      });
      renderTopics();
    } catch (e) {
      console.error("list_categories failed", e);
    }
  }

  // Render subtopic checkboxes for the currently selected subject.
  // `preselect` is an optional array of topic names to tick.
  function renderTopics(preselect) {
    const subject = $("category").value;
    const mode = $("mode") ? $("mode").value : "bank";
    const field = $("topics-field");
    const list = $("topics-list");
    if (mode === "pdf") {
      list.innerHTML = "";
      field.style.display = "none";
      return;
    }
    const topics = (subject && subject !== "All" && state.syllabus[subject]) || [];
    list.innerHTML = "";
    if (!topics.length) {
      field.style.display = "none";
      return;
    }
    field.style.display = "block";
    const chosen = new Set(preselect || []);
    topics.forEach((t) => {
      const id = "topic-" + t.replace(/[^a-z0-9]+/gi, "-").toLowerCase();
      const label = document.createElement("label");
      label.className = "topic-chip";
      label.innerHTML =
        `<input type="checkbox" value="${t.replace(/"/g, "&quot;")}" ${chosen.has(t) ? "checked" : ""} /> ` +
        `<span>${t}</span>`;
      list.appendChild(label);
    });
  }

  function selectedTopics() {
    return [...document.querySelectorAll('#topics-list input[type="checkbox"]:checked')]
      .map((c) => c.value);
  }

  function setAllTopics(checked) {
    document.querySelectorAll('#topics-list input[type="checkbox"]')
      .forEach((c) => { c.checked = checked; });
  }

  async function restoreSettings() {
    try {
      const s = await api().get_settings();
      const last = s.last_settings || {};
      if (last.category) $("category").value = last.category;
      if (last.difficulty) $("difficulty").value = last.difficulty;
      if (last.num_questions) $("num-questions").value = last.num_questions;
      if (last.duration_minutes) $("duration").value = last.duration_minutes;
      if ([...$("mode").options].some((opt) => opt.value === last.mode)) $("mode").value = last.mode;
      // Re-render topic checkboxes for the restored subject and re-tick saved ones.
      renderTopics(Array.isArray(last.topics) ? last.topics : []);
      if (s.active_provider) $("active-provider").value = s.active_provider;
      reflectKeyStatus("groq", s.has_groq_key);
      reflectKeyStatus("gemini", s.has_gemini_key);
      state.keys = { groq: !!s.has_groq_key, gemini: !!s.has_gemini_key };
      state.autoSaveAi = !!s.auto_save_ai;
      $("auto-save-ai").checked = state.autoSaveAi;
      populateProviders(s.active_provider);
      updateModeHint();
    } catch (e) {
      console.error("get_settings failed", e);
    }
  }

  // Build the setup-screen provider dropdown from providers that have a key.
  // Defaults to Gemini when both keys are present.
  function populateProviders(savedProvider) {
    const sel = $("setup-provider");
    const labels = { gemini: "Gemini", groq: "Groq" };
    // Preferred order: gemini first so it wins as the default when both exist.
    const available = ["gemini", "groq"].filter((p) => state.keys && state.keys[p]);
    sel.innerHTML = "";
    available.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p;
      opt.textContent = labels[p];
      sel.appendChild(opt);
    });
    if (available.length) {
      // Prefer the saved provider if it still has a key, else the first
      // available (gemini, given the order above).
      const choice = available.includes(savedProvider) ? savedProvider : available[0];
      sel.value = choice;
      // Keep the hidden settings-modal select in sync so startQuiz/save agree.
      $("active-provider").value = choice;
    }
  }

  function reflectKeyStatus(provider, hasKey) {
    const statusEl = $(provider + "-status");
    const delBtn = document.querySelector('.delete-key[data-provider="' + provider + '"]');
    if (statusEl) {
      statusEl.textContent = hasKey ? "A key is saved on this computer." : "No key saved.";
      statusEl.className = "key-status " + (hasKey ? "ok" : "");
    }
    if (delBtn) delBtn.disabled = !hasKey;
  }

  function updateModeHint() {
    const mode = $("mode").value;
    const hint = $("mode-hint");
    if (mode === "bank") hint.textContent = "Bank + images uses built-in questions and tagged image imports.";
    else if (mode === "pdf") hint.textContent = "PDF mode uses only questions imported from subject-wise PDFs.";
    else hint.textContent = "AI mode generates fresh questions with the selected provider.";

    // Show the provider switcher only when AI is involved.
    const needsAI = mode === "live";
    const field = $("provider-field");
    const phint = $("provider-hint");
    const available = ["gemini", "groq"].filter((p) => state.keys && state.keys[p]);
    field.style.display = needsAI ? "block" : "none";
    if (needsAI) {
      if (available.length === 0) {
        phint.textContent = "No API key saved — add one in Settings to use AI modes.";
      } else if (available.length === 1) {
        phint.textContent = `Using ${available[0] === "gemini" ? "Gemini" : "Groq"} (only key saved).`;
      } else {
        phint.textContent = "Both keys saved — Gemini is selected by default.";
      }
    }
  }

  function onProviderChange() {
    const p = $("setup-provider").value;
    if (!p) return;
    $("active-provider").value = p;
    // Persist the choice so it sticks across restarts.
    api().save_settings({ active_provider: p }).catch((e) => console.error(e));
  }

  function banner(targetId, message, kind = "warn") {
    const el = $(targetId);
    if (!message) { el.innerHTML = ""; return; }
    el.innerHTML = `<div class="banner ${kind}">${message}</div>`;
  }

  async function startQuiz() {
    const btn = $("start-btn");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Building…';
    banner("setup-banner", "");
    try {
      const options = {
        mode: $("mode").value,
        category: $("category").value,
        difficulty: $("difficulty").value,
        topics: $("mode").value === "pdf" ? [] : selectedTopics(),
        num_questions: parseInt($("num-questions").value, 10) || 10,
        duration_minutes: parseInt($("duration").value, 10) || 15,
        provider: $("setup-provider").value || $("active-provider").value,
      };
      // AI mode calls the selected provider directly. The old local
      // embedding preload is intentionally skipped to keep memory usage low.
      if (options.mode === "live") {
        if (!options.provider) {
          banner("setup-banner", "No API key saved. Add a Groq or Gemini key in Settings, or use Bank + images mode.", "warn");
          return;
        }
      }
      const res = await api().start_quiz(options);
      if (!res.ok) {
        banner("setup-banner", res.error || "Could not start quiz.", "warn");
        return;
      }
      if (!res.questions.length) {
        banner("setup-banner", "No questions matched your selection. Try different filters.", "warn");
        return;
      }
      state.quizId = res.quiz_id;
      state.questions = res.questions;
      state.current = 0;
      state.answers = {};
      state.times = {};
      state.submitting = false;
      state.durationMinutes = res.duration_minutes;
      // Warnings (e.g. AI fell back to the bank) are shown only in the pre-test
      // ready modal, not on the live exam screen where they'd be a distraction.
      $("quiz-warnings").innerHTML = "";
      // Questions are loaded — let the user start when ready (timer waits).
      showReadyModal(res);
    } catch (e) {
      console.error(e);
      banner("setup-banner", "Unexpected error starting the quiz.", "warn");
    } finally {
      btn.disabled = false;
      btn.textContent = "Start Quiz";
    }
  }

  // Show a confirmation modal once questions have loaded. The timer only
  // starts when the user clicks "Start test", so they never lose time waiting
  // for AI generation to finish.
  function showReadyModal(res) {
    const mins = res.duration_minutes;
    $("ready-stats").innerHTML = `
      <div class="ready-stat"><div class="value">${state.questions.length}</div><div class="label">Questions</div></div>
      <div class="ready-stat"><div class="value">${mins}</div><div class="label">Minutes</div></div>`;
    $("ready-warnings").innerHTML = (res.warnings || [])
      .map((w) => `<div class="banner warn">${w}</div>`)
      .join("");
    $("ready-modal").classList.add("open");
  }

  function beginTest() {
    if (state.quizId === null) return;
    $("ready-modal").classList.remove("open");
    showView("quiz");
    startTimer(state.durationMinutes * 60);
    renderQuestion();
  }

  // Cancel a loaded-but-not-started quiz: discard it and return to setup.
  function cancelReady() {
    $("ready-modal").classList.remove("open");
    state.quizId = null;
    state.questions = [];
  }

  // ---- Quiz screen ----
  function recordTimeOnLeave() {
    const q = state.questions[state.current];
    if (!q) return;
    const elapsed = (Date.now() - state.questionEnterTs) / 1000;
    state.times[q.id] = (state.times[q.id] || 0) + elapsed;
  }

  function renderQuestion() {
    const q = state.questions[state.current];
    state.questionEnterTs = Date.now();
    $("q-progress").textContent = `Question ${state.current + 1} of ${state.questions.length}`;
    $("q-text").textContent = q.question;

    const optsEl = $("q-options");
    optsEl.innerHTML = "";
    const letters = ["A", "B", "C", "D"];
    q.options.forEach((opt, i) => {
      const div = document.createElement("div");
      div.className = "option" + (state.answers[q.id] === i ? " selected" : "");
      div.innerHTML = `<span class="marker">${letters[i]}</span><span>${opt}</span>`;
      div.addEventListener("click", () => {
        if (state.paused) return;
        state.answers[q.id] = i;
        renderQuestion();
      });
      optsEl.appendChild(div);
    });

    $("prev-btn").disabled = state.current === 0;
    const isLast = state.current === state.questions.length - 1;
    $("next-btn").style.display = isLast ? "none" : "inline-block";
    $("submit-btn").style.display = isLast ? "inline-block" : "none";
  }

  function goTo(delta) {
    if (state.paused) return;
    recordTimeOnLeave();
    state.current = Math.max(0, Math.min(state.questions.length - 1, state.current + delta));
    renderQuestion();
  }

  // ---- Timer ----
  function startTimer(seconds) {
    state.remainingSeconds = seconds;
    state.paused = false;
    updateTimerDisplay();
    $("timer").style.display = "inline-block";
    const pauseBtn = $("pause-btn");
    pauseBtn.style.display = "inline-block";
    pauseBtn.textContent = "Pause";
    runTimerTick();
  }

  function runTimerTick() {
    if (state.timerInterval) clearInterval(state.timerInterval);
    state.timerInterval = setInterval(() => {
      if (state.paused) return;
      state.remainingSeconds -= 1;
      updateTimerDisplay();
      if (state.remainingSeconds <= 0) {
        clearInterval(state.timerInterval);
        submitQuiz(true);
      }
    }, 1000);
  }

  function togglePause() {
    if (state.quizId === null) return;
    state.paused = !state.paused;
    const pauseBtn = $("pause-btn");
    pauseBtn.textContent = state.paused ? "Resume" : "Pause";
    $("timer").classList.toggle("paused", state.paused);
    // While paused, stop counting time-on-question too.
    if (state.paused) {
      recordTimeOnLeave();
    } else {
      state.questionEnterTs = Date.now();
    }
  }

  function updateTimerDisplay() {
    const s = Math.max(0, state.remainingSeconds);
    const m = String(Math.floor(s / 60)).padStart(2, "0");
    const sec = String(s % 60).padStart(2, "0");
    const el = $("timer");
    el.textContent = state.paused ? `${m}:${sec} (paused)` : `${m}:${sec}`;
    el.classList.toggle("danger", s <= 30 && !state.paused);
  }

  function stopTimer() {
    if (state.timerInterval) clearInterval(state.timerInterval);
    state.paused = false;
    $("timer").style.display = "none";
    $("timer").classList.remove("paused");
    $("pause-btn").style.display = "none";
  }

  // ---- Submit + analysis ----
  async function submitQuiz(auto = false) {
    if (state.submitting || state.quizId === null) return;
    state.submitting = true;
    recordTimeOnLeave();
    stopTimer();
    const responses = state.questions.map((q) => ({
      id: q.id,
      selected_index: q.id in state.answers ? state.answers[q.id] : null,
      time_spent_seconds: state.times[q.id] || 0,
    }));
    try {
      const res = await api().submit_quiz(state.quizId, responses);
      if (!res.ok) {
        alert(res.error || "Could not score quiz.");
        state.submitting = false;
        return;
      }
      // Keep the id around so the analysis screen can save AI questions.
      state.lastQuizId = state.quizId;
      state.quizId = null;
      renderAnalysis(res);
      showView("analysis");
    } catch (e) {
      console.error(e);
      alert("Unexpected error scoring the quiz.");
      state.submitting = false;
    }
  }

  // Shared Chart.js theme so every chart matches the app UI.
  const CHART_COLORS = {};

  function cssVar(name, fallback) {
    if (!document.body) return fallback;
    return getComputedStyle(document.body).getPropertyValue(name).trim() || fallback;
  }

  function syncChartColors() {
    Object.assign(CHART_COLORS, {
      primary: cssVar("--primary", "#f97316"),
      correct: cssVar("--correct", "#16a34a"),
      wrong: cssVar("--wrong", "#dc2626"),
      accent: cssVar("--accent", "#0891b2"),
      grid: cssVar("--chart-grid", "rgba(100, 116, 139, 0.18)"),
      tick: cssVar("--chart-tick", "#475569"),
      tooltipBg: cssVar("--tooltip-bg", "#ffffff"),
      tooltipBorder: cssVar("--tooltip-border", "#f5c17d"),
      tooltipTitle: cssVar("--tooltip-title", "#243042"),
      tooltipBody: cssVar("--tooltip-body", "#475569"),
    });
  }

  function baseChartOptions(extra) {
    const opts = {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: false,
          labels: { color: CHART_COLORS.tick, usePointStyle: true, boxWidth: 8 },
        },
        tooltip: {
          backgroundColor: CHART_COLORS.tooltipBg,
          borderColor: CHART_COLORS.tooltipBorder,
          borderWidth: 1,
          padding: 10,
          titleColor: CHART_COLORS.tooltipTitle,
          bodyColor: CHART_COLORS.tooltipBody,
        },
      },
      scales: {
        x: {
          grid: { color: CHART_COLORS.grid, drawBorder: false },
          ticks: { color: CHART_COLORS.tick },
        },
        y: {
          grid: { color: CHART_COLORS.grid, drawBorder: false },
          ticks: { color: CHART_COLORS.tick },
        },
      },
    };
    return Object.assign(opts, extra || {});
  }

  function renderAnalysis(res) {
    const s = res.summary;
    $("stats-grid").innerHTML = `
      <div class="stat"><div class="value">${s.score}/${s.total}</div><div class="label">Score</div></div>
      <div class="stat"><div class="value">${s.accuracy}%</div><div class="label">Accuracy</div></div>
      <div class="stat"><div class="value">${s.attempted}</div><div class="label">Attempted</div></div>
      <div class="stat"><div class="value">${s.skipped}</div><div class="label">Skipped</div></div>
      <div class="stat"><div class="value">${Math.round(s.total_time_seconds)}s</div><div class="label">Total time</div></div>
      <div class="stat"><div class="value">${s.avg_time_seconds}s</div><div class="label">Avg / question</div></div>`;

    drawCharts(res.charts);
  state.chartData = res.charts;
    renderReview(res.review);
    renderSaveAiCard(res.pending_ai_count || 0, res.auto_saved_count || 0);
  }

  // Offer to add this quiz's AI-generated questions to the bank (only shown
  // when there are pending AI questions, i.e. auto-save is off).
  function renderSaveAiCard(pendingCount, autoSavedCount) {
    const card = $("save-ai-card");
    const btn = $("save-ai-btn");
    // Auto-save on: questions were already saved in the background — confirm it.
    if (autoSavedCount) {
      card.style.display = "flex";
      $("save-ai-title").textContent =
        `${autoSavedCount} AI-generated question${autoSavedCount === 1 ? "" : "s"} saved to your bank.`;
      $("save-ai-hint").textContent =
        "Auto-save is on (duplicates are skipped). Manage them in the Database screen.";
      btn.style.display = "none";
      return;
    }
    if (!pendingCount) {
      card.style.display = "none";
      return;
    }
    card.style.display = "flex";
    $("save-ai-title").textContent =
      `This quiz included ${pendingCount} AI-generated question${pendingCount === 1 ? "" : "s"}.`;
    $("save-ai-hint").textContent =
      "Add them to your question bank (duplicates are skipped) so you can reuse them later.";
    // Reset the button: a previous quiz's save may have hidden/disabled it.
    btn.style.display = "";
    btn.disabled = false;
    btn.textContent = "Add questions to database";
  }

  async function saveAiQuestions() {
    const btn = $("save-ai-btn");
    if (!state.lastQuizId) return;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Adding…';
    try {
      const res = await api().save_ai_questions(state.lastQuizId);
      if (!res.ok) {
        $("save-ai-hint").textContent = res.error || "Could not add questions.";
        btn.style.display = "none";
        return;
      }
      $("save-ai-title").textContent =
        `Added ${res.added} question${res.added === 1 ? "" : "s"} to your bank.`;
      $("save-ai-hint").textContent = res.skipped
        ? `${res.skipped} duplicate${res.skipped === 1 ? "" : "s"} skipped.`
        : "";
      btn.style.display = "none";
    } catch (e) {
      console.error(e);
      $("save-ai-hint").textContent = "Unexpected error adding questions.";
      btn.disabled = false;
      btn.textContent = "Add questions to database";
    }
  }

  function drawCharts(charts) {
    Object.values(state.charts).forEach((c) => c && c.destroy());
    state.charts = {};
    if (typeof Chart === "undefined") return;
    syncChartColors();

    // --- Difficulty: chart 1 — distribution (correct vs wrong counts) ---
    const d = charts.difficulty;
    if (d) {
      state.charts.difficultyDist = new Chart($("chart-difficulty-dist"), {
        type: "bar",
        data: {
          labels: d.labels,
          datasets: [
            { label: "Correct", data: d.correct, backgroundColor: CHART_COLORS.correct, borderRadius: 6, stack: "q" },
            { label: "Wrong", data: d.wrong, backgroundColor: CHART_COLORS.wrong, borderRadius: 6, stack: "q" },
          ],
        },
        options: baseChartOptions({
          plugins: { legend: { display: true, position: "bottom", labels: { color: CHART_COLORS.tick, usePointStyle: true, boxWidth: 8 } } },
          scales: {
            x: { stacked: true, grid: { display: false }, ticks: { color: CHART_COLORS.tick } },
            y: { stacked: true, beginAtZero: true, grid: { color: CHART_COLORS.grid }, ticks: { color: CHART_COLORS.tick, precision: 0 } },
          },
        }),
      });

      // --- Difficulty: chart 2 — accuracy % per level ---
      state.charts.difficultyAcc = new Chart($("chart-difficulty-acc"), {
        type: "bar",
        data: {
          labels: d.labels,
          datasets: [{
            label: "Accuracy %",
            data: d.accuracy,
            backgroundColor: [CHART_COLORS.correct, CHART_COLORS.accent, CHART_COLORS.wrong],
            borderRadius: 6,
          }],
        },
        options: baseChartOptions({
          scales: {
            x: { grid: { display: false }, ticks: { color: CHART_COLORS.tick } },
            y: { beginAtZero: true, max: 100, grid: { color: CHART_COLORS.grid }, ticks: { color: CHART_COLORS.tick, callback: (v) => v + "%" } },
          },
        }),
      });
    }

    // --- Category accuracy ---
    const cat = charts.category_accuracy;
    state.charts.category = new Chart($("chart-category"), {
      type: "bar",
      data: {
        labels: cat.labels,
        datasets: [{ label: "Accuracy %", data: cat.accuracy, backgroundColor: CHART_COLORS.primary, borderRadius: 6 }],
      },
      options: baseChartOptions({
        scales: {
          x: { grid: { display: false }, ticks: { color: CHART_COLORS.tick } },
          y: { beginAtZero: true, max: 100, grid: { color: CHART_COLORS.grid }, ticks: { color: CHART_COLORS.tick, callback: (v) => v + "%" } },
        },
      }),
    });

    // --- Time per question ---
    const t = charts.time_per_question;
    state.charts.time = new Chart($("chart-time"), {
      type: "bar",
      data: {
        labels: t.labels,
        datasets: [{
          label: "Seconds",
          data: t.seconds,
          backgroundColor: t.correct.map((c) => (c ? CHART_COLORS.correct : CHART_COLORS.wrong)),
          borderRadius: 6,
        }],
      },
      options: baseChartOptions({
        scales: {
          x: { grid: { display: false }, ticks: { color: CHART_COLORS.tick } },
          y: { beginAtZero: true, grid: { color: CHART_COLORS.grid }, ticks: { color: CHART_COLORS.tick } },
        },
      }),
    });
  }

  function renderReview(review) {
    $("review-list").innerHTML = reviewItemsHtml(review, (r) => r.category);
  }

  // Shared renderer for a list of answered questions (analysis review screen
  // and the past-attempt detail modal). `subjectFn` reads the subject label
  // from an item (the two sources name that field differently).
  function reviewItemsHtml(items, subjectFn) {
    const letters = ["A", "B", "C", "D"];
    const subjOf = subjectFn || ((r) => r.subject || r.category || "");
    return items.map((r, idx) => {
      const cls = !r.attempted ? "skipped" : r.is_correct ? "correct" : "wrong";
      const opts = r.options.map((opt, i) => {
        let oc = "review-opt";
        if (i === r.correct_index) oc += " is-correct";
        else if (i === r.selected_index) oc += " is-chosen-wrong";
        return `<div class="${oc}">${letters[i]}. ${opt}</div>`;
      }).join("");
      const expl = r.explanation ? `<div class="review-expl">${r.explanation}</div>` : "";
      const subject = subjOf(r) || "";
      return `<div class="review-item ${cls}">
        <div class="review-q">Q${idx + 1}. ${r.question}</div>
        ${opts}
        <div class="review-meta">${subject}${r.topic ? " · " + r.topic : ""} · ${r.difficulty} · ${r.time_spent_seconds}s
          ${r.attempted ? "" : " · skipped"}</div>
        ${expl}
      </div>`;
    }).join("");
  }

  // ---- PDF question import ----
  async function uploadPdf() {
    const status = $("upload-status");
    try {
      const path = await api().pick_pdf();
      if (!path) return;
      const subject = $("pdf-subject").value;
      if (!subject) {
        status.textContent = "Choose the subject for this PDF first.";
        status.className = "import-status error";
        return;
      }
      status.className = "hint";
      status.innerHTML = '<span class="spinner"></span> Reading PDF into question bank…';
      const res = await api().import_questions(path, { subject });
      if (res.ok) {
        const added = res.added || 0;
        let msg = `Added ${added} question${added === 1 ? "" : "s"} from ${res.source} to the bank`;
        if (res.skipped) msg += ` (skipped ${res.skipped} duplicate/invalid)`;
        msg += `. Find them in Database → Browse questions under "Imported PDF" and practise them with PDF mode.`;
        status.textContent = msg;
      } else {
        status.textContent = res.error || "Upload failed.";
        status.className = "import-status error";
      }
    } catch (e) {
      console.error(e);
      status.textContent = "Unexpected error during upload.";
      status.className = "import-status error";
    }
  }

  // ---- Import questions from a scan / image (Gemini vision) ----
  async function importQuestions() {
    const status = $("import-status");
    try {
      const path = await api().pick_import_file();
      if (!path) return;
      status.className = "hint";
      const isPdf = /\.pdf$/i.test(path);
      status.innerHTML = isPdf
        ? '<span class="spinner"></span> Reading PDF…'
        : '<span class="spinner"></span> Reading image with AI…';
      const res = await api().import_questions(path);
      if (res.ok) {
        const added = res.added || 0;
        let msg = `Imported ${added} new question${added === 1 ? "" : "s"} from ${res.source}`;
        if (res.skipped) msg += ` (skipped ${res.skipped} duplicate/invalid)`;
        if (res.pages_failed) msg += `; ${res.pages_failed} page(s) failed`;
        msg += ". Find them in the Database screen under \"Imported image\"; they are included in Bank + images mode.";
        status.textContent = msg;
        status.className = res.quota_exhausted ? "import-status warn" : "hint";
        if (res.quota_exhausted) {
          status.textContent = msg +
            " Note: Gemini's daily free-tier limit was hit, so some pages were skipped — retry after it resets to capture the rest.";
        }
      } else {
        status.textContent = res.error || "Import failed.";
        status.className = res.quota_exhausted ? "import-status warn" : "import-status error";
      }
    } catch (e) {
      console.error(e);
      status.textContent = "Unexpected error during import.";
      status.className = "import-status error";
    }
  }

  // ---- Session history ----
  function fmtDuration(seconds) {
    const s = Math.max(0, Math.round(seconds || 0));
    const m = Math.floor(s / 60);
    const r = s % 60;
    return m ? `${m}m ${r}s` : `${r}s`;
  }

  function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    return d.toLocaleString(undefined, {
      month: "short", day: "numeric", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  }

  function subjectLabel(subject) {
    return subject && subject !== "All" ? subject : "All subjects";
  }

  async function openHistory() {
    showView("history");
    const listEl = $("history-list");
    listEl.innerHTML = '<p class="hint"><span class="spinner"></span> Loading…</p>';
    try {
      const res = await api().list_sessions();
      renderHistory((res && res.sessions) || []);
    } catch (e) {
      console.error(e);
      listEl.innerHTML = '<p class="hint">Could not load history.</p>';
    }
  }
  function renderHistory(sessions) {
    const empty = $("history-empty");
    const summaryEl = $("history-summary");
    const listEl = $("history-list");
    const trendCard = $("history-trend-card");

    state.sessions = sessions || [];

    if (!sessions.length) {
      empty.style.display = "block";
      summaryEl.innerHTML = "";
      listEl.innerHTML = "";
      trendCard.style.display = "none";
      if (state.charts.history) { state.charts.history.destroy(); state.charts.history = null; }
      return;
    }
    empty.style.display = "none";

    // Aggregate summary across all attempts.
    const totalAttempts = sessions.length;
    const totalQ = sessions.reduce((a, s) => a + (s.total || 0), 0);
    const totalCorrect = sessions.reduce((a, s) => a + (s.score || 0), 0);
    const avgAcc = totalAttempts
      ? Math.round((sessions.reduce((a, s) => a + (s.accuracy || 0), 0) / totalAttempts) * 10) / 10
      : 0;
    const totalTime = sessions.reduce((a, s) => a + (s.time_taken_seconds || 0), 0);
    const best = sessions.reduce((m, s) => Math.max(m, s.accuracy || 0), 0);

    summaryEl.innerHTML = `
      <div class="stat"><div class="value">${totalAttempts}</div><div class="label">Attempts</div></div>
      <div class="stat"><div class="value">${avgAcc}%</div><div class="label">Avg accuracy</div></div>
      <div class="stat"><div class="value">${best}%</div><div class="label">Best</div></div>
      <div class="stat"><div class="value">${totalCorrect}/${totalQ}</div><div class="label">Total correct</div></div>
      <div class="stat"><div class="value">${fmtDuration(totalTime)}</div><div class="label">Time practised</div></div>`;

    // Trend chart: accuracy oldest -> newest (sessions arrive newest first).
    const chrono = [...sessions].reverse();
    trendCard.style.display = "block";
    if (typeof Chart !== "undefined") {
      syncChartColors();
      if (state.charts.history) state.charts.history.destroy();
      state.charts.history = new Chart($("chart-history"), {
        type: "line",
        data: {
          labels: chrono.map((_, i) => `#${i + 1}`),
          datasets: [{
            label: "Accuracy %",
            data: chrono.map((s) => s.accuracy || 0),
            borderColor: CHART_COLORS.primary,
            backgroundColor: document.body.dataset.theme === "dark" ? "rgba(251,146,60,0.18)" : "rgba(249,115,22,0.16)",
            pointBackgroundColor: CHART_COLORS.primary,
            pointRadius: 3,
            fill: true,
            tension: 0.35,
          }],
        },
        options: baseChartOptions({
          scales: {
            x: { grid: { display: false }, ticks: { color: CHART_COLORS.tick } },
            y: { beginAtZero: true, max: 100, grid: { color: CHART_COLORS.grid }, ticks: { color: CHART_COLORS.tick, callback: (v) => v + "%" } },
          },
        }),
      });
    }

    // Per-attempt cards.
    listEl.innerHTML = sessions.map((s, idx) => {
      const topics = Array.isArray(s.topics) && s.topics.length
        ? s.topics.join(", ")
        : "All topics";
      const modeLabel = { bank: "Bank + images", live: "AI", pdf: "PDF" }[s.mode] || s.mode || "Bank + images";
      const diff = s.difficulty && s.difficulty !== "All" ? s.difficulty : "All levels";
      const da = s.difficulty_accuracy || {};
      const chip = (lvl, label) => {
        const v = da[lvl];
        if (!v || !v.total) return "";
        return `<span class="diff-chip ${lvl}">${label}: ${v.correct}/${v.total}</span>`;
      };
      const diffChips = [chip("easy", "Easy"), chip("medium", "Moderate"), chip("hard", "Hard")].join("");
      const qCount = Array.isArray(s.questions) ? s.questions.length : 0;
      const viewHint = qCount ? `<span class="history-view">View ${qCount} question${qCount === 1 ? "" : "s"} →</span>` : "";
      return `<div class="history-item${qCount ? " clickable" : ""}" data-idx="${idx}">
        <div class="history-row">
          <div class="history-title">${subjectLabel(s.subject)}</div>
          <div class="history-score">${s.score}/${s.total} · ${s.accuracy}%</div>
        </div>
        <div class="history-meta">${fmtDate(s.timestamp)} · ${modeLabel} · ${diff} · ${fmtDuration(s.time_taken_seconds)} taken</div>
        <div class="history-topics">${topics}</div>
        ${diffChips ? `<div class="history-diff">${diffChips}</div>` : ""}
        ${viewHint}
      </div>`;
    }).join("");

    // Clicking an attempt opens its stored questions.
    listEl.querySelectorAll(".history-item.clickable").forEach((el) => {
      el.addEventListener("click", () => openAttempt(parseInt(el.dataset.idx, 10)));
    });
  }

  // Show the questions attempted in a past session (stored with the session).
  function openAttempt(idx) {
    const s = state.sessions[idx];
    if (!s || !Array.isArray(s.questions) || !s.questions.length) return;
    $("attempt-title").textContent = `${subjectLabel(s.subject)} — ${s.score}/${s.total} (${s.accuracy}%)`;
    const modeLabel = { bank: "Bank + images", live: "AI", pdf: "PDF" }[s.mode] || s.mode || "Bank + images";
    $("attempt-meta").textContent =
      `${fmtDate(s.timestamp)} · ${modeLabel} · ${fmtDuration(s.time_taken_seconds)} taken`;
    $("attempt-questions").innerHTML = reviewItemsHtml(s.questions, (q) => q.subject);
    $("attempt-modal").classList.add("open");
  }

  function closeAttempt() {
    $("attempt-modal").classList.remove("open");
  }

  async function clearHistory() {
    if (!confirm("Delete all saved session history from this computer?")) return;
    try {
      await api().clear_sessions();
      renderHistory([]);
    } catch (e) {
      console.error(e);
      alert("Could not clear history.");
    }
  }

  // ---- Database management ----
  async function openDatabase() {
    showView("database");
    $("db-summary").innerHTML = '<p class="hint"><span class="spinner"></span> Loading…</p>';
    try {
      const ov = await api().db_overview();
      renderDbOverview(ov);
    } catch (e) {
      console.error(e);
      $("db-summary").innerHTML = '<p class="hint">Could not load the database.</p>';
    }
  }

  // The browse sub-page: database → browse → questions (with per-item remove).
  async function openBrowse() {
    showView("browse");
    // Always refresh the overview so the filter dropdowns pick up any sources
    // added since last time (e.g. freshly imported scan/image questions).
    try {
      renderDbOverview(await api().db_overview());
    } catch (e) { /* non-fatal */ }
    await loadDbQuestions();
  }

  function renderDbOverview(ov) {
    $("db-summary").innerHTML = `
      <div class="stat"><div class="value">${ov.total_mcq || 0}</div><div class="label">Total questions</div></div>
      <div class="stat"><div class="value">${(ov.mcq_sources || []).length}</div><div class="label">Question sources</div></div>`;

    // MCQ sources (built-in read-only + writable AI sources).
    const mcq = ov.mcq_sources || [];
    $("db-mcq-sources").innerHTML = mcq.length
      ? mcq.map((s) => {
          const del = s.deletable
            ? `<button class="ghost danger db-del-mcq" data-source="${escapeAttr(s.source)}">Delete</button>`
            : `<span class="source-locked">Read-only</span>`;
          return `<div class="source-row">
            <div class="source-info"><span class="source-name">${s.source}</span>
              <span class="source-count">${s.count} question${s.count === 1 ? "" : "s"}</span></div>
            ${del}
          </div>`;
        }).join("")
      : '<p class="hint">No question sources.</p>';

    $("db-mcq-sources").querySelectorAll(".db-del-mcq").forEach((b) =>
      b.addEventListener("click", () => deleteDbSource(b.dataset.source)));

    // Populate the browse filters.
    const subjSel = $("db-filter-subject");
    if (subjSel.options.length <= 1) {
      subjSel.innerHTML = (ov.subjects || ["All"]).map((s) =>
        `<option value="${escapeAttr(s)}">${s === "All" ? "All subjects" : s}</option>`).join("");
    }
    const srcSel = $("db-filter-source");
    const prevSrc = srcSel.value;
    const srcOpts = ["All", ...mcq.map((s) => s.source)];
    srcSel.innerHTML = srcOpts.map((s) =>
      `<option value="${escapeAttr(s)}">${s === "All" ? "All sources" : s}</option>`).join("");
    if (srcOpts.includes(prevSrc)) srcSel.value = prevSrc;
  }

  async function loadDbQuestions() {
    const subject = $("db-filter-subject").value || "All";
    const source = $("db-filter-source").value || "All";
    const listEl = $("db-questions");
    listEl.innerHTML = '<p class="hint"><span class="spinner"></span> Loading…</p>';
    try {
      const res = await api().list_db_questions(subject, source);
      renderDbQuestions(res);
    } catch (e) {
      console.error(e);
      listEl.innerHTML = '<p class="hint">Could not load questions.</p>';
    }
  }

  function renderDbQuestions(res) {
    const items = (res && res.questions) || [];
    const total = (res && res.total) || 0;
    $("db-questions-count").textContent = items.length < total
      ? `Showing ${items.length} of ${total} questions.`
      : `${total} question${total === 1 ? "" : "s"}.`;
    const letters = ["A", "B", "C", "D"];
    const listEl = $("db-questions");
    listEl.innerHTML = items.length
      ? items.map((q, idx) => {
          const opts = (q.options || []).map((opt, i) =>
            `<div class="review-opt${i === q.correct_index ? " is-correct" : ""}">${letters[i]}. ${opt}</div>`).join("");
          const expl = q.explanation ? `<div class="review-expl">${q.explanation}</div>` : "";
          const del = q.deletable && q.id
            ? `<button class="ghost danger db-del-q" data-id="${escapeAttr(q.id)}">Remove</button>`
            : `<span class="source-locked">Built-in</span>`;
          return `<div class="review-item">
            <div class="review-q">Q${idx + 1}. ${q.question}</div>
            ${opts}
            <div class="review-meta">${q.subject}${q.topic ? " · " + q.topic : ""} · ${q.difficulty} · <span class="source-tag">${q.source}</span></div>
            ${expl}
            <div class="review-actions">${del}</div>
          </div>`;
        }).join("")
      : '<p class="hint">No questions match this filter.</p>';

    listEl.querySelectorAll(".db-del-q").forEach((b) =>
      b.addEventListener("click", () => deleteDbQuestion(b.dataset.id)));
  }

  async function deleteDbQuestion(id) {
    if (!id) return;
    if (!confirm("Remove this question from your database?\n\nThis cannot be undone.")) return;
    try {
      const res = await api().delete_db_question(id);
      if (!res.ok) { alert(res.error || "Could not remove the question."); return; }
      // Reload the current filter view so counts stay accurate.
      await loadDbQuestions();
    } catch (e) {
      console.error(e);
      alert("Could not remove the question.");
    }
  }

  async function deleteDbSource(source) {
    if (!source) return;
    if (!confirm(`Delete ALL questions from "${source}"?\n\nThis permanently removes these questions from your database and cannot be undone.`)) return;
    try {
      const res = await api().delete_db_source(source);
      if (!res.ok) { alert(res.error || "Could not delete."); return; }
      await openDatabase();
    } catch (e) {
      console.error(e);
      alert("Could not delete the source.");
    }
  }

  function escapeAttr(s) {
    return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // ---- Settings modal ----
  function openSettings() { $("settings-modal").classList.add("open"); }
  function closeSettings() { $("settings-modal").classList.remove("open"); }

  async function saveSettings() {
    const payload = {
      active_provider: $("active-provider").value,
      groq_key: $("groq-key").value,
      gemini_key: $("gemini-key").value,
      auto_save_ai: $("auto-save-ai").checked,
    };
    try {
      const s = await api().save_settings(payload);
      $("groq-key").value = "";
      $("gemini-key").value = "";
      reflectKeyStatus("groq", s.has_groq_key);
      reflectKeyStatus("gemini", s.has_gemini_key);
      state.keys = { groq: !!s.has_groq_key, gemini: !!s.has_gemini_key };
      state.autoSaveAi = !!s.auto_save_ai;
      populateProviders(s.active_provider);
      updateModeHint();
      closeSettings();
    } catch (e) {
      console.error(e);
      alert("Could not save settings.");
    }
  }

  async function deleteKey(ev) {
    const provider = ev.target.dataset.provider;
    if (!confirm("Delete the saved " + provider + " API key from this computer?")) return;
    try {
      const s = await api().delete_api_key(provider);
      $(provider + "-key").value = "";
      reflectKeyStatus(provider, provider === "groq" ? s.has_groq_key : s.has_gemini_key);
      state.keys = { groq: !!s.has_groq_key, gemini: !!s.has_gemini_key };
      populateProviders(s.active_provider);
      updateModeHint();
    } catch (e) {
      console.error(e);
      alert("Could not delete the key.");
    }
  }

  async function testKey(ev) {
    const provider = ev.target.dataset.provider;
    const statusEl = $(provider + "-status");
    const key = $(provider + "-key").value;
    statusEl.className = "key-status";
    statusEl.innerHTML = '<span class="spinner"></span> Testing…';
    try {
      const res = await api().test_api_key(provider, key);
      statusEl.textContent = res.message;
      statusEl.className = "key-status " + (res.ok ? "ok" : "bad");
    } catch (e) {
      statusEl.textContent = "Test failed.";
      statusEl.className = "key-status bad";
    }
  }

  // ---- Wire up ----
  function bind() {
    $("theme-toggle-btn").addEventListener("click", toggleTheme);
    $("start-btn").addEventListener("click", startQuiz);
    $("mode").addEventListener("change", () => { updateModeHint(); renderTopics(); });
    $("category").addEventListener("change", () => renderTopics());
    $("topics-all").addEventListener("click", () => setAllTopics(true));
    $("topics-none").addEventListener("click", () => setAllTopics(false));
    $("setup-provider").addEventListener("change", onProviderChange);
    $("prev-btn").addEventListener("click", () => goTo(-1));
    $("next-btn").addEventListener("click", () => goTo(1));
    $("submit-btn").addEventListener("click", () => {
      if (confirm("Submit your quiz now?")) submitQuiz(false);
    });
    $("end-btn").addEventListener("click", () => {
      const answered = Object.keys(state.answers).length;
      const total = state.questions.length;
      if (confirm(`End the test now? You've answered ${answered} of ${total}. Unanswered questions are marked skipped.`)) {
        submitQuiz(false);
      }
    });
    $("pause-btn").addEventListener("click", togglePause);
    $("ready-start").addEventListener("click", beginTest);
    $("ready-cancel").addEventListener("click", cancelReady);
    $("retake-btn").addEventListener("click", () => showView("setup"));
    $("save-ai-btn").addEventListener("click", saveAiQuestions);
    $("history-btn").addEventListener("click", () => { closeNavMenu(); openHistory(); });
    $("history-back-btn").addEventListener("click", () => showView("setup"));
    $("history-clear-btn").addEventListener("click", clearHistory);
    $("attempt-close").addEventListener("click", closeAttempt);
    $("database-btn").addEventListener("click", () => { closeNavMenu(); openDatabase(); });
    $("database-back-btn").addEventListener("click", () => showView("setup"));
    $("database-browse-btn").addEventListener("click", openBrowse);
    $("browse-back-btn").addEventListener("click", openDatabase);
    $("db-filter-subject").addEventListener("change", loadDbQuestions);
    $("db-filter-source").addEventListener("change", loadDbQuestions);
    $("upload-btn").addEventListener("click", uploadPdf);
    $("import-btn").addEventListener("click", importQuestions);
    $("settings-btn").addEventListener("click", () => { closeNavMenu(); openSettings(); });
    $("settings-cancel").addEventListener("click", closeSettings);
    $("settings-save").addEventListener("click", saveSettings);
    document.querySelectorAll(".test-key").forEach((b) => b.addEventListener("click", testKey));
    document.querySelectorAll(".delete-key").forEach((b) => b.addEventListener("click", deleteKey));
  }

  whenReady(async () => {
    setTheme(storedTheme(), false);
    bind();
    await loadCategories();
    await restoreSettings();
  });
})();
