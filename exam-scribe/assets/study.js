(function () {
  "use strict";
  var store = {
    get: function (k, d) { try { var v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } }
  };
  var course = document.body.getAttribute("data-course") || "course";
  var UI = {};
  try { UI = JSON.parse(document.body.getAttribute("data-ui") || "{}"); } catch (e) { UI = {}; }
  function t(s, v) {                       // the page's words in the notes language (data-ui), else English
    var out = UI[s] || s;
    Object.keys(v || {}).forEach(function (k) { out = out.split("{" + k + "}").join(String(v[k])); });
    return out;
  }
  var RKEY = "examscribe:" + course + ":results";

  // ---- theme and mode -------------------------------------------------------
  function setMode(m) {
    document.body.setAttribute("data-mode", m);
    document.querySelectorAll("[data-set-mode]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-set-mode") === m));
    });
    store.set("examscribe:mode", m);
  }
  var initial = document.body.getAttribute("data-default-mode") || store.get("examscribe:mode", "read");
  setMode(initial);
  document.querySelectorAll("[data-set-mode]").forEach(function (b) {
    b.addEventListener("click", function () { setMode(b.getAttribute("data-set-mode")); });
  });
  var theme = store.get("examscribe:theme", null);
  if (theme) document.documentElement.setAttribute("data-theme", theme);
  var tbtn = document.getElementById("theme-toggle");
  if (tbtn) tbtn.addEventListener("click", function () {
    var cur = document.documentElement.getAttribute("data-theme");
    var dark = cur ? cur === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    var next = dark ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    store.set("examscribe:theme", next);
  });

  // ---- recall: click or Enter reveals ---------------------------------------
  function reveal(el) { el.classList.add("shown"); }
  document.querySelectorAll(".ans").forEach(function (el) {
    el.setAttribute("tabindex", "0");
    el.addEventListener("click", function () { if (document.body.getAttribute("data-mode") === "recall") reveal(el); });
    el.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); reveal(el); } });
  });
  var hideAll = document.getElementById("hide-all");
  if (hideAll) hideAll.addEventListener("click", function () {
    document.querySelectorAll(".ans.shown").forEach(function (el) { el.classList.remove("shown"); });
  });

  // ---- results ----------------------------------------------------------------
  function record(qid, ok) {
    var r = store.get(RKEY, {});
    (r[qid] = r[qid] || []).push({ at: new Date().toISOString(), correct: !!ok });
    store.set(RKEY, r);
    updateScore();
  }
  function updateScore() {
    var el = document.getElementById("score");
    if (!el) return;
    var done = document.querySelectorAll(".q[data-done]").length;
    var good = document.querySelectorAll(".q[data-done='1']").length;
    var total = document.querySelectorAll(".q").length;
    el.textContent = t("{good} / {done} correct ({total} questions)", { good: good, done: done, total: total });
  }
  var exp = document.getElementById("export-results");
  if (exp) exp.addEventListener("click", function () {
    var r = store.get(RKEY, {}), rows = [];
    Object.keys(r).forEach(function (q) { r[q].forEach(function (x) { rows.push({ id: q, correct: x.correct, at: x.at }); }); });
    var blob = new Blob([JSON.stringify({ course: course, results: rows }, null, 2)], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "examscribe-results-" + new Date().toISOString().slice(0, 10) + ".json";
    document.body.appendChild(a); a.click(); a.remove();
  });

  // ---- quizzes ----------------------------------------------------------------
  var deferred = document.body.hasAttribute("data-exam");     // mock exam: feedback only after Finish
  function norm(s) {
    return (s || "").toLowerCase().replace(/\b(the|a|an)\b/g, " ").replace(/[^\p{L}\p{N}.]+/gu, "");
  }
  function finish(q, ok) {
    if (q.hasAttribute("data-done")) return;
    q.setAttribute("data-done", ok ? "1" : "0");
    record(q.getAttribute("data-qid"), ok);
    if (!deferred) showFeedback(q, ok);
  }
  function showFeedback(q, ok) {
    var fb = q.querySelector(".feedback");
    if (!fb) return;
    fb.classList.add("show", ok === null ? "neutral" : (ok ? "good" : "bad"));
    var head = fb.querySelector(".verdict");
    if (head) head.textContent = ok === null ? "" : (ok ? t("Correct.") : t("Not quite."));
    var ans = q.getAttribute("data-type") === "mcq" ? q.getAttribute("data-answer") : null;
    if (ans) q.querySelectorAll(".opt").forEach(function (b) { if (b.getAttribute("data-letter") === ans) b.classList.add("correct"); });
  }
  document.querySelectorAll(".q").forEach(function (q) {
    var type = q.getAttribute("data-type");
    var answer = q.getAttribute("data-answer") || "";
    if (type === "mcq" || type === "tf") {
      q.querySelectorAll(".opt").forEach(function (b) {
        b.addEventListener("click", function () {
          if (q.hasAttribute("data-done")) return;
          var ok = b.getAttribute("data-letter") === answer;
          if (!ok && !deferred) b.classList.add("incorrect");
          if (deferred) { q.querySelectorAll(".opt").forEach(function (x) { x.setAttribute("aria-pressed", "false"); }); b.setAttribute("aria-pressed", "true"); }
          finish(q, ok);
        });
      });
    } else if (type === "numeric" || type === "cloze") {
      var input = q.querySelector("input"), go = q.querySelector(".check");
      var run = function () {
        var v = input.value.trim(); if (!v) return;
        var ok;
        if (type === "numeric") {
          var want = parseFloat(answer), got = parseFloat(v.replace(/,/g, ""));
          ok = isFinite(got) && Math.abs(got - want) <= Math.abs(want) * 0.01 + 1e-12;
        } else {
          var accept = JSON.parse(q.getAttribute("data-accept") || "[]");
          ok = accept.concat([answer]).some(function (a) { return norm(a) === norm(v); });
        }
        finish(q, ok);
      };
      if (go) go.addEventListener("click", run);
      if (input) input.addEventListener("keydown", function (e) { if (e.key === "Enter") run(); });
    } else if (type === "short") {
      var show = q.querySelector(".show-answer"), sg = q.querySelector(".selfgrade");
      if (show) show.addEventListener("click", function () { showFeedback(q, null); if (sg) sg.classList.add("show"); });
      q.querySelectorAll("[data-grade]").forEach(function (b) {
        b.addEventListener("click", function () { var ok = b.getAttribute("data-grade") === "1"; q.removeAttribute("data-done"); finish(q, ok); showFeedback(q, ok); });
      });
    }
  });
  updateScore();

  // ---- mock exam: timer and finish ------------------------------------------------
  var timer = document.getElementById("timer");
  if (timer) {
    var secs = parseInt(timer.getAttribute("data-seconds"), 10), started = null, handle = null;
    var startBtn = document.getElementById("start-exam");
    var tick = function () {
      var left = Math.max(0, secs - Math.floor((Date.now() - started) / 1000));
      timer.textContent = Math.floor(left / 60) + ":" + String(left % 60).padStart(2, "0");
      if (left === 0) { clearInterval(handle); finishExam(); }
    };
    if (startBtn) startBtn.addEventListener("click", function () {
      if (started) return; started = Date.now(); handle = setInterval(tick, 500); tick();
      document.getElementById("exam-body").hidden = false; startBtn.hidden = true;
    });
  }
  function finishExam() {
    document.querySelectorAll(".q").forEach(function (q) {
      var done = q.getAttribute("data-done");
      showFeedback(q, done === null ? false : done === "1");
    });
    var s = document.getElementById("score"); if (s) s.scrollIntoView({ behavior: "smooth" });
  }
  var fin = document.getElementById("finish-exam");
  if (fin) fin.addEventListener("click", function () { deferred = false; finishExam(); });

  // ---- faded worked examples ---------------------------------------------------------
  document.querySelectorAll(".faded").forEach(function (f) {
    var btn = f.querySelector(".show-steps");
    if (btn) btn.addEventListener("click", function () {
      f.querySelectorAll(".blank").forEach(function (b) { b.classList.remove("blank"); b.style.color = ""; });
      btn.hidden = true;
    });
  });
})();
