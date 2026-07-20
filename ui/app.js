const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

const state = { accounts: [] };

function money(minor) {
  return (minor / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function when(unix) {
  return new Date(unix * 1000).toLocaleString();
}

function short(id, n = 8) {
  return id.slice(0, n) + "…";
}

function showError(msg) {
  const el = $("#global-error");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(showError._t);
  showError._t = setTimeout(() => { el.hidden = true; }, 6000);
}

function showInfo(msg) {
  const el = $("#global-info");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(showInfo._t);
  showInfo._t = setTimeout(() => { el.hidden = true; }, 4000);
}

// Card number "1234 5678 9012 3456" grouped by 4 for legibility.
function formatCard(n) {
  return n.replace(/(\d{4})(?=\d)/g, "$1 ");
}

function accountCard(a, opts = {}) {
  const card = document.createElement("div");
  card.className = "account-card" + (a.status === "frozen" ? " is-frozen" : "");
  const showFreeze = opts.canFreeze && a.status === "active";
  const showUnfreeze = opts.canFreeze && a.status === "frozen";
  card.innerHTML = `
    <div class="account-top">
      <div class="account-num">•••• ${a.account_number.slice(-4)}</div>
      <div class="account-status ${a.status}">${a.status}</div>
    </div>
    <div class="account-balance">$${money(a.balance_minor)}</div>
    <div class="account-meta">
      <div><span class="label">Account number</span><span class="value">${a.account_number}</span></div>
      <div><span class="label">Card</span><span class="value">${formatCard(a.card_number)}</span></div>
      ${opts.showOwner ? `<div><span class="label">Owner</span><span class="value mono">${short(a.owner_id, 12)}</span></div>` : ""}
    </div>
    <div class="account-actions">
      <button class="btn-ghost btn-copy" data-copy="${a.account_number}">Copy number</button>
      ${showFreeze ? `<button class="btn-danger btn-freeze" data-id="${a.id}" data-num="${a.account_number}">Freeze</button>` : ""}
      ${showUnfreeze ? `<button class="btn-success btn-unfreeze" data-id="${a.id}" data-num="${a.account_number}">Unfreeze</button>` : ""}
    </div>
  `;
  return card;
}

function bindCardActions(host) {
  host.querySelectorAll(".btn-copy").forEach((b) =>
    b.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(b.dataset.copy);
        b.textContent = "Copied ✓";
        setTimeout(() => { b.textContent = "Copy number"; }, 1500);
      } catch { showError("Clipboard blocked by the browser."); }
    })
  );
  host.querySelectorAll(".btn-freeze").forEach((b) =>
    b.addEventListener("click", () => freezeAccount(b.dataset.id, b.dataset.num))
  );
  host.querySelectorAll(".btn-unfreeze").forEach((b) =>
    b.addEventListener("click", () => unfreezeAccount(b.dataset.id, b.dataset.num))
  );
}

async function loadMyAccounts() {
  const host = $("#my-accounts");
  host.innerHTML = '<div class="skeleton">Loading…</div>';
  try {
    state.accounts = await Session.api("GET", "/banking/accounts/me");
    host.innerHTML = "";
    if (!state.accounts.length) {
      host.innerHTML = `
        <div class="empty">
          <h3>No accounts yet</h3>
          <p>Open your first account to start moving money.</p>
        </div>`;
      return;
    }
    for (const a of state.accounts) host.appendChild(accountCard(a));
    bindCardActions(host);
  } catch (e) { showError(e.message); }
}

async function loadAllAccounts() {
  const host = $("#all-accounts");
  host.innerHTML = '<div class="skeleton">Loading…</div>';
  try {
    const rows = await Session.api("GET", "/banking/accounts");
    host.innerHTML = "";
    if (!rows.length) {
      host.innerHTML = '<div class="empty"><h3>No accounts exist yet</h3></div>';
      return;
    }
    for (const a of rows) host.appendChild(accountCard(a, { canFreeze: true, showOwner: true }));
    bindCardActions(host);
  } catch (e) { showError(e.message); }
}

async function openAccount() {
  try {
    await Session.api("POST", "/banking/accounts");
    showInfo("Account opened.");
    loadMyAccounts();
  } catch (e) { showError(e.message); }
}

async function freezeAccount(id, number) {
  if (!confirm(`Freeze account •••• ${number.slice(-4)}?\n\nTransfers from this account will be blocked.`)) return;
  try {
    await Session.api("POST", `/banking/accounts/${id}/freeze`);
    showInfo(`Account •••• ${number.slice(-4)} frozen.`);
    loadAllAccounts();
  } catch (e) { showError(e.message); }
}

async function unfreezeAccount(id, number) {
  if (!confirm(`Unfreeze account •••• ${number.slice(-4)}?\n\nTransfers will be allowed again.`)) return;
  try {
    await Session.api("POST", `/banking/accounts/${id}/unfreeze`);
    showInfo(`Account •••• ${number.slice(-4)} unfrozen.`);
    loadAllAccounts();
  } catch (e) { showError(e.message); }
}

