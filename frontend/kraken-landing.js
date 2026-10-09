/**
 * Kraken glue for the landing page (index.html, a saved Framer template).
 * The template's buttons point at template pages that don't exist here (pricing, contact,
 * request-demo, waitlist, ...). This routes them into the app and renames the template brand.
 * Framer may re-render the page after load, so the fixes are re-applied on DOM changes and
 * clicks are also routed in the capture phase.
 */
(() => {
    const APP_ENTRY = "/login.html";   // login.html forwards to the dashboard when already signed in
    const ROUTES = {
        "pricing": APP_ENTRY, "contact": APP_ENTRY, "request-demo": APP_ENTRY, "waitlist": APP_ENTRY,
        "feature": APP_ENTRY, "about": APP_ENTRY, "blog": APP_ENTRY, "changelog": APP_ENTRY, "faqs": APP_ENTRY,
        "404": "/", "legal-pages/privacy-policy": "/terms.html",
    };
    const BRAND_FROM = /FintechX/g;
    const BRAND_TO = "Kraken";
    const TEMPLATE_WORDMARK = "YRLlnG3joxHrTMikBU58pHjeOA.svg";

    function targetFor(anchor) {
        const raw = anchor.getAttribute("href");
        if (!raw || raw.startsWith("#") || raw.startsWith("mailto:")) return null;
        let url;
        try {
            url = new URL(raw, window.location.origin + "/");
        } catch (e) {
            return null;
        }
        if (url.origin !== window.location.origin) return null;
        const page = url.pathname.replace(/^\/+|\/+$/g, "");
        return Object.prototype.hasOwnProperty.call(ROUTES, page) ? ROUTES[page] : null;
    }

    function fixLinks(root) {
        root.querySelectorAll("a[href]").forEach((a) => {
            const target = targetFor(a);
            if (target && a.getAttribute("href") !== target) a.setAttribute("href", target);
        });
    }

    function fixBrand(root) {
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
            if (BRAND_FROM.test(node.nodeValue)) node.nodeValue = node.nodeValue.replace(BRAND_FROM, BRAND_TO);
            BRAND_FROM.lastIndex = 0;
        }
        const wordmark = window.KrakenTheme ? window.KrakenTheme.wordmark() : "/kraken-wordmark.svg";
        root.querySelectorAll(`img[src*="${TEMPLATE_WORDMARK}"], img[src*="kraken-wordmark"]`).forEach((img) => {
            if (!img.getAttribute("src").endsWith(wordmark)) img.src = wordmark;
            img.alt = "Kraken";
            img.setAttribute("data-kraken-wordmark", "");
        });
        if (BRAND_FROM.test(document.title)) document.title = "Kraken – AI Trading Copilot";
        BRAND_FROM.lastIndex = 0;
    }

    /** Framer fades sections into white with gradients set in its stylesheet. Tag them once so
     *  kraken-landing.css can fade into black in dark mode. */
    let fades = null;   // [{node, original}]
    function applyFades() {
        if (fades === null) {
            fades = [];
            document.querySelectorAll("body *").forEach((node) => {
                const bg = getComputedStyle(node).backgroundImage;
                if (bg && bg.includes("gradient") && /rgba?\(255, 255, 255/.test(bg)) fades.push({ node, original: bg });
            });
        }
        const dark = document.documentElement.getAttribute("data-theme") === "dark";
        fades.forEach(({ node, original }) => {
            node.style.backgroundImage = dark
                ? original.replace(/rgb\(255, 255, 255\)/g, "rgb(10, 10, 10)").replace(/rgba\(255, 255, 255,/g, "rgba(10, 10, 10,")
                : "";
        });
    }

    function fixAll() {
        fixLinks(document);
        fixBrand(document.body);
    }

    window.addEventListener("kraken-theme", () => {
        fixAll();
        if (fades !== null) applyFades();
    });
    window.addEventListener("load", () => setTimeout(applyFades, 300));

    // Route clicks before Framer's client-side router sees them.
    window.addEventListener("click", (e) => {
        const a = e.target.closest && e.target.closest("a[href]");
        if (!a) return;
        const target = targetFor(a) || (Object.values(ROUTES).includes(a.getAttribute("href")) ? a.getAttribute("href") : null);
        if (!target) return;
        e.preventDefault();
        e.stopImmediatePropagation();
        window.location.href = target;
    }, true);

    let scheduled = false;
    const observer = new MutationObserver(() => {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(() => {
            scheduled = false;
            fixAll();
        });
    });

    function start() {
        fixAll();
        observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
    else start();
})();
