// Flippy's app window. Talks to Python only through window.webkit.messageHandlers.flippy (flippy/shell/bridge.py).
// A classic script, not a module: WebKit refuses module scripts from file URLs.
(() => {
"use strict";
const pending = new Map();
let nextId = 1;
const handlers = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.flippy;

function call(op, args = {}) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    if (handlers) handlers.postMessage(JSON.stringify({ id, op, args }));
    else reject(new Error("no bridge"));
  });
}

// Python calls these.
window.flippy = {
  reply(msg) {
    const p = pending.get(msg.id);
    if (!p) return;
    pending.delete(msg.id);
    msg.ok ? p.resolve(msg.result) : p.reject(new Error(msg.error));
  },
  event(name, data) {
    if (name === "setting") updateField(data);
    if (name === "route") go(data);
  },
};

let state = { pages: [] };
const fields = new Map();   // field id -> field data
const nav = document.getElementById("nav");
const page = document.getElementById("page");

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined) node.append(c);
  return node;
}

function renderNav(route) {
  const item = (id, title, extra) => el("li", {}, el("a", {
    href: "#" + id, "aria-current": route === id ? "page" : null,
  }, title, extra || null));
  nav.replaceChildren(
    item("history", "History"),
    item("setup", "Setup"),
    el("li", { class: "group", role: "presentation" }, "Settings"),
    ...state.pages.map((p) => item("settings/" + p.id, p.title)),
  );
}

async function save(f, value, row) {
  try {
    updateField(await call("set", { id: f.id, value }));
    row.classList.remove("error");
  } catch (e) {
    row.classList.add("error");
    row.querySelector(".help").textContent = "Couldn't save that: " + e.message;
  }
}

function controlFor(f, row) {
  const id = "f-" + f.id;
  switch (f.control) {
    case "choice":
      return el("select", { id, onchange: (e) => save(f, f.choices[e.target.selectedIndex].value, row) },
        f.choices.map((c) => el("option", { selected: c.value === f.value }, c.label)));
    case "switch":
      return el("input", { id, type: "checkbox", role: "switch", class: "switch", checked: f.value,
        onchange: (e) => save(f, e.target.checked, row) });
    case "slider": {
      const out = el("span", { class: "value" }, Number(f.value).toFixed(f.digits));
      const input = el("input", { id, type: "range", min: f.min, max: f.max, step: f.step, value: f.value,
        oninput: (e) => (out.textContent = Number(e.target.value).toFixed(f.digits)),
        onchange: (e) => save(f, f.digits ? Number(e.target.value) : Math.round(e.target.value), row) });
      return [input, out];
    }
    case "list":
      return el("div", { class: "chips" }, f.value.length ? f.value.map((v) => el("span", { class: "chip" }, v,
        el("button", { "aria-label": "Remove " + v, onclick: () => save(f, f.value.filter((x) => x !== v), row) }, "×")))
        : el("span", { class: "none" }, "None"));
    case "shortcut":
      return el("span", { class: "key", id }, f.value);
    default:
      return el("input", { id, type: "text", value: f.value, spellcheck: "false",
        onchange: (e) => save(f, e.target.value, row) });
  }
}

function fieldRow(f) {
  fields.set(f.id, f);
  const row = el("div", { class: "row", "data-id": f.id });
  const labelled = ["choice", "switch", "slider", "text"].includes(f.control);
  row.append(
    el("div", { class: "text" },
      labelled ? el("label", { for: "f-" + f.id }, f.label) : el("span", { class: "label" }, f.label),
      el("div", { class: "help" }, f.help || "")),
    el("div", { class: "control" }, controlFor(f, row)));
  return row;
}

function updateField(f) {
  if (!f) return;
  fields.set(f.id, f);
  const row = page.querySelector(`[data-id="${CSS.escape(f.id)}"]`);
  if (row && !row.contains(document.activeElement)) row.replaceWith(fieldRow(f));
}

function renderPage(route) {
  const [kind, id] = route.split("/");
  if (kind === "settings") {
    const p = state.pages.find((x) => x.id === id) || state.pages[0];
    page.replaceChildren(el("h1", {}, p.title), el("div", { class: "rows" }, p.fields.map(fieldRow)));
  } else if (kind === "setup") {
    page.replaceChildren(el("h1", {}, "Setup"), el("p", { class: "empty" }, "Sign-in, permissions and shortcuts move here in phase 3."));
  } else {
    page.replaceChildren(el("h1", {}, "History"), el("p", { class: "empty" }, "Your past questions and desktop tasks will show here, newest first."));
  }
}

function go(route) {
  if (location.hash.slice(1) !== route) location.hash = route;
  else { renderNav(route); renderPage(route); }
}

window.addEventListener("hashchange", () => {
  const route = location.hash.slice(1) || "settings/general";
  renderNav(route);
  renderPage(route);
  page.focus();
});

(async () => {
  call("mark", { name: "script" }).catch(() => {});
  state = await call("state");
  const route = state.route || location.hash.slice(1) || "settings/general";
  if (location.hash.slice(1) !== route) history.replaceState(null, "", "#" + route);
  renderNav(route);
  renderPage(route);
  requestAnimationFrame(() => call("mark", { name: "painted" }).catch(() => {}));
})();
})();