function fillFromAccountSelect() {
  const sel = $("select[name=from_account_id]");
  sel.innerHTML = "";
  for (const a of state.accounts) {
    const opt = document.createElement("option");
    opt.value = a.id;
    opt.textContent = `•••• ${a.account_number.slice(-4)} — $${money(a.balance_minor)}${a.status !== "active" ? " (" + a.status + ")" : ""}`;
    sel.appendChild(opt);
  }
  if (!state.accounts.length) {
    const opt = document.createElement("option");
    opt.disabled = true;
    opt.textContent = "No accounts — open one first";
    sel.appendChild(opt);
  }
}

async function onTransfer(e) {
  e.preventDefault();
  const form = e.target;
  const amount = parseFloat(form.amount.value);
  if (!(amount > 0)) { showError("Enter a positive amount."); return; }
  const body = {
    from_account_id: form.from_account_id.value,
    to_account_number: form.to_account_number.value.trim(),
    amount_minor: Math.round(amount * 100),
  };
  const submit = form.querySelector("button[type=submit]");
  submit.disabled = true;
  submit.textContent = "Sending…";
  try {
    const tx = await Session.api("POST", "/banking/transfers", body);
    $("#transfer-result").innerHTML = `
      <div class="tx-receipt">
        <div class="tx-receipt-head">
          <div class="tx-receipt-badge ${tx.signature_valid ? "ok" : "bad"}">
            ${tx.signature_valid ? "✓ Sent" : "✗ Verification failed"}
          </div>
          <div class="tx-receipt-amount">-$${money(tx.amount_minor)}</div>
        </div>
        <dl class="tx-receipt-meta">
          <dt>Reference</dt><dd class="mono">${short(tx.id, 10)}</dd>
          <dt>When</dt><dd>${when(tx.at)}</dd>
        </dl>
      </div>`;
    form.reset();
    await loadMyAccounts();
    fillFromAccountSelect();
  } catch (e) {
    showError(e.message);
  } finally {
    submit.disabled = false;
    submit.textContent = "Send";
  }
}

function fillTxAccountSelect() {
  const sel = $("#tx-account-select");
  sel.innerHTML = "";
  for (const a of state.accounts) {
    const opt = document.createElement("option");
    opt.value = a.id;
    opt.textContent = `•••• ${a.account_number.slice(-4)}`;
    sel.appendChild(opt);
  }
  if (state.accounts.length) loadTransactions(state.accounts[0].id);
  else $("#tx-list").innerHTML = '<div class="empty"><h3>Nothing to show</h3><p>Open an account to see transactions.</p></div>';
}

async function loadTransactions(accountId) {
  const host = $("#tx-list");
  host.innerHTML = '<div class="skeleton">Loading…</div>';
  try {
    const rows = await Session.api("GET", `/banking/transactions/${accountId}`);
    host.innerHTML = "";
    if (!rows.length) {
      host.innerHTML = '<div class="empty"><h3>No transactions yet</h3><p>Transfers to and from this account will show up here.</p></div>';
      return;
    }
    for (const tx of rows) {
      const outbound = tx.from_account_id === accountId;
      const row = document.createElement("div");
      row.className = "tx-row " + (outbound ? "tx-out" : "tx-in");
      row.innerHTML = `
        <div class="tx-icon">${outbound ? "↑" : "↓"}</div>
        <div class="tx-body">
          <div class="tx-title">${outbound ? "Sent" : "Received"}</div>
          <div class="tx-sub">${when(tx.at)} · Ref <span class="mono">${short(tx.id, 10)}</span></div>
        </div>
        <div class="tx-right">
          <div class="tx-amount">${outbound ? "-" : "+"}$${money(tx.amount_minor)}</div>
          <div class="tx-sig ${tx.signature_valid ? "ok" : "bad"}">${tx.signature_valid ? "✓ verified" : "✗ invalid"}</div>
        </div>`;
      host.appendChild(row);
    }
  } catch (e) { showError(e.message); }
}

function selectNav(name) {
  $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.nav === name));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `${name}-view`));
  if (name === "accounts") loadMyAccounts();
  if (name === "transfer") fillFromAccountSelect();
  if (name === "transactions") fillTxAccountSelect();
  if (name === "admin") loadAllAccounts();
}

function paintUser() {
  const name = Session.state.username || short(Session.state.userId || "?", 8);
  $("#user-name").textContent = name;
  $("#user-avatar").textContent = name.slice(0, 1).toUpperCase();
  const role = Session.state.role || "customer";
  $("#user-role").textContent = role;
  $("#user-role").classList.toggle("role-admin", role === "admin");
  document.body.classList.toggle("is-admin", role === "admin");
}

function wire() {
  $$(".nav-item").forEach((n) => n.addEventListener("click", () => selectNav(n.dataset.nav)));
  $("#logout-btn").addEventListener("click", () => {
    Session.clear();
    window.location.href = "/";
  });
  $("#open-account-btn").addEventListener("click", openAccount);
  $("#transfer-form").addEventListener("submit", onTransfer);
  $("#tx-account-select").addEventListener("change", (e) => loadTransactions(e.target.value));
  $("#reload-admin-btn").addEventListener("click", loadAllAccounts);
}

async function boot() {
  if (!Session.state.refresh) { window.location.href = "/"; return; }
  if (!Session.state.access) {
    const ok = await Session.refreshOnce();
    if (!ok) { window.location.href = "/"; return; }
  }
  paintUser();
  wire();
  selectNav("accounts");
}

boot();
