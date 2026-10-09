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
        root.querySelectorAll(`img[src*="${TEMPLATE_WORDMARK}"]`).forEach((img) => {
            img.src = "/kraken-wordmark.svg";
            img.alt = "Kraken";
        });
        if (BRAND_FROM.test(document.title)) document.title = "Kraken – AI Trading Copilot";
        BRAND_FROM.lastIndex = 0;
    }

    function fixAll() {
        fixLinks(document);
        fixBrand(document.body);
    }

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
