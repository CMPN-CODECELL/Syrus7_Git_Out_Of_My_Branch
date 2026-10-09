/**
 * Kraken API helper: every call to a protected route carries the Supabase access token as a
 * Bearer header. The token lives in JavaScript storage (Supabase's own), never in a cookie:
 * Kraken uses no CSRF token, which is only safe while auth stays header-based (docs/DECISIONS.md ADR-011).
 */
const KrakenAPI = (() => {
    async function token() {
        const supabase = await initSupabase();
        if (!supabase) return null;
        // getSession() refreshes an expired access token before returning it.
        const { data: { session } } = await supabase.auth.getSession();
        return session ? session.access_token : null;
    }

    async function request(path, { method = "GET", body, headers = {} } = {}) {
        const jwt = await token();
        if (!jwt) {
            window.location.href = "/login.html";
            throw new Error("Not signed in");
        }
        const init = { method, headers: { Authorization: `Bearer ${jwt}`, ...headers } };
        if (body !== undefined) {
            init.headers["Content-Type"] = "application/json";
            init.body = JSON.stringify(body);
        }
        const res = await fetch(path, init);
        if (res.status === 401) {
            window.location.href = "/login.html";
        }
        return res;
    }

    async function json(path, options) {
        const res = await request(path, options);
        let data = null;
        try {
            data = await res.json();
        } catch (e) {
            data = null;
        }
        return { ok: res.ok, status: res.status, data };
    }

    return { token, request, json };
})();

window.KrakenAPI = KrakenAPI;
