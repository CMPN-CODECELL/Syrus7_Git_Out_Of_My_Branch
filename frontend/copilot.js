/**
 * Kraken copilot panel: chat, order confirmation cards, the order journal and live order updates.
 *
 * Contract: docs/API.md. Rules this file keeps:
 * - Every text from the server is rendered with textContent (replies can quote broker-supplied text).
 * - Order cards are rendered only from GET /v1/proposals/{id}, never from the chat reply.
 * - Approve sends back exactly the payload_hash of the card on screen. Nothing else can send an order.
 */
(() => {
    const STATUS_POLL_MS = 30000;
    const ORDERS_POLL_MS = 10000;   // polling fallback while the live socket is down
    const WS_PING_MS = 25000;
    const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000, 20000];

    const FINAL_JOURNAL_STATES = new Set(["REJECTED", "NOT_SENT", "NOT_PLACED"]);
    const FINAL_ORDER_STATUSES = new Set(["Executed", "Rejected", "Cancelled"]);

    const SUGGESTIONS = [
        "What's my P&L today?",
        "Which positions are down more than 5%?",
        "What's my average price on Reliance?",
        "Show the NIFTY option chain near ATM",
        "Which of my holdings have RSI below 30?",
        "Buy 10 Reliance at market",
    ];

    const state = {
        status: null,
        orders: new Map(),          // journal_id -> journal row
        cards: new Map(),           // proposal_id -> card controller
        ws: null,
        wsConnected: false,
        wsAttempt: 0,
        wsPing: null,
        pollTimer: null,
        sending: false,
    };

    const $ = (id) => document.getElementById(id);

    // ── small DOM helpers ──
    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = String(text);
        return node;
    }

    function rupees(paise) {
        if (paise === null || paise === undefined) return "-";
        return "₹" + (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function shortTime(iso) {
        if (!iso) return "-";
        const d = new Date(iso);
        return isNaN(d) ? String(iso) : d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    }

    function humanize(key) {
        return String(key).replace(/_/g, " ").replace(/\bpct\b/, "%").replace(/^./, (c) => c.toUpperCase());
    }

    function scalarText(value) {
        if (value === null || value === undefined) return "-";
        if (typeof value === "boolean") return value ? "yes" : "no";
        if (typeof value === "object") return JSON.stringify(value);
        return String(value);
    }

    /** Minimal, safe markdown: paragraphs, "- " bullets and **bold**, built from text nodes only. */
    function renderReplyText(container, text) {
        let list = null;
        String(text || "").split("\n").forEach((line) => {
            const bullet = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)$/);
            if (bullet) {
                if (!list) {
                    list = el("ul", "kc-reply-list");
                    container.appendChild(list);
                }
                const li = el("li");
                appendInline(li, bullet[1]);
                list.appendChild(li);
                return;
            }
            list = null;
            if (!line.trim()) return;
            const p = el("p");
            appendInline(p, line);
            container.appendChild(p);
        });
    }

    function appendInline(parent, text) {
        String(text).split(/(\*\*[^*]+\*\*)/g).forEach((part) => {
            if (!part) return;
            if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
                parent.appendChild(el("strong", null, part.slice(2, -2)));
            } else {
                parent.appendChild(document.createTextNode(part));
            }
        });
    }

    // ── view switching (the Option Chain / Technicals tabs are handled in app.js) ──
    function showCopilot() {
        $("tab-copilot")?.classList.add("active");
        $("tab-option-chain")?.classList.remove("active");
        $("tab-technicals")?.classList.remove("active");
        $("option-chain-view-container")?.style.setProperty("display", "none", "important");
        $("technicals-view-container")?.style.setProperty("display", "none", "important");
        $("copilot-view-container")?.style.setProperty("display", "block", "important");
        $("kc-input")?.focus();
    }

    function hideCopilot() {
        $("tab-copilot")?.classList.remove("active");
        $("copilot-view-container")?.style.setProperty("display", "none", "important");
    }

    document.addEventListener("click", (e) => {
        const target = e.target.closest("#tab-copilot, #tab-option-chain, #tab-technicals");
        if (!target) return;
        if (target.id === "tab-copilot") {
            e.preventDefault();
            showCopilot();
        } else {
            hideCopilot();
        }
    });

    // ── status ──
    async function refreshStatus() {
        try {
            const { ok, data } = await KrakenAPI.json("/v1/copilot/status");
            if (!ok || !data) throw new Error("status unavailable");
            state.status = data;
        } catch (e) {
            state.status = null;
        }
        renderStatus();
    }

    function renderStatus() {
        const bar = $("kc-status");
        if (!bar) return;
        bar.replaceChildren();
        const s = state.status;
        if (!s) {
            bar.appendChild(pill("Server", "bad", "Kraken server unreachable"));
            return;
        }
        bar.appendChild(pill("021 broker", s.broker_configured ? "ok" : "bad",
            s.broker_configured ? `Token valid until ${s.broker_token_expires_at || "first call"}` : "021 credentials not configured"));
        bar.appendChild(pill("Instruments", s.instruments_fresh ? "ok" : "warn",
            `${s.instruments_loaded || 0} loaded for ${s.instruments_for || "-"}`));
        bar.appendChild(pill("Market feed", s.market_feed_healthy ? "ok" : (s.market_socket_connected ? "warn" : "bad"),
            s.market_socket_connected ? `${s.subscriptions || 0} subscriptions` : "Market socket disconnected"));
        bar.appendChild(pill("AI", s.llm_configured ? "ok" : "bad", s.llm_configured ? "Gemini configured" : "GEMINI_API_KEY missing"));
        bar.appendChild(pill("Orders", s.orders_enabled ? (s.trading_kill_switch ? "warn" : "ok") : "bad",
            s.orders_enabled ? (s.trading_kill_switch ? "Kill switch is ON: approvals are blocked" : "Order cards enabled") : (s.orders_error || "Order features are off")));
        bar.appendChild(pill("Live orders", state.wsConnected ? "ok" : "warn",
            state.wsConnected ? "Live updates connected" : "Polling every 10 s"));

        const notice = $("kc-orders-notice");
        if (notice) {
            if (!s.orders_enabled) {
                notice.textContent = `Order cards are off: ${s.orders_error || "the order store is unavailable"}. Answers still work.`;
                notice.hidden = false;
            } else if (s.trading_kill_switch) {
                notice.textContent = "Trading kill switch is ON. Cards can't be created or approved.";
                notice.hidden = false;
            } else {
                notice.hidden = true;
            }
        }
        state.cards.forEach((card) => card.refreshButtons());
    }

    function pill(label, level, title) {
        const node = el("span", `kc-pill kc-${level}`, label);
        node.title = title || "";
        return node;
    }

    function ordersAllowed() {
        return !!(state.status && state.status.orders_enabled && !state.status.trading_kill_switch);
    }

    // ── chat ──
    function addMessage(role) {
        const log = $("kc-log");
        const wrap = el("div", `kc-msg kc-${role}`);
        const bubble = el("div", "kc-bubble");
        wrap.appendChild(bubble);
        log.appendChild(wrap);
        $("kc-empty")?.remove();
        return { wrap, bubble };
    }

    function scrollLog() {
        const log = $("kc-log");
        if (log) log.scrollTop = log.scrollHeight;
    }

    async function sendMessage(text) {
        text = (text || "").trim();
        if (!text || state.sending) return;
        state.sending = true;
        const input = $("kc-input");
        const sendBtn = $("kc-send");
        input.value = "";
        sendBtn.disabled = true;

        addMessage("user").bubble.textContent = text;
        const pending = addMessage("assistant");
        pending.bubble.classList.add("kc-thinking");
        pending.bubble.textContent = "Thinking…";
        scrollLog();

        try {
            const { ok, status, data } = await KrakenAPI.json("/v1/chat", { method: "POST", body: { message: text } });
            pending.bubble.classList.remove("kc-thinking");
            pending.bubble.replaceChildren();
            if (!ok) {
                pending.wrap.classList.add("kc-system");
                pending.bubble.textContent = (data && data.detail && typeof data.detail === "string")
                    ? data.detail
                    : `The request failed (HTTP ${status}).`;
                return;
            }
            renderReply(pending, data);
        } catch (e) {
            pending.bubble.classList.remove("kc-thinking");
            pending.wrap.classList.add("kc-system");
            pending.bubble.textContent = "Couldn't reach the Kraken server. Check that it is running and try again.";
        } finally {
            state.sending = false;
            sendBtn.disabled = false;
            input.focus();
            scrollLog();
        }
    }

    function renderReply(msg, data) {
        if (!data.llm_available) msg.wrap.classList.add("kc-system");
        renderReplyText(msg.bubble, data.reply);

        const tools = (data.tools || []).filter((t) => t && t.name);
        if (tools.length) {
            const row = el("div", "kc-tools");
            tools.forEach((t) => {
                const chip = el("span", `kc-tool ${t.ok ? "" : "kc-tool-failed"}`, t.name);
                chip.title = t.ok ? `${t.duration_ms ?? "?"} ms` : (t.error || "failed");
                row.appendChild(chip);
            });
            msg.bubble.appendChild(row);
        }

        (data.data || []).forEach((item) => {
            if (!item || !item.result || String(item.tool || "").startsWith("draft_")) return;
            msg.bubble.appendChild(renderToolData(item));
        });

        (data.proposals || []).forEach((id) => {
            const holder = el("div", "kc-card-slot");
            msg.wrap.appendChild(holder);
            loadCard(id, holder);
        });
    }

    /** Tables and numbers come from data[].result, not from parsing the reply (docs/API.md). */
    function renderToolData(item) {
        const details = el("details", "kc-data");
        const summary = el("summary", null, `${humanize(item.tool)} data`);
        if (item.result.as_of) summary.appendChild(el("span", "kc-muted", ` · as of ${shortTime(item.result.as_of)}`));
        details.appendChild(summary);

        const scalars = el("dl", "kc-kv");
        Object.entries(item.result).forEach(([key, value]) => {
            if (key === "as_of") return;
            if (Array.isArray(value)) {
                if (!value.length) return;
                details.appendChild(el("div", "kc-data-title", humanize(key)));
                if (value.every((v) => v && typeof v === "object" && !Array.isArray(v))) {
                    details.appendChild(renderTable(value));
                } else {
                    details.appendChild(el("div", "kc-data-list", value.map(scalarText).join(" · ")));
                }
            } else if (value && typeof value === "object") {
                details.appendChild(el("div", "kc-data-title", humanize(key)));
                details.appendChild(renderTable([value]));
            } else {
                scalars.appendChild(el("dt", null, humanize(key)));
                scalars.appendChild(el("dd", null, scalarText(value)));
            }
        });
        if (scalars.childNodes.length) details.insertBefore(scalars, details.children[1] || null);
        return details;
    }

    function renderTable(rows) {
        const columns = [];
        rows.forEach((r) => Object.keys(r).forEach((k) => { if (!columns.includes(k)) columns.push(k); }));
        const wrap = el("div", "kc-table-wrap");
        const table = el("table", "kc-table");
        const head = el("tr");
        columns.forEach((c) => head.appendChild(el("th", null, humanize(c))));
        table.appendChild(el("thead")).appendChild(head);
        const body = el("tbody");
        rows.forEach((r) => {
            const tr = el("tr");
            columns.forEach((c) => tr.appendChild(el("td", null, scalarText(r[c]))));
            body.appendChild(tr);
        });
        table.appendChild(body);
        wrap.appendChild(table);
        return wrap;
    }

    // ── order cards ──
    async function loadCard(proposalId, holder) {
        holder.textContent = "Loading order card…";
        try {
            const { ok, data } = await KrakenAPI.json(`/v1/proposals/${encodeURIComponent(proposalId)}`);
            holder.replaceChildren();
            if (!ok || !data) {
                holder.appendChild(el("div", "kc-card kc-card-error", "This order card could not be loaded. Ask again for a fresh one."));
                return;
            }
            mountCard(data, holder);
        } catch (e) {
            holder.textContent = "This order card could not be loaded.";
        }
    }

    function mountCard(view, holder) {
        const existing = state.cards.get(view.proposal_id);
        if (existing) existing.stop();
        const card = new OrderCard(view);
        state.cards.set(view.proposal_id, card);
        holder.replaceChildren(card.root);
        scrollLog();
        return card;
    }

    class OrderCard {
        constructor(view) {
            this.view = view;
            this.deadline = Date.now() + (view.seconds_left || 0) * 1000;
            this.busy = false;
            this.closed = view.state !== "PROPOSED";
            this.build();
            this.timer = setInterval(() => this.tick(), 1000);
            this.tick();
            if (view.state === "APPROVED") this.followJournal();
        }

        build() {
            const v = this.view;
            const c = v.card;
            const root = el("div", `kc-card kc-side-${(c.side || "").toLowerCase()}`);

            const head = el("div", "kc-card-head");
            let title;
            if (c.action === "MODIFY") title = `Modify order #${c.target_order_id || v.target_order_id}`;
            else if (c.action === "CANCEL") title = `Cancel order #${c.target_order_id || v.target_order_id}`;
            else title = `${c.side} ${c.quantity} × ${c.symbol}`;
            head.appendChild(el("span", "kc-card-title", title));
            if (c.amo) head.appendChild(el("span", "kc-badge kc-badge-amo", "AMO"));
            head.appendChild(el("span", `kc-badge kc-badge-${(c.side || "").toLowerCase()}`, c.side));
            root.appendChild(head);

            const grid = el("dl", "kc-card-grid");
            const add = (label, value) => {
                if (value === null || value === undefined || value === "") return;
                grid.appendChild(el("dt", null, label));
                grid.appendChild(el("dd", null, value));
            };
            add("Symbol", `${c.symbol} · ${c.exchange}`);
            add("Side", c.side);
            add("Quantity", c.lots ? `${c.quantity} (${c.lots} lot${c.lots > 1 ? "s" : ""} × ${c.lot_size})` : String(c.quantity));
            add("Order type", c.order_type);
            if (c.limit_price_paise !== null && c.limit_price_paise !== undefined) add("Limit price", rupees(c.limit_price_paise));
            if (c.trigger_price_paise !== null && c.trigger_price_paise !== undefined) add("Trigger price", rupees(c.trigger_price_paise));
            add("Product", c.product);
            add("Validity", c.validity);
            if (c.reference_ltp_paise) add("Reference price", `${rupees(c.reference_ltp_paise)} at ${shortTime(c.reference_ltp_as_of)} (021)`);
            if (c.estimated_value_paise) add("Estimated value", rupees(c.estimated_value_paise));
            root.appendChild(grid);

            if (c.notices && c.notices.length) {
                const ul = el("ul", "kc-notices");
                c.notices.forEach((n) => ul.appendChild(el("li", null, n)));
                root.appendChild(ul);
            }

            const foot = el("div", "kc-card-foot");
            this.statusLine = el("span", "kc-card-status");
            this.countdown = el("span", "kc-countdown");
            this.approveBtn = el("button", "kc-btn kc-approve", "Approve");
            this.rejectBtn = el("button", "kc-btn kc-reject", "Reject");
            this.approveBtn.type = "button";
            this.rejectBtn.type = "button";
            this.approveBtn.addEventListener("click", () => this.approve());
            this.rejectBtn.addEventListener("click", () => this.reject());
            foot.appendChild(this.statusLine);
            foot.appendChild(this.countdown);
            foot.appendChild(this.rejectBtn);
            foot.appendChild(this.approveBtn);
            root.appendChild(foot);
            root.appendChild(el("div", "kc-card-hash", `Payload ${v.payload_hash.slice(0, 12)}…`));

            this.root = root;
            if (this.closed) this.setStatus(this.describeClosed(), v.state === "APPROVED" ? "info" : "muted");
            this.refreshButtons();
        }

        describeClosed() {
            const v = this.view;
            if (v.state === "APPROVED") return "Approved";
            if (v.state === "REJECTED") return "Rejected";
            if (v.state === "EXPIRED") return "Expired. Ask again for a fresh card.";
            return v.state_reason || v.state;
        }

        secondsLeft() {
            return Math.max(0, Math.ceil((this.deadline - Date.now()) / 1000));
        }

        tick() {
            if (this.closed) {
                this.countdown.textContent = "";
                return;
            }
            const left = this.secondsLeft();
            this.countdown.textContent = left > 0 ? `${left}s left` : "";
            if (left <= 0) {
                this.closed = true;
                this.setStatus("Expired. Ask again for a fresh card.", "muted");
            }
            this.refreshButtons();
        }

        refreshButtons() {
            const live = !this.closed && !this.busy && this.secondsLeft() > 0;
            this.approveBtn.hidden = this.closed || !(state.status && state.status.orders_enabled);
            this.rejectBtn.hidden = this.closed;
            this.approveBtn.disabled = !live || !ordersAllowed();
            this.rejectBtn.disabled = !live;
        }

        setStatus(text, level) {
            this.statusLine.textContent = text;
            this.statusLine.className = `kc-card-status kc-status-${level || "info"}`;
        }

        stop() {
            clearInterval(this.timer);
        }

        close(text, level) {
            this.closed = true;
            this.setStatus(text, level);
            this.refreshButtons();
            this.tick();
        }

        async approve() {
            if (this.closed || this.busy) return;
            this.busy = true;
            this.refreshButtons();
            this.setStatus("Sending…", "info");
            try {
                const { status, data } = await KrakenAPI.json(`/v1/proposals/${encodeURIComponent(this.view.proposal_id)}/approve`, {
                    method: "POST",
                    body: { payload_hash: this.view.payload_hash },
                });
                this.handleApproveResult(status, data || {});
            } catch (e) {
                this.setStatus("The approval didn't reach the server. Check the Orders list before trying again.", "bad");
            } finally {
                this.busy = false;
                this.refreshButtons();
            }
        }

        handleApproveResult(httpStatus, data) {
            if (data.order) upsertOrder(data.order);
            const message = data.message || data.detail || `HTTP ${httpStatus}`;
            if (httpStatus === 409 && data.status === "requote" && data.new_proposal) {
                this.close("Price moved more than 0.5%. Here is a fresh card at the new price.", "warn");
                this.mountReplacement(data.new_proposal);
                return;
            }
            switch (data.status) {
                case "sent":
                    this.close(`Sent to 021 · order #${data.order?.order_id ?? "?"}`, "ok");
                    this.journalId = data.order?.journal_id;
                    this.showJournal(data.order);
                    break;
                case "rejected":
                    this.close(`Rejected by 021: ${data.order?.reason || message}`, "bad");
                    break;
                case "not_sent":
                    // 021 never processed it; the server may attach a fresh card for a new approval.
                    this.close(message, "bad");
                    if (data.new_proposal) this.mountReplacement(data.new_proposal);
                    break;
                case "unknown":
                    this.close("Sent, but 021 didn't confirm. Checking the order book; it will not be resent…", "warn");
                    this.journalId = data.order?.journal_id;
                    break;
                default:
                    if (httpStatus === 410) this.close("This card expired. Ask again for a fresh card.", "muted");
                    else if (httpStatus === 423) this.close(message, "bad");
                    else if (httpStatus === 409 && data.proposal && data.proposal.state === "EXPIRED") {
                        // A failed pre-send check closes the card on the server; only a new card can be approved.
                        this.close(`${message} Ask Kraken again for a fresh card.`, "bad");
                    } else if (httpStatus === 409 || httpStatus === 404) this.close(message, "bad");
                    else this.setStatus(message, "bad");
            }
        }

        mountReplacement(view) {
            const slot = el("div", "kc-card-slot");
            this.root.parentElement.after(slot);
            mountCard(view, slot);
        }

        followJournal() {
            for (const row of state.orders.values()) {
                if (row.proposal_id === this.view.proposal_id) {
                    this.journalId = row.journal_id;
                    this.showJournal(row);
                }
            }
        }

        /** Live journal updates (WS or polling) for the order this card sent. */
        showJournal(row) {
            if (!row) return;
            const text = journalSummary(row);
            const level = row.state === "ACKED"
                ? (row.order_status === "Rejected" ? "bad" : (row.order_status === "Executed" ? "ok" : "info"))
                : (FINAL_JOURNAL_STATES.has(row.state) ? "bad" : "warn");
            this.setStatus(text, level);
        }

        async reject() {
            if (this.closed || this.busy) return;
            this.busy = true;
            this.refreshButtons();
            try {
                const { ok, data } = await KrakenAPI.json(`/v1/proposals/${encodeURIComponent(this.view.proposal_id)}/reject`, {
                    method: "POST",
                    body: {},
                });
                this.close(ok ? "Rejected. Nothing was sent." : ((data && data.detail) || "Couldn't reject this card."), ok ? "muted" : "bad");
            } catch (e) {
                this.setStatus("Couldn't reach the server.", "bad");
            } finally {
                this.busy = false;
                this.refreshButtons();
            }
        }
    }

    function journalSummary(row) {
        switch (row.state) {
            case "SENDING": return "Sending…";
            case "UNKNOWN": return "Sent, waiting for 021 to confirm (never resent)…";
            case "NOT_SENT": return `Not sent: ${row.reason || "it never reached 021"}`;
            case "NOT_PLACED": return "021 has no such order: it was not placed.";
            case "AMBIGUOUS": return "Several 021 orders could match. Check the 021 order book; nothing is resent.";
            case "REJECTED": return `Rejected by 021: ${row.reason || "no reason given"}`;
            case "ACKED": {
                let text = `Order #${row.order_id} · ${row.order_status || "Placed"}`;
                if (row.filled_qty) text += ` · filled ${row.filled_qty}${row.avg_fill_price_paise ? ` @ ${rupees(row.avg_fill_price_paise)}` : ""}`;
                if (row.order_status === "Rejected" && row.reason) text += ` · ${row.reason}`;
                return text;
            }
            default: return row.state;
        }
    }

    // ── order journal ──
    async function loadOrders() {
        try {
            const { ok, data } = await KrakenAPI.json("/v1/orders?limit=50");
            if (!ok || !data) return;
            (data.orders || []).forEach((row) => upsertOrder(row, false));
            renderOrders();
        } catch (e) {
            // the next poll or socket message will catch up
        }
    }

    function upsertOrder(row, render = true) {
        if (!row || !row.journal_id) return;
        state.orders.set(row.journal_id, row);
        state.cards.forEach((card) => {
            if (card.view.proposal_id === row.proposal_id || card.journalId === row.journal_id) {
                card.journalId = row.journal_id;
                card.showJournal(row);
            }
        });
        if (render) renderOrders();
    }

    function renderOrders() {
        const body = $("kc-orders-body");
        if (!body) return;
        const rows = [...state.orders.values()].sort((a, b) => String(b.sent_at).localeCompare(String(a.sent_at)));
        body.replaceChildren();
        $("kc-orders-empty").hidden = rows.length > 0;
        rows.forEach((row) => {
            const c = row.card || {};
            const tr = el("tr");
            tr.appendChild(el("td", "kc-mono", shortTime(row.sent_at)));
            const what = c.action && c.action !== "PLACE"
                ? `${c.action === "MODIFY" ? "Modify" : "Cancel"} #${c.target_order_id || "?"}`
                : `${c.side || ""} ${c.quantity || ""} ${c.symbol || ""}`.trim();
            tr.appendChild(el("td", null, what || row.action));
            tr.appendChild(el("td", null, c.order_type ? `${c.order_type}${c.limit_price_paise ? " " + rupees(c.limit_price_paise) : ""}` : "-"));
            const stateCell = el("td");
            stateCell.appendChild(el("span", `kc-state kc-state-${String(row.state).toLowerCase()}`, row.state));
            tr.appendChild(stateCell);
            tr.appendChild(el("td", null, row.order_status || "-"));
            tr.appendChild(el("td", "kc-mono", row.order_id || "-"));
            tr.appendChild(el("td", null, row.filled_qty ? `${row.filled_qty}${row.avg_fill_price_paise ? " @ " + rupees(row.avg_fill_price_paise) : ""}` : "-"));
            tr.appendChild(el("td", "kc-reason", row.reason || ""));
            body.appendChild(tr);
        });
    }

    // ── live order updates ──
    function connectOrdersSocket() {
        if (state.ws) return;
        const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        const ws = new WebSocket(`${proto}//${window.location.host}/v1/stream/orders`);
        state.ws = ws;

        ws.onopen = async () => {
            const jwt = await KrakenAPI.token();
            if (!jwt || ws.readyState !== WebSocket.OPEN) {
                ws.close();
                return;
            }
            ws.send(JSON.stringify({ type: "auth", token: jwt }));
        };

        ws.onmessage = (event) => {
            let msg;
            try {
                msg = JSON.parse(event.data);
            } catch (e) {
                return;
            }
            if (msg.type === "ready") {
                state.wsConnected = true;
                state.wsAttempt = 0;
                stopPolling();
                loadOrders();   // catch up on anything missed while disconnected
                state.wsPing = setInterval(() => {
                    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
                }, WS_PING_MS);
                renderStatus();
            } else if (msg.type === "order_update" && msg.order) {
                upsertOrder(msg.order);
            }
        };

        ws.onclose = (event) => {
            clearInterval(state.wsPing);
            state.ws = null;
            const wasConnected = state.wsConnected;
            state.wsConnected = false;
            if (wasConnected) renderStatus();
            startPolling();
            if (event.code === 4403) return;   // origin not allowed: retrying won't help
            const delay = RECONNECT_DELAYS_MS[Math.min(state.wsAttempt, RECONNECT_DELAYS_MS.length - 1)];
            state.wsAttempt += 1;
            setTimeout(connectOrdersSocket, delay);
        };

        ws.onerror = () => {
            // onclose follows and schedules the reconnect
        };
    }

    function startPolling() {
        if (state.pollTimer) return;
        state.pollTimer = setInterval(loadOrders, ORDERS_POLL_MS);
    }

    function stopPolling() {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
    }

    // ── setup ──
    function renderSuggestions() {
        const box = $("kc-suggestions");
        if (!box) return;
        SUGGESTIONS.forEach((text) => {
            const chip = el("button", "kc-suggestion", text);
            chip.type = "button";
            chip.addEventListener("click", () => sendMessage(text));
            box.appendChild(chip);
        });
    }

    async function clearHistory() {
        try {
            await KrakenAPI.request("/v1/chat/history", { method: "DELETE" });
        } catch (e) {
            // the local log is cleared either way
        }
        state.cards.forEach((card) => card.stop());
        state.cards.clear();
        const log = $("kc-log");
        log.replaceChildren();
        const empty = el("div", "kc-empty");
        empty.id = "kc-empty";
        empty.textContent = "Conversation cleared. Ask about your portfolio, prices, option chains or technicals, or ask Kraken to prepare an order card.";
        log.appendChild(empty);
    }

    async function init() {
        if (!$("copilot-view-container")) return;
        const supabase = await initSupabase();
        if (!supabase) return;
        const { data: { session } } = await supabase.auth.getSession();
        if (!session) return;   // the dashboard auth guard redirects to the login page

        renderSuggestions();
        $("kc-form").addEventListener("submit", (e) => {
            e.preventDefault();
            sendMessage($("kc-input").value);
        });
        $("kc-input").addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage($("kc-input").value);
            }
        });
        $("kc-clear").addEventListener("click", clearHistory);
        $("kc-orders-refresh").addEventListener("click", loadOrders);

        if (window.location.hash !== "#option-chain") showCopilot();

        await refreshStatus();
        setInterval(refreshStatus, STATUS_POLL_MS);
        await loadOrders();
        startPolling();
        connectOrdersSocket();
    }

    document.addEventListener("DOMContentLoaded", init);
})();
