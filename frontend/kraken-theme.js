/**
 * Kraken theme switch, shared by every page: light = white/gold, dark = black/gold.
 * Load it synchronously in <head> so the saved theme applies before first paint.
 * Sets <html data-theme="light|dark"> (read by kraken-theme.css) and keeps the dashboard's
 * legacy body.light-theme class in sync. Pages without their own toggle get a floating one.
 */
(function () {
    var KEY = "krakenTheme";

    function saved() {
        try {
            return localStorage.getItem(KEY) || localStorage.getItem("shaniTheme");
        } catch (e) {
            return null;
        }
    }

    function initial() {
        var s = saved();
        if (s === "dark" || s === "light") return s;
        return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }

    var theme = initial();

    function wordmarkFor(t) {
        return t === "dark" ? "/kraken-wordmark-dark.svg" : "/kraken-wordmark.svg";
    }

    function apply(t) {
        theme = t;
        var root = document.documentElement;
        root.setAttribute("data-theme", t);
        root.style.colorScheme = t;
        if (document.body) {
            document.body.classList.toggle("light-theme", t === "light");
            document.querySelectorAll("img[data-kraken-wordmark]").forEach(function (img) {
                img.src = wordmarkFor(t);
            });
        }
        try {
            window.dispatchEvent(new CustomEvent("kraken-theme", { detail: t }));
        } catch (e) {
            // very old browsers: the attribute alone is enough
        }
    }

    function set(t) {
        try {
            localStorage.setItem(KEY, t);
        } catch (e) {
            // private mode: the choice lasts for this page only
        }
        apply(t);
    }

    var SUN = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
    var MOON = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';

    function injectToggle() {
        if (document.getElementById("theme-toggle-btn") || document.getElementById("k-theme-toggle")) return;
        var btn = document.createElement("button");
        btn.id = "k-theme-toggle";
        btn.type = "button";
        btn.className = "k-theme-toggle";
        function paint() {
            btn.innerHTML = theme === "dark" ? SUN : MOON;
            btn.title = theme === "dark" ? "Switch to light (white/gold)" : "Switch to dark (black/gold)";
            btn.setAttribute("aria-label", btn.title);
        }
        btn.addEventListener("click", function () {
            set(theme === "dark" ? "light" : "dark");
        });
        window.addEventListener("kraken-theme", paint);
        paint();
        document.body.appendChild(btn);
    }

    apply(theme);
    window.KrakenTheme = {
        get: function () { return theme; },
        set: set,
        toggle: function () { set(theme === "dark" ? "light" : "dark"); },
        wordmark: function () { return wordmarkFor(theme); },
    };
    document.addEventListener("DOMContentLoaded", function () {
        apply(theme);
        injectToggle();
    });
})();
