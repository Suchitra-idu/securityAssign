const state = {
  access: null,
  refresh: sessionStorage.getItem("refresh"),
  username: sessionStorage.getItem("username"),
  role: null,
  userId: null,
  accounts: [],
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function decodeJwtPayload(token) {
  const [, payload] = token.split(".");
  const padded = payload.replace(/-/g, "+").replace(/_/g, "/");
  return JSON.parse(atob(padded));
}

function setSession(access, refresh, username) {
  state.access = access;
  state.refresh = refresh;
  sessionStorage.setItem("refresh", refresh);
  if (username) {
    state.username = username;
    sessionStorage.setItem("username", username);
  }
  const claims = decodeJwtPayload(access);
  state.role = claims.role;
  state.userId = claims.sub;
}

function clearSession() {
  state.access = null;
  state.refresh = null;
  state.username = null;
  state.role = null;
  state.userId = null;
  state.accounts = [];
  sessionStorage.removeItem("refresh");
  sessionStorage.removeItem("username");
}

async function api(method, path, body) {
  const doFetch = async () => {
    const headers = { "content-type": "application/json" };
    if (state.access) headers["authorization"] = `Bearer ${state.access}`;
    return fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  };

  let res = await doFetch();
  if (res.status === 401 && state.refresh && path !== "/refresh" && path !== "/login") {
    const r = await fetch("/refresh", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: state.refresh }),
    });
    if (r.ok) {
      const t = await r.json();
      setSession(t.access_token, t.refresh_token, null);
      res = await doFetch();
    } else {
      clearSession();
      renderAuth();
      throw new Error("session expired — please log in again");
    }
  }
  if (!res.ok) {
    let detail;
    try { detail = (await res.json()).detail; } catch { detail = res.statusText; }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

function formatMoney(minor) {
  return (minor / 100).toFixed(2);
}

function formatTime(unix) {
  return new Date(unix * 1000).toLocaleString();
}

function renderAuth() {
  $("#auth-view").hidden = false;
  $("#app-view").hidden = true;
  $("#who").hidden = true;
  document.body.classList.remove("is-admin");
}

function renderApp() {
  $("#auth-view").hidden = true;
  $("#app-view").hidden = false;
  $("#who").hidden = false;
  $("#who-name").textContent = state.username || state.userId.slice(0, 8);
  const roleEl = $("#who-role");
  roleEl.textContent = state.role;
  roleEl.classList.toggle("admin", state.role === "admin");
  document.body.classList.toggle("is-admin", state.role === "admin");
  selectNav("accounts");
  loadMyAccounts();
}

function showError(where, msg) {
  const el = $(where);
  el.textContent = msg;
  el.hidden = false;
  setTimeout(() => { el.hidden = true; }, 5000);
}

function showInfo(where, msg) {
  const el = $(where);
  el.textContent = msg;
  el.hidden = false;
  setTimeout(() => { el.hidden = true; }, 4000);
}

function selectNav(name) {
  $$(".nav").forEach((b) => b.classList.toggle("active", b.dataset.nav === name));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.id === `${name}-panel`));
  if (name === "admin") loadAllAccounts();
  if (name === "accounts") loadMyAccounts();
  if (name === "transfer") populateTransferAccounts();
  if (name === "transactions") populateTxAccountSelect();
}

function accountRow(a, opts = {}) {
  const wrap = document.createElement("div");
  wrap.className = "account";
  const fields = document.createElement("div");
  fields.className = "fields";
  fields.innerHTML = `
    <div><label>Account ID</label><span class="value">${a.id}</span></div>
    <div><label>Account number</label><span class="value">${a.account_number}</span></div>
    <div><label>Balance</label><span class="value">${formatMoney(a.balance_minor)}</span></div>
    <div><label>Card number</label><span class="value">${a.card_number}</span></div>
    <div><label>Owner</label><span class="value">${a.owner_id}</span></div>
    <div><label>Status</label><span class="status ${a.status === "frozen" ? "frozen" : ""}">${a.status}</span></div>
  `;
  wrap.appendChild(fields);
  const actions = document.createElement("div");
  actions.className = "actions";
  if (opts.canFreeze && a.status !== "frozen") {
    const btn = document.createElement("button");
    btn.className = "danger";
    btn.type = "button";
    btn.textContent = "Freeze";
    btn.addEventListener("click", () => freezeAccount(a.id));
    actions.appendChild(btn);
  }
  wrap.appendChild(actions);
  return wrap;
}

async function loadMyAccounts() {
  try {
    state.accounts = await api("GET", "/banking/accounts/me");
    const host = $("#my-accounts");
    host.innerHTML = "";
    if (!state.accounts.length) {
      host.innerHTML = '<div class="empty">You have no accounts yet. Click "Open new account" to create one.</div>';
      return;
    }
    for (const a of state.accounts) host.appendChild(accountRow(a));
  } catch (e) {
    showError("#global-error", e.message);
  }
}

async function loadAllAccounts() {
  try {
    const rows = await api("GET", "/banking/accounts");
    const host = $("#all-accounts");
    host.innerHTML = "";
    if (!rows.length) {
      host.innerHTML = '<div class="empty">No accounts exist yet.</div>';
      return;
    }
    for (const a of rows) host.appendChild(accountRow(a, { canFreeze: true }));
  } catch (e) {
    showError("#global-error", e.message);
  }
}

async function openAccount() {
  try {
    await api("POST", "/banking/accounts");
    showInfo("#global-info", "Account opened.");
    loadMyAccounts();
  } catch (e) {
    showError("#global-error", e.message);
  }
}

