/* llm-NOOBservability chat UI: NDJSON stream -> steps, summary, chart/table. */
"use strict";

/* ---- theme -------------------------------------------------------------- */
const root = document.documentElement;
function applyTheme(t) {
  root.dataset.theme = t;
  localStorage.setItem("noob-theme", t);
  for (const c of charts) rebuildChart(c);
}
document.getElementById("theme-toggle").onclick = () =>
  applyTheme(root.dataset.theme === "dark" ? "light" : "dark");
applyTheme(localStorage.getItem("noob-theme") ||
  (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));

/* ---- helpers ------------------------------------------------------------ */
const timeline = document.getElementById("timeline");
const form = document.getElementById("ask-form");
const input = document.getElementById("question");
const send = document.getElementById("send");

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
const cssVar = (name) => getComputedStyle(root).getPropertyValue(name).trim();
const seriesColors = () => [1, 2, 3, 4, 5, 6].map((i) => cssVar(`--s${i}`));

function fmtVal(v) {
  if (v == null || !isFinite(v)) return "–";
  const a = Math.abs(v);
  if (a >= 1e12) return (v / 1e12).toFixed(2) + "T";
  if (a >= 1e9) return (v / 1e9).toFixed(2) + "G";
  if (a >= 1e6) return (v / 1e6).toFixed(2) + "M";
  if (a >= 1e3) return (v / 1e3).toFixed(2) + "k";
  if (a >= 1) return +v.toFixed(2) + "";
  return v.toPrecision(3);
}
function seriesName(metric) {
  const m = { ...metric };
  delete m.__name__;
  const parts = Object.entries(m).map(([k, v]) => `${k}=${v}`);
  return parts.length ? parts.join(" ") : (metric.__name__ || "value");
}
function download(name, text, type) {
  const a = el("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ---- charts (uPlot) ------------------------------------------------------ */
const charts = []; // { holder, spec } — rebuilt on theme change / resize

function buildMatrixSpec(result) {
  // top 6 series by mean |value|; the rest are download-only.
  const scored = result
    .map((s) => {
      const vals = (s.values || []).map(([, v]) => parseFloat(v));
      const mean = vals.reduce((a, b) => a + Math.abs(b), 0) / (vals.length || 1);
      return { s, mean };
    })
    .sort((a, b) => b.mean - a.mean);
  const kept = scored.slice(0, 6).map((x) => x.s);
  const xsSet = new Set();
  for (const s of kept) for (const [t] of s.values || []) xsSet.add(+t);
  const xs = [...xsSet].sort((a, b) => a - b);
  const idx = new Map(xs.map((t, i) => [t, i]));
  const ys = kept.map((s) => {
    const col = new Array(xs.length).fill(null);
    for (const [t, v] of s.values || []) col[idx.get(+t)] = parseFloat(v);
    return col;
  });
  return {
    xs, ys,
    labels: kept.map((s) => seriesName(s.metric || {})),
    omitted: result.length - kept.length,
  };
}

function rebuildChart(entry) {
  const { holder, spec } = entry;
  holder.textContent = "";
  const colors = seriesColors();
  const axis = {
    stroke: cssVar("--muted"),
    grid: { stroke: cssVar("--grid"), width: 1 },
    ticks: { stroke: cssVar("--grid"), width: 1 },
    font: "11px ui-monospace, Menlo, monospace",
  };
  const u = new uPlot(
    {
      width: Math.max(holder.clientWidth || holder.parentNode.clientWidth - 28, 320),
      height: 280,
      series: [
        {},
        ...spec.labels.map((label, i) => ({
          label,
          stroke: colors[i % colors.length],
          width: 2,
          points: { show: false },
        })),
      ],
      axes: [axis, { ...axis, values: (u, vals) => vals.map(fmtVal) }],
      legend: { live: true },
      cursor: { drag: { x: true, y: false } },
    },
    [spec.xs, ...spec.ys],
    holder
  );
  entry.plot = u;
}

let resizeTimer;
addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    for (const c of charts)
      c.plot && c.plot.setSize({ width: Math.max(c.holder.clientWidth, 320), height: 280 });
  }, 150);
});

/* ---- log table ----------------------------------------------------------- */
function renderStreams(container, result) {
  const rows = [];
  for (const s of result)
    for (const [ts, line] of s.values || [])
      rows.push({ t: +ts / 1e6, who: s.stream?.unit || s.stream?.service_name || "", line });
  rows.sort((a, b) => b.t - a.t);
  const wrap = el("div", "logs");
  const table = el("table");
  table.append(el("thead"));
  table.tHead.append(el("tr"));
  for (const h of ["time", "unit", "line"]) table.tHead.rows[0].append(el("th", "", h));
  const body = el("tbody");
  for (const r of rows.slice(0, 300)) {
    const tr = el("tr");
    tr.append(el("td", "ts", new Date(r.t).toLocaleString()));
    tr.append(el("td", "who", r.who));
    tr.append(el("td", "", r.line));
    body.append(tr);
  }
  table.append(body);
  wrap.append(table);
  container.append(wrap);
  if (rows.length > 300)
    container.append(el("div", "note", `showing 300 of ${rows.length} lines — download for all`));
  return rows;
}

