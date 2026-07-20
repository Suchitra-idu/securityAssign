const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

function showError(msg) {
  const el = $("#auth-error");
  el.textContent = msg;
  el.hidden = false;
}

function hideError() { $("#auth-error").hidden = true; }

function selectTab(name) {
  $$(".seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".auth-form").forEach((f) => f.classList.toggle("active", f.id === `${name}-form`));
  hideError();
}

async function onLogin(e) {
  e.preventDefault();
  hideError();
  const form = e.target;
  const submit = form.querySelector("button[type=submit]");
  submit.disabled = true;
  submit.textContent = "Signing in…";
  const username = form.username.value;
  try {
    const t = await Session.api("POST", "/login", { username, password: form.password.value });
    Session.set(t.access_token, t.refresh_token, username);
    window.location.href = "/app";
  } catch (err) {
    showError(err.message);
    submit.disabled = false;
    submit.textContent = "Sign in";
  }
}

async function onRegister(e) {
  e.preventDefault();
  hideError();
  const form = e.target;
  const submit = form.querySelector("button[type=submit]");
  submit.disabled = true;
  submit.textContent = "Creating…";
  const username = form.username.value;
  const password = form.password.value;
  try {
    await Session.api("POST", "/register", { username, password });
    const t = await Session.api("POST", "/login", { username, password });
    Session.set(t.access_token, t.refresh_token, username);
    window.location.href = "/app";
  } catch (err) {
    showError(err.message);
    submit.disabled = false;
    submit.textContent = "Create account";
  }
}

async function init() {
  // Already signed in? Skip the form and land in the app. The persisted
  // access covers the fresh-reload case; refresh handles a stale one.
  if (Session.state.access) { window.location.href = "/app"; return; }
  if (Session.state.refresh) {
    if (await Session.refreshOnce()) {
      window.location.href = "/app";
      return;
    }
  }
  $$(".seg-btn").forEach((b) => b.addEventListener("click", () => selectTab(b.dataset.tab)));
  $("#login-form").addEventListener("submit", onLogin);
  $("#register-form").addEventListener("submit", onRegister);
}

init();