async function freezeAccount(id) {
  if (!confirm(`Freeze account ${id}? Transfers from this account will be rejected.`)) return;
  try {
    await api("POST", `/banking/accounts/${id}/freeze`);
    showInfo("#global-info", `Account ${id.slice(0, 8)}… frozen.`);
    loadAllAccounts();
  } catch (e) {
    showError("#global-error", e.message);
  }
}

function populateTransferAccounts() {
  const sel = $("#transfer-form select[name=from_account_id]");
  sel.innerHTML = "";
  for (const a of state.accounts) {
    const opt = document.createElement("option");
    opt.value = a.id;
    opt.textContent = `${a.account_number} — ${formatMoney(a.balance_minor)} (${a.status})`;
    sel.appendChild(opt);
  }
}

async function submitTransfer(e) {
  e.preventDefault();
  const form = e.target;
  const amountMajor = parseFloat(form.amount.value);
  if (isNaN(amountMajor) || amountMajor <= 0) {
    showError("#global-error", "Enter a positive amount.");
    return;
  }
  const body = {
    from_account_id: form.from_account_id.value,
    to_account_id: form.to_account_id.value.trim(),
    amount_minor: Math.round(amountMajor * 100),
  };
  try {
    const tx = await api("POST", "/banking/transfers", body);
    const result = $("#transfer-result");
    result.innerHTML = `
      <div class="info" style="margin-top: 16px;">
        Transfer complete. Transaction ID: <code>${tx.id}</code>.
        Signature: ${tx.signature_valid ? "verified" : "INVALID"}.
      </div>
    `;
    form.reset();
    await loadMyAccounts();
    populateTransferAccounts();
  } catch (e) {
    showError("#global-error", e.message);
  }
}

function populateTxAccountSelect() {
  const sel = $("#tx-account-select");
  sel.innerHTML = "";
  for (const a of state.accounts) {
    const opt = document.createElement("option");
    opt.value = a.id;
    opt.textContent = `${a.account_number} (${formatMoney(a.balance_minor)})`;
    sel.appendChild(opt);
  }
  if (state.accounts.length) loadTransactions(state.accounts[0].id);
}

async function loadTransactions(accountId) {
  try {
    const rows = await api("GET", `/banking/transactions/${accountId}`);
    const host = $("#tx-list");
    host.innerHTML = "";
    if (!rows.length) {
      host.innerHTML = '<div class="empty">No transactions for this account.</div>';
      return;
    }
    for (const tx of rows) {
      const isOut = tx.from_account_id === accountId;
      const div = document.createElement("div");
      div.className = "tx";
      div.innerHTML = `
        <div>
          <div class="direction ${isOut ? "out" : "in"}">
            ${isOut ? "-" : "+"}${formatMoney(tx.amount_minor)}
            ${isOut ? "→ " + tx.to_account_id.slice(0, 8) + "…" : "← " + tx.from_account_id.slice(0, 8) + "…"}
          </div>
          <div class="id">${tx.id} · ${formatTime(tx.at)}</div>
        </div>
        <div>
          <div class="${tx.signature_valid ? "sig-ok" : "sig-bad"}">
            ${tx.signature_valid ? "sig ✓" : "SIG INVALID"}
          </div>
        </div>
      `;
      host.appendChild(div);
    }
  } catch (e) {
    showError("#global-error", e.message);
  }
}

async function submitLogin(e) {
  e.preventDefault();
  const form = e.target;
  const username = form.username.value;
  try {
    const t = await api("POST", "/login", {
      username,
      password: form.password.value,
    });
    setSession(t.access_token, t.refresh_token, username);
    form.reset();
    renderApp();
  } catch (e) {
    showError("#auth-error", e.message);
  }
}

async function submitRegister(e) {
  e.preventDefault();
  const form = e.target;
  const username = form.username.value;
  const password = form.password.value;
  try {
    await api("POST", "/register", { username, password });
    const t = await api("POST", "/login", { username, password });
    setSession(t.access_token, t.refresh_token, username);
    form.reset();
    renderApp();
  } catch (e) {
    showError("#auth-error", e.message);
  }
}

async function tryResume() {
  if (!state.refresh) { renderAuth(); return; }
  try {
    const t = await fetch("/refresh", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: state.refresh }),
    });
    if (!t.ok) throw new Error("refresh failed");
    const body = await t.json();
    setSession(body.access_token, body.refresh_token, null);
    renderApp();
  } catch {
    clearSession();
    renderAuth();
  }
}

function wireEvents() {
  $$(".tab").forEach((t) => t.addEventListener("click", () => {
    $$(".tab").forEach((x) => x.classList.toggle("active", x === t));
    $$(".pane").forEach((p) => p.classList.toggle("active", p.id === `${t.dataset.tab}-form`));
    $("#auth-error").hidden = true;
  }));
  $$(".nav").forEach((n) => n.addEventListener("click", () => selectNav(n.dataset.nav)));
  $("#login-form").addEventListener("submit", submitLogin);
  $("#register-form").addEventListener("submit", submitRegister);
  $("#logout-btn").addEventListener("click", () => { clearSession(); renderAuth(); });
  $("#open-account-btn").addEventListener("click", openAccount);
  $("#transfer-form").addEventListener("submit", submitTransfer);
  $("#tx-account-select").addEventListener("change", (e) => loadTransactions(e.target.value));
}

wireEvents();
tryResume();
