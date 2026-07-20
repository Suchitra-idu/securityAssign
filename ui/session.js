const Session = (() => {
  function decodeJwt(token) {
    try {
      const [, payload] = token.split(".");
      const padded = payload.replace(/-/g, "+").replace(/_/g, "/");
      return JSON.parse(atob(padded));
    } catch {
      return null;
    }
  }

  // Access is persisted alongside refresh so a reload right after login
  // doesn't have to race an in-flight rotation. Refresh tokens rotate on
  // every /refresh call (revoking the old one), so calling /refresh
  // eagerly on every page load is what caused reload-during-boot to log
  // the user out. Persisting the short-lived access lets us skip that
  // eager refresh; api() still auto-refreshes on 401 when it expires.
  const state = {
    access: sessionStorage.getItem("access"),
    refresh: sessionStorage.getItem("refresh"),
    username: sessionStorage.getItem("username"),
    role: null,
    userId: null,
  };
  if (state.access) {
    const claims = decodeJwt(state.access);
    if (claims) {
      state.role = claims.role;
      state.userId = claims.sub;
    }
  }

  function set(access, refresh, username) {
    state.access = access;
    state.refresh = refresh;
    sessionStorage.setItem("access", access);
    sessionStorage.setItem("refresh", refresh);
    if (username) {
      state.username = username;
      sessionStorage.setItem("username", username);
    }
    const claims = decodeJwt(access);
    if (claims) {
      state.role = claims.role;
      state.userId = claims.sub;
    }
  }

  function clear() {
    Object.assign(state, { access: null, refresh: null, username: null, role: null, userId: null });
    sessionStorage.removeItem("access");
    sessionStorage.removeItem("refresh");
    sessionStorage.removeItem("username");
  }

  async function refreshOnce() {
    if (!state.refresh) return false;
    const r = await fetch("/refresh", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: state.refresh }),
    });
    if (!r.ok) { clear(); return false; }
    const t = await r.json();
    set(t.access_token, t.refresh_token);
    return true;
  }

  async function api(method, path, body) {
    const doFetch = () => {
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
      if (await refreshOnce()) {
        res = await doFetch();
      } else {
        window.location.href = "/";
        throw new Error("session expired");
      }
    }
    if (!res.ok) {
      let detail;
      try { detail = (await res.json()).detail; } catch { detail = res.statusText; }
      throw new Error(detail || `HTTP ${res.status}`);
    }
    return res.status === 204 ? null : res.json();
  }

  return { state, set, clear, refreshOnce, api };
})();