/* ---- CSV ------------------------------------------------------------------ */
const csvEsc = (s) => `"${String(s).replaceAll('"', '""')}"`;
function toCsv(dataEv) {
  if (dataEv.resultType === "streams") {
    const out = ["time,stream,line"];
    for (const s of dataEv.result)
      for (const [ts, line] of s.values || [])
        out.push([new Date(+ts / 1e6).toISOString(), csvEsc(seriesName(s.stream || {})), csvEsc(line)].join(","));
    return out.join("\n");
  }
  const spec = buildMatrixSpec(dataEv.result); // note: top-6 view; JSON has everything
  const out = ["time," + spec.labels.map(csvEsc).join(",")];
  spec.xs.forEach((t, i) =>
    out.push([new Date(t * 1000).toISOString(), ...spec.ys.map((col) => col[i] ?? "")].join(","))
  );
  return out.join("\n");
}

/* ---- ask flow -------------------------------------------------------------- */
async function ask(question, since) {
  document.body.classList.replace("fresh", "chat");

  const ex = el("div", "exchange");
  ex.append(el("div", "q-bubble", question));
  const steps = el("div", "steps");
  const running = el("div", "step");
  running.append(el("span", "spinner", "● thinking…"));
  steps.append(running);
  const summaryBox = el("div", "summary");
  const vizBox = el("div");
  ex.append(steps, summaryBox, vizBox);
  timeline.append(ex);
  ex.scrollIntoView({ block: "end", behavior: "smooth" });

  const addStep = (text, cls) => {
    const s = el("div", "step" + (cls ? " " + cls : ""));
    steps.insertBefore(s, running);
    return s;
  };

  let dataEv = null;
  try {
    const resp = await fetch("/api/ask", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ question, since: since || null }),
    });
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (line) handleEvent(JSON.parse(line));
      }
    }
  } catch (e) {
    addStep(`connection error: ${e.message}`, "err");
  }
  running.remove();
  ex.scrollIntoView({ block: "end", behavior: "smooth" });

  function handleEvent(ev) {
    switch (ev.event) {
      case "route":
        addStep(`→ ${ev.target === "mimir" ? "metrics (PromQL)" : "logs (LogQL)"}`);
        break;
      case "attempt": {
        const s = addStep(`attempt ${ev.n} · since ${ev.since} · `);
        s.append(el("span", "qtext", ev.query));
        break;
      }
      case "query_error":
        addStep(`✗ ${ev.error.slice(0, 260)}`, "err");
        break;
      case "empty":
        addStep(`∅ no data — retrying with hints`);
        break;
      case "data": {
        dataEv = ev;
        const card = el("div", "card result-card");
        vizBox.append(card);
        if (ev.resultType === "streams") {
          if (ev.result.length) renderStreams(card, ev.result);
          else card.append(el("div", "note", "no matching log lines — that's the answer"));
        } else if (ev.result.length) {
          const holder = el("div");
          card.append(holder);
          const spec = buildMatrixSpec(ev.result);
          const entry = { holder, spec };
          charts.push(entry);
          rebuildChart(entry);
          if (spec.omitted > 0)
            card.append(el("div", "note",
              `top 6 of ${ev.result.length} series shown — download JSON for all`));
        } else {
          card.append(el("div", "note", "empty result"));
        }
        const actions = el("div", "actions");
        const jb = el("button", "", "⇩ json");
        jb.onclick = () => download("noob-data.json", JSON.stringify(ev, null, 1), "application/json");
        const cb = el("button", "", "⇩ csv");
        cb.onclick = () => download("noob-data.csv", toCsv(ev), "text/csv");
        actions.append(jb, cb);
        card.append(actions);
        break;
      }
      case "summary":
        summaryBox.textContent = ev.text;
        break;
      case "done":
        if (!ev.ok) addStep(`✗ ${ev.error || "gave up"}`, "err");
        break;
      case "fatal":
        addStep(`✗ ${ev.error}`, "err");
        break;
    }
    ex.scrollIntoView({ block: "end", behavior: "smooth" });
  }
}

document.body.classList.add("fresh");
form.onsubmit = (e) => {
  e.preventDefault();
  const q = input.value.trim();
  if (!q || send.disabled) return;
  input.value = "";
  send.disabled = true;
  ask(q, document.getElementById("since").value).finally(() => {
    send.disabled = false;
    input.focus();
  });
};
