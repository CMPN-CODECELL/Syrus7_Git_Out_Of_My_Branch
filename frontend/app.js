/**
 * NSE Option Chain Clone - BSM Calculator & Dynamic Solver Engine
 */

// Global State
let appState = {
    symbol: "NIFTY",
    marketSpot: 0.0,
    marketVol: 15.0,
    marketDays: 30,
    marketRate: 6.50,
    marketYield: 1.20,
    optionChains: {},  // Map of expiry_date -> list of OptionChainRow
    expiryDates: [],
    selectedExpiry: "",
    selectedStrike: "ALL",
    showFullChain: false,
    applySimulation: false,
    // Model parameters
    spot: 0.0,
    volatility: 12.8,
    daysToExpiry: 5,
    riskFreeRate: 6.50,
    dividendYield: 1.20,
    // ATM Option Strike Info
    atmStrike: 0.0,
    lastPriceUpdated: null,
    technicals: null,
    // Layout and Theme configuration
    layoutMode: "standard",
    theme: "light"
};

// WebSocket and inspection states
let currentSocket = null;
let activeSocketSymbol = null;
let activeInspectedStrike = null;

// DOM Elements
const elements = {
    symbolSearchInput: document.getElementById("symbol-search-input"),
    searchSuggestions: document.getElementById("search-suggestions"),
    expirySelect: document.getElementById("expiry-select"),
    underlyingSymbol: document.getElementById("underlying-symbol"),
    underlyingPrice: document.getElementById("underlying-price"),
    underlyingTime: document.getElementById("underlying-time"),
    underlyingTimeElapsed: document.getElementById("underlying-time-elapsed"),
    reloadBtn: document.getElementById("reload-btn"),
    downloadCsvBtn: document.getElementById("download-csv-btn"),
    
    // BSM Modal elements
    openBsmModalBtn: document.getElementById("open-bsm-modal-btn"),
    bsmModal: document.getElementById("bsm-modal"),
    bsmModalClose: document.getElementById("bsm-modal-close"),
    applySimulationToggle: document.getElementById("apply-simulation-toggle"),
    toggleFullChainBtn: document.getElementById("toggle-full-chain-btn"),
    
    // BSM Controls
    bsmSpot: document.getElementById("bsm-spot"),
    bsmSpotSlider: document.getElementById("bsm-spot-slider"),
    spotCurrency: document.getElementById("spot-currency"),
    spotMinLbl: document.getElementById("spot-min-lbl"),
    spotMaxLbl: document.getElementById("spot-max-lbl"),
    
    bsmVol: document.getElementById("bsm-vol"),
    bsmVolSlider: document.getElementById("bsm-vol-slider"),
    
    bsmDays: document.getElementById("bsm-days"),
    bsmDaysSlider: document.getElementById("bsm-days-slider"),
    
    bsmRate: document.getElementById("bsm-rate"),
    bsmRateSlider: document.getElementById("bsm-rate-slider"),
    
    bsmDiv: document.getElementById("bsm-div"),
    bsmDivSlider: document.getElementById("bsm-div-slider"),
    
    resetMarketBtn: document.getElementById("reset-market-btn"),
    bsmCalculateBtn: document.getElementById("bsm-calculate-btn"),
    
    // ATM Outputs
    atmStrikeVal: document.getElementById("atm-strike-val"),
    atmCallPrice: document.getElementById("atm-call-price"),
    atmCallDelta: document.getElementById("atm-call-delta"),
    atmCallTheta: document.getElementById("atm-call-theta"),
    atmCallRho: document.getElementById("atm-call-rho"),
    
    atmGamma: document.getElementById("atm-gamma"),
    atmVega: document.getElementById("atm-vega"),
    
    atmPutPrice: document.getElementById("atm-put-price"),
    atmPutDelta: document.getElementById("atm-put-delta"),
    atmPutTheta: document.getElementById("atm-put-theta"),
    atmPutRho: document.getElementById("atm-put-rho"),
    
    // Table Body
    tableBody: document.getElementById("option-chain-tbody"),
    
    // Modal
    greeksModal: document.getElementById("greeks-modal"),
    modalClose: document.getElementById("modal-close"),
    modalStrikePrice: document.getElementById("modal-strike-price"),
    modalCLtp: document.getElementById("modal-c-ltp"),
    modalCBsVal: document.getElementById("modal-c-bs-val"),
    modalCEdge: document.getElementById("modal-c-edge"),
    modalCDelta: document.getElementById("modal-c-delta"),
    modalCGamma: document.getElementById("modal-c-gamma"),
    modalCVega: document.getElementById("modal-c-vega"),
    modalCTheta: document.getElementById("modal-c-theta"),
    modalCRho: document.getElementById("modal-c-rho"),
    
    modalPLtp: document.getElementById("modal-p-ltp"),
    modalPBsVal: document.getElementById("modal-p-bs-val"),
    modalPEdge: document.getElementById("modal-p-edge"),
    modalPDelta: document.getElementById("modal-p-delta"),
    modalPGamma: document.getElementById("modal-p-gamma"),
    modalPVega: document.getElementById("modal-p-vega"),
    modalPTheta: document.getElementById("modal-p-theta"),
    modalPRho: document.getElementById("modal-p-rho"),
    
    modalInSpot: document.getElementById("modal-in-spot"),
    modalInVol: document.getElementById("modal-in-vol"),
    modalInDays: document.getElementById("modal-in-days"),
    modalInRate: document.getElementById("modal-in-rate"),
    modalInDiv: document.getElementById("modal-in-div"),
    modalD1: document.getElementById("modal-d1"),
    modalD2: document.getElementById("modal-d2"),
    modalNd1: document.getElementById("modal-nd1"),
    modalNd2: document.getElementById("modal-nd2"),
    
    // New modal market data elements
    modalCOi: document.getElementById("modal-c-oi"),
    modalCOiChg: document.getElementById("modal-c-oi-chg"),
    modalCVolume: document.getElementById("modal-c-volume"),
    modalCIv: document.getElementById("modal-c-iv"),
    modalCChg: document.getElementById("modal-c-chg"),
    modalCBidPrice: document.getElementById("modal-c-bid-price"),
    modalCBidQty: document.getElementById("modal-c-bid-qty"),
    modalCAskPrice: document.getElementById("modal-c-ask-price"),
    modalCAskQty: document.getElementById("modal-c-ask-qty"),

    modalPOi: document.getElementById("modal-p-oi"),
    modalPOiChg: document.getElementById("modal-p-oi-chg"),
    modalPVolume: document.getElementById("modal-p-volume"),
    modalPIv: document.getElementById("modal-p-iv"),
    modalPChg: document.getElementById("modal-p-chg"),
    modalPBidPrice: document.getElementById("modal-p-bid-price"),
    modalPBidQty: document.getElementById("modal-p-bid-qty"),
    modalPAskPrice: document.getElementById("modal-p-ask-price"),
    modalPAskQty: document.getElementById("modal-p-ask-qty"),
    
    // Info and Regulatory modal elements
    userManualBtn: document.getElementById("user-manual-btn"),
    termsBtn: document.getElementById("terms-btn"),
    infoModal: document.getElementById("info-modal"),
    infoModalClose: document.getElementById("info-modal-close")
};

// ----------------------------------------------------
// Black-Scholes-Merton Pricing Formula Math Block
// ----------------------------------------------------

/**
 * Standard standard normal probability density function
 */
function ndensity(x) {
    return Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI);
}

/**
 * High-precision Hastings approximation for cumulative normal distribution function
 */
function cndist(x) {
    const a1 = 0.319381530;
    const a2 = -0.356563782;
    const a3 = 1.781477937;
    const a4 = -1.821255978;
    const a5 = 1.330274429;
    const L = Math.abs(x);
    const K = 1.0 / (1.0 + 0.2316419 * L);
    const cnd = 1.0 - 1.0 / Math.sqrt(2 * Math.PI) * Math.exp(-L * L / 2) * 
        (a1 * K + a2 * Math.pow(K, 2) + a3 * Math.pow(K, 3) + a4 * Math.pow(K, 4) + a5 * Math.pow(K, 5));
    return x < 0 ? 1.0 - cnd : cnd;
}

/**
 * Black-Scholes-Merton analytic pricer and greeks calculation
 */
function calculateBSM(S, K, T_days, r_pct, sigma_pct, q_pct) {
    // Conversions
    const T = Math.max(T_days, 0.001) / 365.0; // Avoid division by zero
    const r = r_pct / 100.0;
    const sigma = Math.max(0.0001, sigma_pct / 100.0); // Safeguard against zero/negative volatility
    const q = q_pct / 100.0;

    if (S <= 0 || K <= 0) {
        return {
            call: 0.0, put: 0.0,
            deltaCall: 0.0, deltaPut: 0.0,
            gamma: 0.0, vega: 0.0,
            thetaCall: 0.0, thetaPut: 0.0,
            rhoCall: 0.0, rhoPut: 0.0,
            d1: 0, d2: 0, nd1: 0, nd2: 0
        };
    }

    let d1, d2, Nd1, Nd2, NminusD1, NminusD2, nd1Val;
    
    try {
        d1 = (Math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * Math.sqrt(T));
        d2 = d1 - sigma * Math.sqrt(T);
        Nd1 = cndist(d1);
        Nd2 = cndist(d2);
        NminusD1 = cndist(-d1);
        NminusD2 = cndist(-d2);
        nd1Val = ndensity(d1);
    } catch (e) {
        return {
            call: 0.0, put: 0.0,
            deltaCall: 0.0, deltaPut: 0.0,
            gamma: 0.0, vega: 0.0,
            thetaCall: 0.0, thetaPut: 0.0,
            rhoCall: 0.0, rhoPut: 0.0,
            d1: 0, d2: 0, nd1: 0, nd2: 0
        };
    }

    // Call and Put Prices
    const callPrice = S * Math.exp(-q * T) * Nd1 - K * Math.exp(-r * T) * Nd2;
    const putPrice = K * Math.exp(-r * T) * NminusD2 - S * Math.exp(-q * T) * NminusD1;

    // Greeks calculations
    const deltaCall = Math.exp(-q * T) * Nd1;
    const deltaPut = -Math.exp(-q * T) * NminusD1;
    
    const gamma = (Math.exp(-q * T) * nd1Val) / (S * sigma * Math.sqrt(T));
    
    // Vega per 1% change in volatility
    const vega = (S * Math.exp(-q * T) * Math.sqrt(T) * nd1Val) / 100.0;
    
    // Theta per calendar day decay
    const term1 = -(S * Math.exp(-q * T) * nd1Val * sigma) / (2 * Math.sqrt(T));
    const term2Call = r * K * Math.exp(-r * T) * Nd2;
    const term3Call = q * S * Math.exp(-q * T) * Nd1;
    const thetaCall = (term1 - term2Call + term3Call) / 365.0;

    const term2Put = r * K * Math.exp(-r * T) * NminusD2;
    const term3Put = q * S * Math.exp(-q * T) * NminusD1;
    const thetaPut = (term1 + term2Put - term3Put) / 365.0;

    // Rho per 1% change in risk-free rate
    const rhoCall = (K * T * Math.exp(-r * T) * Nd2) / 100.0;
    const rhoPut = (-K * T * Math.exp(-r * T) * NminusD2) / 100.0;

    return {
        call: Math.max(callPrice, 0.0),
        put: Math.max(putPrice, 0.0),
        deltaCall: deltaCall,
        deltaPut: deltaPut,
        gamma: gamma,
        vega: vega,
        thetaCall: thetaCall,
        thetaPut: thetaPut,
        rhoCall: rhoCall,
        rhoPut: rhoPut,
        d1: d1,
        d2: d2,
        nd1: Nd1,
        nd2: Nd2
    };
}

// ----------------------------------------------------
// UI Logic, Bindings & API Integration Block
// ----------------------------------------------------

/**
 * Format numeric value with commas as thousands separators and fixed decimals
 */
function formatNumber(num, decimals = 2, defaultVal = "-") {
    if (num === null || num === undefined || isNaN(num)) return defaultVal;
    return Number(num).toLocaleString('en-IN', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    });
}

/**
 * Automatically enable simulation flag and check UI toggle
 */
function activateSimulation() {
    appState.applySimulation = true;
    const applyToggle = elements.applySimulationToggle || document.getElementById("apply-simulation-toggle");
    if (applyToggle) {
        applyToggle.checked = true;
    }
}

/**
 * Synchronize slider input value with numeric input field
 */
function bindSlider(numInput, sliderInput, stateProp, callback) {
    numInput.addEventListener("input", (e) => {
        let val = parseFloat(e.target.value);
        if (isNaN(val)) return;
        
        // Update state and slider without clamping on every keystroke
        sliderInput.value = val;
        appState[stateProp] = val;
        if (callback) callback();
    });
    
    numInput.addEventListener("blur", (e) => {
        let val = parseFloat(e.target.value);
        if (isNaN(val)) return;
        
        // Clamp only on blur
        const min = parseFloat(sliderInput.min);
        const max = parseFloat(sliderInput.max);
        if (val < min) val = min;
        if (val > max) val = max;
        
        numInput.value = val;
        sliderInput.value = val;
        appState[stateProp] = val;
        if (callback) callback();
    });
    
    const updateFromSlider = (e) => {
        let val = parseFloat(e.target.value);
        numInput.value = val;
        appState[stateProp] = val;
        if (callback) callback();
    };
    sliderInput.addEventListener("input", updateFromSlider);
    sliderInput.addEventListener("change", updateFromSlider);
}

let debounceTimer;
let activeSuggestionIndex = -1;
let currentSuggestions = [];

/**
 * Setup search and autocomplete bindings for the premium search component
 */
function setupAutocomplete() {
    const input = elements.symbolSearchInput;
    const container = elements.searchSuggestions;

    if (!input || !container) return;

    // Trigger search on input focus
    input.addEventListener("focus", () => {
        fetchSuggestions(input.value);
    });

    // Handle typing with debouncing (200ms)
    input.addEventListener("input", (e) => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            fetchSuggestions(e.target.value);
        }, 200);
    });

    // Handle keyboard navigation
    input.addEventListener("keydown", (e) => {
        const items = container.querySelectorAll(".suggestion-item");

        if (e.key === "ArrowDown") {
            if (!items.length) return;
            e.preventDefault();
            activeSuggestionIndex = (activeSuggestionIndex + 1) % items.length;
            highlightSuggestion(items);
        } else if (e.key === "ArrowUp") {
            if (!items.length) return;
            e.preventDefault();
            activeSuggestionIndex = (activeSuggestionIndex - 1 + items.length) % items.length;
            highlightSuggestion(items);
        } else if (e.key === "Enter") {
            e.preventDefault();
            if (activeSuggestionIndex >= 0 && activeSuggestionIndex < items.length) {
                selectSuggestion(currentSuggestions[activeSuggestionIndex]);
            } else {
                const typedVal = input.value.trim().toUpperCase();
                if (typedVal) {
                    closeSuggestions();
                    fetchTickerData(typedVal);
                }
            }
        } else if (e.key === "Escape") {
            closeSuggestions();
        }
    });

    // Close suggestions dropdown when clicking outside
    document.addEventListener("click", (e) => {
        if (!input.contains(e.target) && !container.contains(e.target)) {
            closeSuggestions();
        }
    });
}

async function fetchSuggestions(query) {
    try {
        const res = await fetch(`/v1/symbols/search?q=${encodeURIComponent(query)}`);
        if (!res.ok) throw new Error("Search failed");
        const data = await res.json();
        currentSuggestions = data.results || [];
        renderSuggestions(currentSuggestions);
    } catch (err) {
        console.error("Autocomplete search error: ", err);
    }
}

// Security Utility
function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function renderSuggestions(suggestions) {
    const container = elements.searchSuggestions;
    if (!container) return;
    
    container.innerHTML = "";
    activeSuggestionIndex = -1;

    if (suggestions.length === 0) {
        container.classList.add("hidden");
        return;
    }

    suggestions.forEach((item, index) => {
        const div = document.createElement("div");
        div.className = "suggestion-item";
        div.innerHTML = `
            <div class="suggestion-left">
                <span class="suggestion-symbol">${escapeHtml(item.symbol)}</span>
                <span class="suggestion-name">${escapeHtml(item.name)}</span>
            </div>
            <span class="suggestion-type">${escapeHtml(item.type)}</span>
        `;
        
        div.addEventListener("click", () => {
            selectSuggestion(item);
        });

        container.appendChild(div);
    });

    container.classList.remove("hidden");
}

function highlightSuggestion(items) {
    items.forEach((item, idx) => {
        if (idx === activeSuggestionIndex) {
            item.classList.add("active");
            item.scrollIntoView({ block: "nearest" });
        } else {
            item.classList.remove("active");
        }
    });
}

function selectSuggestion(item) {
    elements.symbolSearchInput.value = item.symbol;
    closeSuggestions();
    fetchTickerData(item.symbol);
}

function closeSuggestions() {
    if (elements.searchSuggestions) {
        elements.searchSuggestions.classList.add("hidden");
    }
    activeSuggestionIndex = -1;
}


/**
 * Monotonically update underlying price timestamp
 */
function updateUnderlyingTime(timestampStr) {
    if (!timestampStr) return false;
    const incomingTime = new Date(timestampStr);
    if (appState.lastPriceUpdated && incomingTime <= appState.lastPriceUpdated) {
        console.log("Skipping out-of-order or stale update:", timestampStr);
        return false;
    }
    appState.lastPriceUpdated = incomingTime;
    if (elements.underlyingTimeElapsed) {
        elements.underlyingTimeElapsed.textContent = "(updated live)";
    }
    return true;
}

/**
 * Query live Redis or dynamic analytics parameters for selected instrument
 */
async function fetchTickerData(symbol) {
    try {
        // Show loading state in the table
        elements.tableBody.innerHTML = `<tr><td colspan="19" style="text-align: center; padding: 40px; font-size: 14px; font-weight: 700; color: #1a237e; background-color: rgba(26, 35, 126, 0.04);">Loading option chain for ${symbol}...</td></tr>`;
        
        const res = await fetch(`/v1/pricer/ticker/${symbol}`);
        if (!res.ok) throw new Error(`Ticker query failed for ${symbol}`);
        
        const data = await res.json();
        
        // Load data properties into state
        appState.symbol = data.symbol;
        appState.marketSpot = data.stock_price;
        appState.optionChains = data.option_chains || {};
        appState.expiryDates = data.expiry_dates || [];
        
        // Reset full chain show
        appState.showFullChain = false;
        const fullChainBtn = elements.toggleFullChainBtn || document.getElementById("toggle-full-chain-btn");
        if (fullChainBtn) {
            fullChainBtn.classList.remove("active");
            fullChainBtn.textContent = "Show Full Chain";
        }
        
        // Reset simulation states
        appState.applySimulation = false;
        const applyToggle = elements.applySimulationToggle || document.getElementById("apply-simulation-toggle");
        if (applyToggle) {
            applyToggle.checked = false;
        }

        // Bind live/market metrics
        appState.marketVol = data.implied_volatility > 0 ? data.implied_volatility : (data.historical_volatility > 0 ? data.historical_volatility : 25.0);
        appState.marketDays = data.expiry_days > 0 ? data.expiry_days : 30;
        appState.marketRate = data.risk_free_rate || (appState.symbol === "AAPL" || appState.symbol === "TSLA" ? 5.25 : 6.50);
        appState.marketYield = data.dividend_yield || 0.0;
        
        // Bind dynamic model values
        appState.volatility = appState.marketVol;
        appState.daysToExpiry = appState.marketDays;
        appState.riskFreeRate = appState.marketRate;
        appState.dividendYield = appState.marketYield;
        appState.spot = appState.marketSpot;
        
        // Select nearest expiry date by default
        if (appState.expiryDates.length > 0) {
            appState.selectedExpiry = appState.expiryDates[0];
        } else {
            appState.selectedExpiry = "";
        }
        
        // Compute initial days to expiry from selectedExpiry
        let initialDays = data.expiry_days > 0 ? data.expiry_days : 30;
        if (appState.selectedExpiry) {
            try {
                const today = new Date();
                today.setHours(0,0,0,0);
                const exp = new Date(appState.selectedExpiry + 'T00:00:00');
                exp.setHours(0,0,0,0);
                initialDays = Math.max(Math.round((exp - today) / (1000 * 60 * 60 * 24)), 1);
            } catch (e) {
                initialDays = data.expiry_days > 0 ? data.expiry_days : 30;
            }
        }
        appState.daysToExpiry = initialDays;
        
        // Sync custom expiry UI and badge
        syncCustomExpiryUI(initialDays, appState.selectedExpiry);
        
        // Populate inputs in UI
        elements.underlyingSymbol.textContent = appState.symbol;
        elements.underlyingPrice.textContent = formatNumber(appState.marketSpot, 2);
        
        const spotMin = Math.round(appState.marketSpot * 0.7 * 100) / 100;
        const spotMax = Math.round(appState.marketSpot * 1.3 * 100) / 100;
        
        elements.bsmSpot.value = appState.spot;
        elements.bsmSpotSlider.min = spotMin;
        elements.bsmSpotSlider.max = spotMax;
        elements.bsmSpotSlider.step = Math.round((spotMax - spotMin) / 200 * 100) / 100 || 0.05;
        elements.bsmSpotSlider.value = appState.spot;
        
        elements.spotMinLbl.textContent = formatNumber(spotMin, 2);
        elements.spotMaxLbl.textContent = formatNumber(spotMax, 2);
        
        elements.bsmVol.value = appState.volatility;
        elements.bsmVolSlider.value = appState.volatility;
        
        elements.bsmDays.value = appState.daysToExpiry;
        elements.bsmDaysSlider.value = appState.daysToExpiry;
        
        elements.bsmRate.value = appState.riskFreeRate;
        elements.bsmRateSlider.value = appState.riskFreeRate;
        
        elements.bsmDiv.value = appState.dividendYield;
        elements.bsmDivSlider.value = appState.dividendYield;
        
        // Update Expiry Date and Strike Price filters dropdowns
        populateDropdowns();
        
        // Recalculate and render Option Chain table grid
        recalculateAndRender();
        
        // Also fetch and render technicals for current symbol
        fetchAndRenderTechnicals(appState.symbol);
        
        // Setup/Switch WebSocket for real-time updates
        if (!currentSocket || appState.symbol !== activeSocketSymbol) {
            setupWebSocket(appState.symbol);
        }
    } catch (e) {

        console.error("Error fetching options parameters: ", e);
        elements.tableBody.innerHTML = `<tr><td colspan="19" style="text-align: center; padding: 40px; font-size: 14px; font-weight: 700; color: #dc2626; background-color: rgba(220, 38, 38, 0.04);">Error: Failed to fetch option chain for "${symbol}". Instrument may not exist or has no derivatives data.</td></tr>`;
    }
}

/**
 * Setup WebSocket connection for real-time updates
 */
function setupWebSocket(symbol) {
    if (currentSocket) {
        try {
            currentSocket.close(1000, "Switching symbol");
        } catch (e) {
            console.error("Error closing existing socket:", e);
        }
        currentSocket = null;
    }
    
    const loc = window.location;
    const wsProtocol = loc.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProtocol}//${loc.host}/v1/ws/${symbol}`;
    
    console.log(`Connecting WebSocket for ${symbol} to: ${wsUrl}`);
    const socket = new WebSocket(wsUrl);
    currentSocket = socket;
    activeSocketSymbol = symbol;
    
    socket.onopen = () => {
        console.log(`WebSocket connected for symbol: ${symbol}`);
    };
    
    socket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === "price") {
                console.log(`Real-time price update received for ${symbol}:`, msg.data);
                const priceData = msg.data;
                if (priceData && priceData.last_price) {
                    const updateTimeStr = priceData.last_updated || new Date().toISOString();
                    if (!updateUnderlyingTime(updateTimeStr)) {
                        return;
                    }
                    const newPrice = priceData.last_price;
                    appState.marketSpot = newPrice;
                    elements.underlyingPrice.textContent = formatNumber(newPrice, 2);
                    
                    const spotMin = Math.round(appState.marketSpot * 0.7 * 100) / 100;
                    const spotMax = Math.round(appState.marketSpot * 1.3 * 100) / 100;
                    
                    elements.bsmSpotSlider.min = spotMin;
                    elements.bsmSpotSlider.max = spotMax;
                    elements.bsmSpotSlider.step = Math.round((spotMax - spotMin) / 200 * 100) / 100 || 0.05;
                    elements.spotMinLbl.textContent = formatNumber(spotMin, 2);
                    elements.spotMaxLbl.textContent = formatNumber(spotMax, 2);
                    
                    if (!appState.applySimulation) {
                        appState.spot = newPrice;
                        elements.bsmSpot.value = appState.spot;
                        elements.bsmSpotSlider.value = appState.spot;
                    }
                    
                    recalculateAndRender();
                    updateGreeksModalIfOpen();

                    if (document.getElementById("tab-technicals")?.classList.contains("active")) {
                        fetchAndRenderTechnicals(symbol);
                    }
                }
            } else if (msg.type === "options") {
                console.log(`Real-time options update received for ${symbol}`);
                fetchTickerDataBackground(symbol);
            } else if (msg.type === "ALERT_NOTIFICATION" || msg.type === "alert") {
                console.log(`Real-time alert notification received for ${symbol}:`, msg);
                showAlertToast(msg.message || `${msg.symbol} alert triggered: ${msg.triggered_value}`);
            }
        } catch (err) {
            console.error("Error parsing WebSocket message:", err);
        }
    };
    
    socket.onclose = (event) => {
        console.log(`WebSocket closed for symbol: ${symbol}. Code: ${event.code}`);
        if (currentSocket === socket) {
            currentSocket = null;
            activeSocketSymbol = null;
            
            if (event.code !== 1000 && appState.symbol === symbol) {
                console.log(`Attempting reconnection in 5s...`);
                setTimeout(() => {
                    if (appState.symbol === symbol) {
                        setupWebSocket(symbol);
                    }
                }, 5000);
            }
        }
    };
    
    socket.onerror = (err) => {
        console.error("WebSocket error:", err);
    };
}

/**
 * Silently fetch ticker data in the background and update UI
 */
async function fetchTickerDataBackground(symbol) {
    try {
        const res = await fetch(`/v1/pricer/ticker/${symbol}`);
        if (!res.ok) throw new Error(`Background ticker query failed for ${symbol}`);
        
        const data = await res.json();
        
        if (data.symbol !== appState.symbol) return;
        
        const updateTimeStr = data.generated_at || new Date().toISOString();
        if (!updateUnderlyingTime(updateTimeStr)) {
            return;
        }
        
        appState.marketSpot = data.stock_price;
        appState.marketVol = data.implied_volatility > 0 ? data.implied_volatility : (data.historical_volatility > 0 ? data.historical_volatility : 25.0);
        appState.marketDays = data.expiry_days > 0 ? data.expiry_days : 30;
        appState.marketRate = data.risk_free_rate || (appState.symbol === "AAPL" || appState.symbol === "TSLA" ? 5.25 : 6.50);
        appState.marketYield = data.dividend_yield || 0.0;
        
        appState.optionChains = data.option_chains || {};
        
        elements.underlyingPrice.textContent = formatNumber(appState.marketSpot, 2);
        
        const spotMin = Math.round(appState.marketSpot * 0.7 * 100) / 100;
        const spotMax = Math.round(appState.marketSpot * 1.3 * 100) / 100;
        
        elements.bsmSpotSlider.min = spotMin;
        elements.bsmSpotSlider.max = spotMax;
        elements.bsmSpotSlider.step = Math.round((spotMax - spotMin) / 200 * 100) / 100 || 0.05;
        elements.spotMinLbl.textContent = formatNumber(spotMin, 2);
        elements.spotMaxLbl.textContent = formatNumber(spotMax, 2);
        
        if (!appState.applySimulation) {
            appState.spot = data.stock_price;
            appState.volatility = appState.marketVol;
            appState.daysToExpiry = appState.marketDays;
            appState.riskFreeRate = appState.marketRate;
            appState.dividendYield = appState.marketYield;
            
            elements.bsmSpot.value = appState.spot;
            elements.bsmSpotSlider.value = appState.spot;
            elements.bsmVol.value = appState.volatility;
            elements.bsmVolSlider.value = appState.volatility;
            elements.bsmDays.value = appState.daysToExpiry;
            elements.bsmDaysSlider.value = appState.daysToExpiry;
            elements.bsmRate.value = appState.riskFreeRate;
            elements.bsmRateSlider.value = appState.riskFreeRate;
            elements.bsmDiv.value = appState.dividendYield;
            elements.bsmDivSlider.value = appState.dividendYield;
        }
        
        recalculateAndRender();
        updateGreeksModalIfOpen();

        if (document.getElementById("tab-technicals")?.classList.contains("active")) {
            fetchAndRenderTechnicals(symbol);
        }
    } catch (e) {
        console.error("Error in background options update:", e);
    }
}

/**
 * Refresh Greeks details modal if open
 */
function updateGreeksModalIfOpen() {
    if (activeInspectedStrike !== null && elements.greeksModal.classList.contains("show")) {
        openStrikeModal(activeInspectedStrike);
    }
}

/**
 * Re-populate Strike select dropdown options dynamically
 */
/**
 * Populate Expiry date dropdown options dynamically
 */
function populateDropdowns() {
    // 1. Expiry Dates Select
    elements.expirySelect.innerHTML = "";
    if (appState.expiryDates.length === 0) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "No Expiry";
        elements.expirySelect.appendChild(opt);
    } else {
        appState.expiryDates.forEach(dateStr => {
            const opt = document.createElement("option");
            opt.value = dateStr;
            
            // Format date beautifully (e.g. 04-Jun-2026)
            try {
                const dt = new Date(dateStr + 'T00:00:00');
                const day = String(dt.getDate()).padStart(2, '0');
                const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
                const monthStr = months[dt.getMonth()];
                const year = dt.getFullYear();
                opt.textContent = `${day}-${monthStr}-${year}`;
            } catch (e) {
                opt.textContent = dateStr;
            }
            
            if (dateStr === appState.selectedExpiry) {
                opt.selected = true;
            }
            elements.expirySelect.appendChild(opt);
        });
    }
}

let isFirstLoad = true;

/**
 * Dynamically adjust table headers based on current layout mode
 */
function updateTableHeaders() {
    const tableEl = document.getElementById("option-chain-table");
    if (!tableEl) return;
    
    let theadHtml = "";
    const layout = appState.layoutMode || "standard";
    
    if (layout === "standard") {
        theadHtml = `
            <tr class="super-header">
                <th colspan="9" class="calls-super">CALLS</th>
                <th class="strike-super">STRIKE</th>
                <th colspan="9" class="puts-super">PUTS</th>
            </tr>
            <tr class="sub-header">
                <th title="Chart Link"></th>
                <th title="Volume">VOLUME</th>
                <th title="Implied Volatility">IV</th>
                <th title="BSM Theoretical Price" class="bs-col">BS PRICE</th>
                <th title="Last Traded Price">LTP</th>
                <th title="Bid Quantity">BID QTY</th>
                <th title="Bid Price">BID</th>
                <th title="Ask Price">ASK</th>
                <th title="Ask Quantity">ASK QTY</th>
                <th title="Strike Price" class="strike-col">STRIKE</th>
                <th title="Bid Quantity">BID QTY</th>
                <th title="Bid Price">BID</th>
                <th title="Ask Price">ASK</th>
                <th title="Ask Quantity">ASK QTY</th>
                <th title="Last Traded Price">LTP</th>
                <th title="BSM Theoretical Price" class="bs-col">BS PRICE</th>
                <th title="Implied Volatility">IV</th>
                <th title="Volume">VOLUME</th>
                <th title="Chart Link"></th>
            </tr>
        `;
    } else if (layout === "calls") {
        theadHtml = `
            <tr class="super-header">
                <th colspan="9" class="calls-super">CALL OPTIONS ONLY</th>
                <th class="strike-super">STRIKE</th>
            </tr>
            <tr class="sub-header">
                <th title="Chart Link"></th>
                <th title="Volume">VOLUME</th>
                <th title="Implied Volatility">IV</th>
                <th title="BSM Theoretical Price" class="bs-col">BS PRICE</th>
                <th title="Last Traded Price">LTP</th>
                <th title="Bid Quantity">BID QTY</th>
                <th title="Bid Price">BID</th>
                <th title="Ask Price">ASK</th>
                <th title="Ask Quantity">ASK QTY</th>
                <th title="Strike Price" class="strike-col">STRIKE</th>
            </tr>
        `;
    } else if (layout === "puts") {
        theadHtml = `
            <tr class="super-header">
                <th class="strike-super">STRIKE</th>
                <th colspan="9" class="puts-super">PUT OPTIONS ONLY</th>
            </tr>
            <tr class="sub-header">
                <th title="Strike Price" class="strike-col">STRIKE</th>
                <th title="Bid Quantity">BID QTY</th>
                <th title="Bid Price">BID</th>
                <th title="Ask Price">ASK</th>
                <th title="Ask Quantity">ASK QTY</th>
                <th title="Last Traded Price">LTP</th>
                <th title="BSM Theoretical Price" class="bs-col">BS PRICE</th>
                <th title="Implied Volatility">IV</th>
                <th title="Volume">VOLUME</th>
                <th title="Chart Link"></th>
            </tr>
        `;
    } else if (layout === "greeks") {
        theadHtml = `
            <tr class="super-header">
                <th colspan="6" class="calls-super">CALL GREEKS</th>
                <th class="strike-super">STRIKE</th>
                <th colspan="6" class="puts-super">PUT GREEKS</th>
            </tr>
            <tr class="sub-header">
                <th title="Delta">DELTA</th>
                <th title="Gamma">GAMMA</th>
                <th title="Vega">VEGA</th>
                <th title="Theta">THETA</th>
                <th title="Last Traded Price">LTP</th>
                <th title="Implied Volatility">IV</th>
                <th title="Strike Price" class="strike-col">STRIKE</th>
                <th title="Implied Volatility">IV</th>
                <th title="Last Traded Price">LTP</th>
                <th title="Delta">DELTA</th>
                <th title="Gamma">GAMMA</th>
                <th title="Vega">VEGA</th>
                <th title="Theta">THETA</th>
            </tr>
        `;
    }
    
    let thead = tableEl.querySelector("thead");
    if (!thead) {
        thead = document.createElement("thead");
        tableEl.insertBefore(thead, tableEl.firstChild);
    }
    thead.innerHTML = theadHtml;
}

/**
 * Locate ATM strike and calculate option chain values and dynamic layouts
 */
function recalculateAndRender() {
    updateTableHeaders();
    
    const chainRows = appState.optionChains[appState.selectedExpiry] || [];
    if (chainRows.length === 0) {
        const symbolText = appState.symbol ? appState.symbol : "selected instrument";
        const layout = appState.layoutMode || "standard";
        const colsCount = layout === "standard" ? 19 : (layout === "greeks" ? 13 : 10);
        elements.tableBody.innerHTML = `<tr><td colspan="${colsCount}" style="text-align: center; padding: 40px; font-size: 14px; font-weight: 700; color: var(--accent-orange); background-color: rgba(243, 112, 33, 0.04);">Option chain is not available for ${symbolText} in the Indian market.</td></tr>`;
        return;
    }

    // 1. Resolve active calculation parameters (live vs. simulated)
    let liveDays = appState.marketDays || 30;
    if (appState.selectedExpiry) {
        try {
            const today = new Date();
            today.setHours(0,0,0,0);
            const exp = new Date(appState.selectedExpiry);
            exp.setHours(0,0,0,0);
            liveDays = Math.max(Math.round((exp - today) / (1000 * 60 * 60 * 24)), 1);
        } catch (e) {
            liveDays = appState.marketDays || 30;
        }
    }

    const activeSpot = appState.applySimulation ? appState.spot : appState.marketSpot;
    const activeVol = appState.applySimulation ? appState.volatility : (appState.marketVol || 25.0);
    const activeDays = appState.applySimulation ? appState.daysToExpiry : liveDays;
    const activeRate = appState.applySimulation ? appState.riskFreeRate : (appState.marketRate || 6.50);
    const activeYield = appState.applySimulation ? appState.dividendYield : (appState.marketYield || 0.0);

    // 2. Locate ATM strike (closest to Active Spot Price)
    let minDiff = Infinity;
    let atmStrike = 0.0;
    chainRows.forEach(row => {
        const diff = Math.abs(row.strike_price - activeSpot);
        if (diff < minDiff) {
            minDiff = diff;
            atmStrike = row.strike_price;
        }
    });
    appState.atmStrike = atmStrike;
    elements.atmStrikeVal.textContent = formatNumber(atmStrike, 0);

    // 3. Compute ATM Analytics (for Modal & Controls) using modal/simulated values
    // Modal ALWAYS displays the inputs specified on the control sliders
    const atmMetrics = calculateBSM(
        appState.spot,
        atmStrike,
        appState.daysToExpiry,
        appState.riskFreeRate,
        appState.volatility,
        appState.dividendYield
    );

    // Bind metrics labels in control card
    elements.atmCallPrice.textContent = formatNumber(atmMetrics.call, 2);
    elements.atmCallDelta.textContent = formatNumber(atmMetrics.deltaCall, 4);
    elements.atmCallTheta.textContent = formatNumber(atmMetrics.thetaCall, 4);
    elements.atmCallRho.textContent = formatNumber(atmMetrics.rhoCall, 4);

    elements.atmGamma.textContent = formatNumber(atmMetrics.gamma, 6);
    elements.atmVega.textContent = formatNumber(atmMetrics.vega, 4);

    elements.atmPutPrice.textContent = formatNumber(atmMetrics.put, 2);
    elements.atmPutDelta.textContent = formatNumber(atmMetrics.deltaPut, 4);
    elements.atmPutTheta.textContent = formatNumber(atmMetrics.thetaPut, 4);
    elements.atmPutRho.textContent = formatNumber(atmMetrics.rhoPut, 4);

    // 4. Render Option Chain table body with batched DocumentFragment
    const fragment = document.createDocumentFragment();
    
    // Slice options table (Full chain vs. 20 strikes ATM +/-)
    let rowsToRender = chainRows;
    if (!appState.showFullChain) {
        // Show 20 rows above ATM, 20 rows below ATM (total 41)
        const atmIndex = chainRows.findIndex(r => r.strike_price === atmStrike);
        if (atmIndex !== -1) {
            const startIdx = Math.max(0, atmIndex - 20);
            const endIdx = Math.min(chainRows.length, atmIndex + 21);
            rowsToRender = chainRows.slice(startIdx, endIdx);
        }
    }

    // Calculate maximum volume for dynamic progress bars
    let maxVolume = 1;
    rowsToRender.forEach(row => {
        if (row.call?.volume && row.call.volume > maxVolume) maxVolume = row.call.volume;
        if (row.put?.volume && row.put.volume > maxVolume) maxVolume = row.put.volume;
    });

    rowsToRender.forEach(row => {
        const strike = row.strike_price;
        const isATM = strike === atmStrike;
        
        // Calculate BSM values for specific strike using the active parameters
        const callIv = row.call?.iv || activeVol;
        const putIv = row.put?.iv || activeVol;
        
        const callBS = calculateBSM(activeSpot, strike, activeDays, activeRate, callIv, activeYield);
        const putBS = calculateBSM(activeSpot, strike, activeDays, activeRate, putIv, activeYield);

        const tr = document.createElement("tr");
        tr.setAttribute("data-strike", strike);
        if (isATM) tr.className = "atm-strike-row";

        // Call ITM if strike < activeSpot, Put ITM if strike > activeSpot
        const callItmClass = strike < activeSpot ? "itm-call-shaded" : "";
        const putItmClass = strike > activeSpot ? "itm-put-shaded" : "";

        // Net Change style helpers
        const cChgClass = row.call?.chng < 0 ? "negative-val" : (row.call?.chng > 0 ? "positive-val" : "");
        const pChgClass = row.put?.chng < 0 ? "negative-val" : (row.put?.chng > 0 ? "positive-val" : "");

        // Color coding for BSM Prices based on comparison with LTP (market price)
        let callBsClass = "";
        let callBsTitle = "BSM Theoretical Price";
        if (row.call?.ltp && callBS.call) {
            const edge = callBS.call - row.call.ltp;
            if (edge > 0.05) {
                callBsClass = "bs-underpriced";
                callBsTitle = `BSM Price (${formatNumber(callBS.call, 2)}) > LTP (${formatNumber(row.call.ltp, 2)}) - Option is underpriced (Theoretical Edge: +${formatNumber(edge, 2)})`;
            } else if (edge < -0.05) {
                callBsClass = "bs-overpriced";
                callBsTitle = `BSM Price (${formatNumber(callBS.call, 2)}) < LTP (${formatNumber(row.call.ltp, 2)}) - Option is overpriced (Theoretical Edge: ${formatNumber(edge, 2)})`;
            }
        }

        let putBsClass = "";
        let putBsTitle = "BSM Theoretical Price";
        if (row.put?.ltp && putBS.put) {
            const edge = putBS.put - row.put.ltp;
            if (edge > 0.05) {
                putBsClass = "bs-underpriced";
                putBsTitle = `BSM Price (${formatNumber(putBS.put, 2)}) > LTP (${formatNumber(row.put.ltp, 2)}) - Option is underpriced (Theoretical Edge: +${formatNumber(edge, 2)})`;
            } else if (edge < -0.05) {
                putBsClass = "bs-overpriced";
                putBsTitle = `BSM Price (${formatNumber(putBS.put, 2)}) < LTP (${formatNumber(row.put.ltp, 2)}) - Option is overpriced (Theoretical Edge: ${formatNumber(edge, 2)})`;
            }
        }

        // Inline Progress Bar HTML generators
        const callVolPct = row.call?.volume ? (row.call.volume / maxVolume) * 100 : 0;
        const putVolPct = row.put?.volume ? (row.put.volume / maxVolume) * 100 : 0;
        const volumeBgCall = row.call?.volume ? `<div class="ast-bar-bg ast-bar-left" style="width: ${callVolPct}%"></div>` : "";
        const volumeBgPut = row.put?.volume ? `<div class="ast-bar-bg ast-bar-right" style="width: ${putVolPct}%"></div>` : "";

        // Build inner HTML based on Layout Mode
        const layout = appState.layoutMode || "standard";
        let rowHtml = "";

        if (layout === "standard") {
            rowHtml = `
                <!-- CALLS -->
                <td class="chart-cell">
                    <button class="chart-icon-btn" title="View Chart" onclick="openStrikeModal(${strike})">
                        <svg viewBox="0 0 24 24" width="12" height="12">
                            <path d="M5 9.2h3V19H5zM10.5 5h3v14h-3zm5.5 8h3v6h-3z"/>
                        </svg>
                    </button>
                </td>
                <td class="${callItmClass} ast-bar-cell">
                    <div class="ast-bar-container ast-right-align">
                        ${volumeBgCall}
                        <span class="ast-bar-value">${formatNumber(row.call?.volume, 0, "-")}</span>
                    </div>
                </td>
                <td class="${callItmClass}">${formatNumber(row.call?.iv, 2, "-")}</td>
                <td class="${callItmClass} bs-field ${callBsClass}" title="${callBsTitle}">${formatNumber(callBS.call, 2)}</td>
                <td class="${callItmClass} link-blue" onclick="openStrikeModal(${strike})">${formatNumber(row.call?.ltp, 2, "-")}</td>
                <td class="${callItmClass}">${formatNumber(row.call?.bid_qty, 0, "-")}</td>
                <td class="${callItmClass}">${formatNumber(row.call?.bid, 2, "-")}</td>
                <td class="${callItmClass}">${formatNumber(row.call?.ask, 2, "-")}</td>
                <td class="${callItmClass}">${formatNumber(row.call?.ask_qty, 0, "-")}</td>
                
                <!-- CENTER STRIKE -->
                <td class="strike-cell" onclick="openStrikeModal(${strike})">${formatNumber(strike, 2)}</td>
                
                <!-- PUTS -->
                <td class="${putItmClass}">${formatNumber(row.put?.bid_qty, 0, "-")}</td>
                <td class="${putItmClass}">${formatNumber(row.put?.bid, 2, "-")}</td>
                <td class="${putItmClass}">${formatNumber(row.put?.ask, 2, "-")}</td>
                <td class="${putItmClass}">${formatNumber(row.put?.ask_qty, 0, "-")}</td>
                <td class="${putItmClass} link-blue" onclick="openStrikeModal(${strike})">${formatNumber(row.put?.ltp, 2, "-")}</td>
                <td class="${putItmClass} bs-field ${putBsClass}" title="${putBsTitle}">${formatNumber(putBS.put, 2)}</td>
                <td class="${putItmClass}">${formatNumber(row.put?.iv, 2, "-")}</td>
                <td class="${putItmClass} ast-bar-cell">
                    <div class="ast-bar-container ast-right-align">
                        ${volumeBgPut}
                        <span class="ast-bar-value">${formatNumber(row.put?.volume, 0, "-")}</span>
                    </div>
                </td>
                <td class="chart-cell">
                    <button class="chart-icon-btn" title="View Chart" onclick="openStrikeModal(${strike})">
                        <svg viewBox="0 0 24 24" width="12" height="12">
                            <path d="M5 9.2h3V19H5zM10.5 5h3v14h-3zm5.5 8h3v6h-3z"/>
                        </svg>
                    </button>
                </td>
            `;
        } else if (layout === "calls") {
            rowHtml = `
                <!-- CALLS ONLY -->
                <td class="chart-cell">
                    <button class="chart-icon-btn" title="View Chart" onclick="openStrikeModal(${strike})">
                        <svg viewBox="0 0 24 24" width="12" height="12">
                            <path d="M5 9.2h3V19H5zM10.5 5h3v14h-3zm5.5 8h3v6h-3z"/>
                        </svg>
                    </button>
                </td>
                <td class="${callItmClass} ast-bar-cell">
                    <div class="ast-bar-container ast-right-align">
                        ${volumeBgCall}
                        <span class="ast-bar-value">${formatNumber(row.call?.volume, 0, "-")}</span>
                    </div>
                </td>
                <td class="${callItmClass}">${formatNumber(row.call?.iv, 2, "-")}</td>
                <td class="${callItmClass} bs-field ${callBsClass}" title="${callBsTitle}">${formatNumber(callBS.call, 2)}</td>
                <td class="${callItmClass} link-blue" onclick="openStrikeModal(${strike})">${formatNumber(row.call?.ltp, 2, "-")}</td>
                <td class="${callItmClass}">${formatNumber(row.call?.bid_qty, 0, "-")}</td>
                <td class="${callItmClass}">${formatNumber(row.call?.bid, 2, "-")}</td>
                <td class="${callItmClass}">${formatNumber(row.call?.ask, 2, "-")}</td>
                <td class="${callItmClass}">${formatNumber(row.call?.ask_qty, 0, "-")}</td>
                
                <!-- STRIKE -->
                <td class="strike-cell" onclick="openStrikeModal(${strike})">${formatNumber(strike, 2)}</td>
            `;
        } else if (layout === "puts") {
            rowHtml = `
                <!-- STRIKE -->
                <td class="strike-cell" onclick="openStrikeModal(${strike})">${formatNumber(strike, 2)}</td>
                
                <!-- PUTS ONLY -->
                <td class="${putItmClass}">${formatNumber(row.put?.bid_qty, 0, "-")}</td>
                <td class="${putItmClass}">${formatNumber(row.put?.bid, 2, "-")}</td>
                <td class="${putItmClass}">${formatNumber(row.put?.ask, 2, "-")}</td>
                <td class="${putItmClass}">${formatNumber(row.put?.ask_qty, 0, "-")}</td>
                <td class="${putItmClass} link-blue" onclick="openStrikeModal(${strike})">${formatNumber(row.put?.ltp, 2, "-")}</td>
                <td class="${putItmClass} bs-field ${putBsClass}" title="${putBsTitle}">${formatNumber(putBS.put, 2)}</td>
                <td class="${putItmClass}">${formatNumber(row.put?.iv, 2, "-")}</td>
                <td class="${putItmClass} ast-bar-cell">
                    <div class="ast-bar-container ast-right-align">
                        ${volumeBgPut}
                        <span class="ast-bar-value">${formatNumber(row.put?.volume, 0, "-")}</span>
                    </div>
                </td>
                <td class="chart-cell">
                    <button class="chart-icon-btn" title="View Chart" onclick="openStrikeModal(${strike})">
                        <svg viewBox="0 0 24 24" width="12" height="12">
                            <path d="M5 9.2h3V19H5zM10.5 5h3v14h-3zm5.5 8h3v6h-3z"/>
                        </svg>
                    </button>
                </td>
            `;
        } else if (layout === "greeks") {
            rowHtml = `
                <!-- CALL GREEKS -->
                <td class="${callItmClass}">${formatNumber(callBS.deltaCall, 4, "-")}</td>
                <td class="${callItmClass}">${formatNumber(callBS.gamma, 4, "-")}</td>
                <td class="${callItmClass}">${formatNumber(callBS.vega, 4, "-")}</td>
                <td class="${callItmClass}">${formatNumber(callBS.thetaCall, 4, "-")}</td>
                <td class="${callItmClass} link-blue" onclick="openStrikeModal(${strike})">${formatNumber(row.call?.ltp, 2, "-")}</td>
                <td class="${callItmClass}">${formatNumber(row.call?.iv, 2, "-")}</td>
                
                <!-- CENTER STRIKE -->
                <td class="strike-cell" onclick="openStrikeModal(${strike})">${formatNumber(strike, 2)}</td>
                
                <!-- PUT GREEKS -->
                <td class="${putItmClass}">${formatNumber(row.put?.iv, 2, "-")}</td>
                <td class="${putItmClass} link-blue" onclick="openStrikeModal(${strike})">${formatNumber(row.put?.ltp, 2, "-")}</td>
                <td class="${putItmClass}">${formatNumber(putBS.deltaPut, 4, "-")}</td>
                <td class="${putItmClass}">${formatNumber(putBS.gamma, 4, "-")}</td>
                <td class="${putItmClass}">${formatNumber(putBS.vega, 4, "-")}</td>
                <td class="${putItmClass}">${formatNumber(putBS.thetaPut, 4, "-")}</td>
            `;
        }

        tr.innerHTML = rowHtml;
        fragment.appendChild(tr);
    });

    elements.tableBody.replaceChildren(fragment);

    // Scroll to the ATM Strike row inside table for easy visual inspection
    if (appState.selectedStrike === "ALL" && isFirstLoad) {
        setTimeout(() => {
            const atmRow = document.querySelector(".atm-strike-row");
            if (atmRow) {
                atmRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        }, 100);
        isFirstLoad = false;
    }
}

/**
 * Open Greeks Details Modal loaded with specific strike's analytical parameters
 */
window.openStrikeModal = function(strikePrice) {
    activeInspectedStrike = strikePrice;
    const chainRows = appState.optionChains[appState.selectedExpiry] || [];
    const row = chainRows.find(r => Math.abs(r.strike_price - strikePrice) < 0.01);
    if (!row) return;

    let liveDays = appState.marketDays || 30;
    if (appState.selectedExpiry) {
        try {
            const today = new Date();
            today.setHours(0,0,0,0);
            const exp = new Date(appState.selectedExpiry);
            exp.setHours(0,0,0,0);
            liveDays = Math.max(Math.round((exp - today) / (1000 * 60 * 60 * 24)), 1);
        } catch (e) {
            liveDays = appState.marketDays || 30;
        }
    }

    const activeSpot = appState.applySimulation ? appState.spot : appState.marketSpot;
    const activeVol = appState.applySimulation ? appState.volatility : (appState.marketVol || 25.0);
    const activeDays = appState.applySimulation ? appState.daysToExpiry : liveDays;
    const activeRate = appState.applySimulation ? appState.riskFreeRate : (appState.marketRate || 6.50);
    const activeYield = appState.applySimulation ? appState.dividendYield : (appState.marketYield || 0.0);

    const callIv = row.call?.iv || activeVol;
    const putIv = row.put?.iv || activeVol;

    const callBS = calculateBSM(activeSpot, strikePrice, activeDays, activeRate, callIv, activeYield);
    const putBS = calculateBSM(activeSpot, strikePrice, activeDays, activeRate, putIv, activeYield);

    // Call and Put edge: Fair theoretical minus LTP
    const callEdge = row.call?.ltp ? callBS.call - row.call.ltp : null;
    const putEdge = row.put?.ltp ? putBS.put - row.put.ltp : null;

    // Format BSM edge label text with 0.05 threshold
    let callEdgeText = formatNumber(callEdge, 2);
    let callEdgeClass = "font-mono";
    if (callEdge !== null) {
        if (callEdge > 0.05) {
            callEdgeText += " (Underpriced)";
            callEdgeClass += " positive-val";
        } else if (callEdge < -0.05) {
            callEdgeText += " (Overpriced)";
            callEdgeClass += " negative-val";
        } else {
            callEdgeText += " (Fair)";
        }
    }

    let putEdgeText = formatNumber(putEdge, 2);
    let putEdgeClass = "font-mono";
    if (putEdge !== null) {
        if (putEdge > 0.05) {
            putEdgeText += " (Underpriced)";
            putEdgeClass += " positive-val";
        } else if (putEdge < -0.05) {
            putEdgeText += " (Overpriced)";
            putEdgeClass += " negative-val";
        } else {
            putEdgeText += " (Fair)";
        }
    }

    // Load values into modal HTML
    elements.modalStrikePrice.textContent = formatNumber(strikePrice, 2);

    elements.modalCLtp.textContent = formatNumber(row.call?.ltp, 2);
    elements.modalCBsVal.textContent = formatNumber(callBS.call, 2);
    elements.modalCEdge.textContent = callEdgeText;
    elements.modalCEdge.className = callEdgeClass;
    elements.modalCDelta.textContent = formatNumber(callBS.deltaCall, 4);
    elements.modalCGamma.textContent = formatNumber(callBS.gamma, 6);
    elements.modalCVega.textContent = formatNumber(callBS.vega, 4);
    elements.modalCTheta.textContent = formatNumber(callBS.thetaCall, 4);
    elements.modalCRho.textContent = formatNumber(callBS.rhoCall, 4);

    elements.modalPLtp.textContent = formatNumber(row.put?.ltp, 2);
    elements.modalPBsVal.textContent = formatNumber(putBS.put, 2);
    elements.modalPEdge.textContent = putEdgeText;
    elements.modalPEdge.className = putEdgeClass;
    elements.modalPDelta.textContent = formatNumber(putBS.deltaPut, 4);
    elements.modalPGamma.textContent = formatNumber(putBS.gamma, 6); // Gamma is same for Call and Put
    elements.modalPVega.textContent = formatNumber(putBS.vega, 4);   // Vega is same for Call and Put
    elements.modalPTheta.textContent = formatNumber(putBS.thetaPut, 4);
    elements.modalPRho.textContent = formatNumber(putBS.rhoPut, 4);

    elements.modalInSpot.textContent = formatNumber(activeSpot, 2);
    elements.modalInVol.textContent = formatNumber((callIv + putIv) / 2, 2) + "%";
    elements.modalInDays.textContent = activeDays;
    elements.modalInRate.textContent = formatNumber(activeRate, 2) + "%";
    elements.modalInDiv.textContent = formatNumber(activeYield, 2) + "%";
    
    elements.modalD1.textContent = formatNumber(callBS.d1, 4);
    elements.modalD2.textContent = formatNumber(callBS.d2, 4);
    elements.modalNd1.textContent = formatNumber(callBS.nd1, 4);
    elements.modalNd2.textContent = formatNumber(callBS.nd2, 4);

    // Load market and order book data into modal HTML
    elements.modalCOi.textContent = formatNumber(row.call?.oi, 0, "-");
    elements.modalCOiChg.textContent = formatNumber(row.call?.chng_in_oi, 0, "-");
    elements.modalCOiChg.className = "font-mono " + (row.call?.chng_in_oi < 0 ? "negative-val" : "");
    elements.modalCVolume.textContent = formatNumber(row.call?.volume, 0, "-");
    elements.modalCIv.textContent = formatNumber(row.call?.iv, 2, "-");
    elements.modalCChg.textContent = formatNumber(row.call?.chng, 2, "-");
    elements.modalCChg.className = "font-mono " + (row.call?.chng < 0 ? "negative-val" : row.call?.chng > 0 ? "positive-val" : "");
    elements.modalCBidPrice.textContent = formatNumber(row.call?.bid, 2, "-");
    elements.modalCBidQty.textContent = formatNumber(row.call?.bid_qty, 0, "-");
    elements.modalCAskPrice.textContent = formatNumber(row.call?.ask, 2, "-");
    elements.modalCAskQty.textContent = formatNumber(row.call?.ask_qty, 0, "-");

    elements.modalPOi.textContent = formatNumber(row.put?.oi, 0, "-");
    elements.modalPOiChg.textContent = formatNumber(row.put?.chng_in_oi, 0, "-");
    elements.modalPOiChg.className = "font-mono " + (row.put?.chng_in_oi < 0 ? "negative-val" : "");
    elements.modalPVolume.textContent = formatNumber(row.put?.volume, 0, "-");
    elements.modalPIv.textContent = formatNumber(row.put?.iv, 2, "-");
    elements.modalPChg.textContent = formatNumber(row.put?.chng, 2, "-");
    elements.modalPChg.className = "font-mono " + (row.put?.chng < 0 ? "negative-val" : row.put?.chng > 0 ? "positive-val" : "");
    elements.modalPBidPrice.textContent = formatNumber(row.put?.bid, 2, "-");
    elements.modalPBidQty.textContent = formatNumber(row.put?.bid_qty, 0, "-");
    elements.modalPAskPrice.textContent = formatNumber(row.put?.ask, 2, "-");
    elements.modalPAskQty.textContent = formatNumber(row.put?.ask_qty, 0, "-");

    elements.greeksModal.classList.add("show");
};

let _xlsxLoadingPromise = null;

function ensureXlsxLoaded() {
    if (typeof XLSX !== "undefined") return Promise.resolve();
    if (_xlsxLoadingPromise) return _xlsxLoadingPromise;

    _xlsxLoadingPromise = new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = "https://cdn.jsdelivr.net/npm/xlsx-js-style@1.2.0/dist/xlsx.bundle.js";
        script.onload = () => resolve();
        script.onerror = (e) => {
            _xlsxLoadingPromise = null;
            reject(new Error("Failed to load Excel export library from CDN"));
        };
        document.head.appendChild(script);
    });
    return _xlsxLoadingPromise;
}

/**
 * Format Option Chain visible elements and export to a clean local XLSX file
 */
async function downloadCSV() {
    const chainRows = appState.optionChains[appState.selectedExpiry] || [];
    if (chainRows.length === 0) {
        alert("No option chain data available to export.");
        return;
    }

    try {
        await ensureXlsxLoaded();
    } catch (err) {
        alert("Failed to load Excel library. Please check your network connection.");
        return;
    }

    const wb = XLSX.utils.book_new();

    // --- 1. Option Chain Sheet ---
    const chainAoA = [
        ["CALLS - VOLUME", "CALLS - IV", "CALLS - BSM PRICE", "CALLS - LTP", "CALLS - BID QTY", "CALLS - BID", "CALLS - ASK", "CALLS - ASK QTY", "STRIKE", "PUTS - BID QTY", "PUTS - BID", "PUTS - ASK", "PUTS - ASK QTY", "PUTS - LTP", "PUTS - BSM PRICE", "PUTS - IV", "PUTS - VOLUME"]
    ];

    chainRows.forEach(row => {
        const strike = row.strike_price;
        let liveDays = appState.marketDays || 30;
        if (appState.selectedExpiry) {
            try {
                const today = new Date();
                today.setHours(0,0,0,0);
                const exp = new Date(appState.selectedExpiry);
                exp.setHours(0,0,0,0);
                liveDays = Math.max(Math.round((exp - today) / (1000 * 60 * 60 * 24)), 1);
            } catch (e) {
                liveDays = appState.marketDays || 30;
            }
        }
        const activeSpot = appState.applySimulation ? appState.spot : appState.marketSpot;
        const activeVol = appState.applySimulation ? appState.volatility : (appState.marketVol || 25.0);
        const activeDays = appState.applySimulation ? appState.daysToExpiry : liveDays;
        const activeRate = appState.applySimulation ? appState.riskFreeRate : (appState.marketRate || 6.50);
        const activeYield = appState.applySimulation ? appState.dividendYield : (appState.marketYield || 0.0);

        const callIv = row.call?.iv || activeVol;
        const putIv = row.put?.iv || activeVol;
        const callBS = calculateBSM(activeSpot, strike, activeDays, activeRate, callIv, activeYield);
        const putBS = calculateBSM(activeSpot, strike, activeDays, activeRate, putIv, activeYield);

        chainAoA.push([
            row.call?.volume || 0,
            row.call?.iv || 0.0,
            parseFloat(callBS.call.toFixed(2)),
            row.call?.ltp || 0.0,
            row.call?.bid_qty || 0,
            row.call?.bid || 0.0,
            row.call?.ask || 0.0,
            row.call?.ask_qty || 0,
            strike,
            row.put?.bid_qty || 0,
            row.put?.bid || 0.0,
            row.put?.ask || 0.0,
            row.put?.ask_qty || 0,
            row.put?.ltp || 0.0,
            parseFloat(putBS.put.toFixed(2)),
            row.put?.iv || 0.0,
            row.put?.volume || 0
        ]);
    });
    
    const wsChain = XLSX.utils.aoa_to_sheet(chainAoA);

    // Compute ATM strike for highlighting
    let currentAtmStrikeRaw = appState.atmStrike;
    if (!currentAtmStrikeRaw && chainRows.length > 0) {
        const activeSpot = appState.applySimulation ? appState.spot : appState.marketSpot;
        currentAtmStrikeRaw = chainRows.reduce((prev, curr) => 
            Math.abs(curr.strike_price - activeSpot) < Math.abs(prev.strike_price - activeSpot) ? curr : prev
        ).strike_price;
    }
    const currentAtmStrike = parseFloat(currentAtmStrikeRaw);

    // Apply styling to Option Chain
    const range = XLSX.utils.decode_range(wsChain['!ref']);
    for (let R = range.s.r; R <= range.e.r; ++R) {
        const strikeCellRef = XLSX.utils.encode_cell({c: 8, r: R});
        const strikeValRaw = wsChain[strikeCellRef] ? wsChain[strikeCellRef].v : null;
        const strikeVal = strikeValRaw !== null ? parseFloat(strikeValRaw) : null;
        
        for (let C = range.s.c; C <= range.e.c; ++C) {
            const cellRef = XLSX.utils.encode_cell({c: C, r: R});
            if (!wsChain[cellRef]) continue;
            
            // Initialize basic style object without empty fill (which causes black background)
            wsChain[cellRef].s = { font: {} };
            
            if (R === 0) {
                // Header row (Light Grey/Blue)
                wsChain[cellRef].s.font.bold = true;
                wsChain[cellRef].s.fill = { fgColor: { rgb: "D9E1F2" } };
            } else {
                // Strike Column Highlighting
                if (C === 8) {
                    if (strikeVal === currentAtmStrike) {
                        // ATM Strike (Blue)
                        wsChain[cellRef].s.fill = { fgColor: { rgb: "4A86E8" } };
                        wsChain[cellRef].s.font.color = { rgb: "FFFFFF" };
                        wsChain[cellRef].s.font.bold = true;
                    } else {
                        // Regular Strike (Light Blue)
                        wsChain[cellRef].s.fill = { fgColor: { rgb: "C9DAF8" } };
                        wsChain[cellRef].s.font.bold = true;
                    }
                }
                
                // ITM Calls (Left side - Green)
                if (C < 8 && strikeVal <= currentAtmStrike) {
                    wsChain[cellRef].s.fill = { fgColor: { rgb: "D9EAD3" } }; 
                }
                // ITM Puts (Right side - Red)
                else if (C > 8 && strikeVal >= currentAtmStrike) {
                    wsChain[cellRef].s.fill = { fgColor: { rgb: "F4CCCC" } }; 
                }
            }
        }
    }

    XLSX.utils.book_append_sheet(wb, wsChain, "Option Chain");

    // --- 2. Export Summary Sheet (Metadata) ---
    const exportNow = new Date();
    const exportDate = exportNow.toLocaleDateString("en-IN", { day: "2-digit", month: "long", year: "numeric" });
    const exportTime = exportNow.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true });

    // Resolve active BSM parameters (same logic as chain rendering)
    let summaryLiveDays = appState.marketDays || 30;
    if (appState.selectedExpiry) {
        try {
            const td = new Date(); td.setHours(0,0,0,0);
            const ex = new Date(appState.selectedExpiry); ex.setHours(0,0,0,0);
            summaryLiveDays = Math.max(Math.round((ex - td) / (1000 * 60 * 60 * 24)), 1);
        } catch (e) { summaryLiveDays = appState.marketDays || 30; }
    }
    const simActive = !!appState.applySimulation;
    const sourceLabel = simActive ? "BSM Custom Simulation" : "Market Data (Live)";

    const sumSpot    = simActive ? appState.spot           : appState.marketSpot;
    const sumVol     = simActive ? appState.volatility     : (appState.marketVol || 25.0);
    const sumDays    = simActive ? appState.daysToExpiry    : summaryLiveDays;
    const sumRate    = simActive ? appState.riskFreeRate    : (appState.marketRate || 6.50);
    const sumYield   = simActive ? appState.dividendYield   : (appState.marketYield || 0.0);

    const summaryAoA = [
        ["Shani — Export Summary"],
        [],
        ["Export Date", exportDate],
        ["Export Time", exportTime],
        [],
        ["Symbol", appState.symbol || "N/A"],
        ["Expiry", appState.selectedExpiry || "N/A"],
        [],
        ["Parameter Source", sourceLabel],
        ["BSM Simulation Active?", simActive ? "YES" : "NO"],
        [],
        ["Parameter", "Value", "Source"],
        ["Spot Price",        sumSpot,                    simActive ? "Custom" : "Market"],
        ["Volatility (%)",    sumVol,                     simActive ? "Custom" : "Market"],
        ["Days to Expiry",    sumDays,                    simActive ? "Custom" : "Market"],
        ["Risk-Free Rate (%)", sumRate,                   simActive ? "Custom" : "Market"],
        ["Dividend Yield (%)", sumYield,                  simActive ? "Custom" : "Market"],
    ];

    // If simulation active, also show market reference values for comparison
    if (simActive) {
        summaryAoA.push([]);
        summaryAoA.push(["Market Reference Values (before override)"]);
        summaryAoA.push(["Market Spot",          appState.marketSpot]);
        summaryAoA.push(["Market Volatility",    appState.marketVol || "N/A"]);
        summaryAoA.push(["Market Days to Expiry", summaryLiveDays]);
        summaryAoA.push(["Market Risk-Free Rate", appState.marketRate || "N/A"]);
        summaryAoA.push(["Market Dividend Yield", appState.marketYield || "N/A"]);
    }

    const wsSummary = XLSX.utils.aoa_to_sheet(summaryAoA);

    // Style summary sheet
    if (wsSummary['!ref']) {
        const sumRange = XLSX.utils.decode_range(wsSummary['!ref']);
        for (let R = sumRange.s.r; R <= sumRange.e.r; ++R) {
            for (let C = sumRange.s.c; C <= sumRange.e.c; ++C) {
                const ref = XLSX.utils.encode_cell({c: C, r: R});
                if (!wsSummary[ref]) continue;
                wsSummary[ref].s = { font: {} };

                // Title row
                if (R === 0) {
                    wsSummary[ref].s.font.bold = true;
                    wsSummary[ref].s.font.sz = 14;
                    wsSummary[ref].s.fill = { fgColor: { rgb: "4A86E8" } };
                    wsSummary[ref].s.font.color = { rgb: "FFFFFF" };
                }
                // Parameter table header
                if (R === 11) {
                    wsSummary[ref].s.font.bold = true;
                    wsSummary[ref].s.fill = { fgColor: { rgb: "D9E1F2" } };
                }
                // "Parameter Source" row highlight
                if (R === 8) {
                    wsSummary[ref].s.font.bold = true;
                    if (simActive) {
                        wsSummary[ref].s.fill = { fgColor: { rgb: "FCE5CD" } }; // Orange tint for custom
                    } else {
                        wsSummary[ref].s.fill = { fgColor: { rgb: "D9EAD3" } }; // Green tint for market
                    }
                }
                // Source column color coding in param rows
                if (C === 2 && R >= 12 && R <= 16) {
                    const val = String(wsSummary[ref].v || "");
                    if (val === "Custom") {
                        wsSummary[ref].s.fill = { fgColor: { rgb: "FCE5CD" } };
                        wsSummary[ref].s.font.bold = true;
                    } else if (val === "Market") {
                        wsSummary[ref].s.fill = { fgColor: { rgb: "D9EAD3" } };
                        wsSummary[ref].s.font.bold = true;
                    }
                }
            }
        }
        // Set column widths
        wsSummary['!cols'] = [{ wch: 30 }, { wch: 25 }, { wch: 12 }];
    }

    XLSX.utils.book_append_sheet(wb, wsSummary, "Export Summary");

    // Reorder sheets: Export Summary first
    wb.SheetNames = ["Export Summary", ...wb.SheetNames.filter(n => n !== "Export Summary")];

    // --- 3. Technicals Sheet ---
    const techAoA = [];
    if (appState.technicals) {
        const t = appState.technicals;
        techAoA.push(["Technical Indicator", "Value", "Signal"]);
        
        if (t.summary) {
            techAoA.push(["Overall Signal", `${t.summary.bullish_count} Buy | ${t.summary.neutral_count} Neutral | ${t.summary.bearish_count} Sell`, t.summary.overall_signal]);
            techAoA.push([]); // blank row
        }
        
        if (t.rsi) techAoA.push(["RSI", t.rsi.value, t.rsi.signal || t.rsi.label || ""]);
        if (t.macd) techAoA.push(["MACD", `${t.macd.macd} (Hist: ${t.macd.histogram})`, t.macd.signal || t.macd.label || ""]);
        if (t.bollinger) techAoA.push(["Bollinger Bands", `Upper: ${t.bollinger.upper} | Lower: ${t.bollinger.lower}`, t.bollinger.signal || t.bollinger.label || ""]);
        if (t.atr) techAoA.push(["ATR", t.atr, ""]);
        
        techAoA.push([]); // blank row
        if (t.moving_averages) {
            techAoA.push(["Moving Averages", "", ""]);
            t.moving_averages.forEach(ma => {
                techAoA.push([ma.name, ma.value, ma.signal]);
            });
        }
        
        techAoA.push([]); // blank row
        if (t.pivots) {
            techAoA.push(["Pivot Points", "", ""]);
            techAoA.push(["R3", t.pivots.r3, ""]);
            techAoA.push(["R2", t.pivots.r2, ""]);
            techAoA.push(["R1", t.pivots.r1, ""]);
            techAoA.push(["Pivot", t.pivots.p, ""]);
            techAoA.push(["S1", t.pivots.s1, ""]);
            techAoA.push(["S2", t.pivots.s2, ""]);
            techAoA.push(["S3", t.pivots.s3, ""]);
        }
    } else {
        techAoA.push(["Technicals Data Not Available", ""]);
    }
    
    const wsTech = XLSX.utils.aoa_to_sheet(techAoA);

    // Apply styling to Technicals Sheet
    if (wsTech['!ref']) {
        const techRange = XLSX.utils.decode_range(wsTech['!ref']);
        for (let R = techRange.s.r; R <= techRange.e.r; ++R) {
            
            // Check if this is a subheader row (Value column is empty string)
            const valCellRef = XLSX.utils.encode_cell({c: 1, r: R});
            const isSubheader = wsTech[valCellRef] && wsTech[valCellRef].v === "" && R > 0;
            
            for (let C = techRange.s.c; C <= techRange.e.c; ++C) {
                const cellRef = XLSX.utils.encode_cell({c: C, r: R});
                if (!wsTech[cellRef]) continue;
                
                wsTech[cellRef].s = { font: {} };
                const cellVal = String(wsTech[cellRef].v || "").toUpperCase();
                
                if (R === 0) {
                    // Header row
                    wsTech[cellRef].s.font.bold = true;
                    wsTech[cellRef].s.fill = { fgColor: { rgb: "D9E1F2" } }; // Light blue
                } else if (isSubheader) {
                    // Subheader row
                    wsTech[cellRef].s.font.bold = true;
                    wsTech[cellRef].s.fill = { fgColor: { rgb: "EFEFEF" } }; // Light grey
                } else {
                    // Signal colors
                    if (cellVal.includes("BULLISH") || cellVal === "BUY") {
                        wsTech[cellRef].s.fill = { fgColor: { rgb: "D9EAD3" } }; // Green
                        wsTech[cellRef].s.font.color = { rgb: "274E13" }; 
                        wsTech[cellRef].s.font.bold = true;
                    } else if (cellVal.includes("BEARISH") || cellVal === "SELL") {
                        wsTech[cellRef].s.fill = { fgColor: { rgb: "F4CCCC" } }; // Red
                        wsTech[cellRef].s.font.color = { rgb: "990000" };
                        wsTech[cellRef].s.font.bold = true;
                    }
                }
            }
        }
    }

    XLSX.utils.book_append_sheet(wb, wsTech, "Technicals");

    // --- 3. Export ---
    const now = new Date();
    const months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
    const formattedDate = `${months[now.getMonth()]} ${String(now.getDate()).padStart(2, '0')} ${now.getFullYear()}`;
    XLSX.writeFile(wb, `Shani_${appState.symbol}_${appState.selectedExpiry} - ${formattedDate}.xlsx`);
}

// ----------------------------------------------------
// Event Handlers Setup & Inits
// ----------------------------------------------------

// Close Greeks Modal
elements.modalClose.onclick = function() {
    elements.greeksModal.classList.remove("show");
    activeInspectedStrike = null;
};

// Help & Regulatory Info Modal Logic
function openInfoTab(tabId) {
    elements.infoModal.classList.add("show");
    
    // Deactivate all tab buttons & contents, activate target
    const tabButtons = elements.infoModal.querySelectorAll(".info-tab-btn");
    tabButtons.forEach(btn => {
        if (btn.getAttribute("data-tab") === tabId) {
            btn.classList.add("active");
        } else {
            btn.classList.remove("active");
        }
    });
    
    const tabContents = elements.infoModal.querySelectorAll(".info-tab-content");
    tabContents.forEach(content => {
        if (content.id === tabId) {
            content.classList.add("active");
        } else {
            content.classList.remove("active");
        }
    });
}

// Robust event delegation click handler for Info Modal triggers
document.addEventListener("click", function(e) {
    const userManualTrigger = e.target.closest("#footer-user-manual-btn, #user-manual-btn");
    const termsTrigger = e.target.closest("#footer-terms-btn, #terms-btn");
    const closeTrigger = e.target.closest("#info-modal-close");
    
    if (userManualTrigger) {
        e.preventDefault();
        openInfoTab("user-manual");
    } else if (termsTrigger) {
        e.preventDefault();
        openInfoTab("terms-conditions");
    } else if (closeTrigger) {
        const infoM = elements.infoModal || document.getElementById("info-modal");
        if (infoM) infoM.classList.remove("show");
    }
});

// Bind clicks to individual tab buttons
document.querySelectorAll(".info-tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        const tabId = btn.getAttribute("data-tab");
        openInfoTab(tabId);
    });
});

window.addEventListener("click", function(event) {
    if (event.target == elements.greeksModal) {
        elements.greeksModal.classList.remove("show");
        activeInspectedStrike = null;
    }
    const infoModalEl = elements.infoModal || document.getElementById("info-modal");
    if (event.target == infoModalEl) {
        infoModalEl.classList.remove("show");
    }
});

// Bind sliders to number boxes and state values
bindSlider(elements.bsmSpot, elements.bsmSpotSlider, "spot", recalculateAndRender);
bindSlider(elements.bsmVol, elements.bsmVolSlider, "volatility", recalculateAndRender);
bindSlider(elements.bsmDays, elements.bsmDaysSlider, "daysToExpiry", () => {
    syncCustomExpiryUI(appState.daysToExpiry);
    recalculateAndRender();
});
bindSlider(elements.bsmRate, elements.bsmRateSlider, "riskFreeRate", recalculateAndRender);
bindSlider(elements.bsmDiv, elements.bsmDivSlider, "dividendYield", recalculateAndRender);

// Custom Expiry Date & DTE UI Synchronization
function syncCustomExpiryUI(days, dateStr) {
    if (days < 1) days = 1;
    appState.daysToExpiry = days;
    
    if (elements.bsmDays) elements.bsmDays.value = days;
    if (elements.bsmDaysSlider) elements.bsmDaysSlider.value = days;
    
    const dteBadge = document.getElementById("terminal-dte-badge");
    if (dteBadge) {
        dteBadge.textContent = `${days} DTE`;
    }
    
    const customDateInput = document.getElementById("custom-expiry-date");
    if (customDateInput) {
        if (dateStr) {
            customDateInput.value = dateStr;
        } else {
            const targetDate = new Date();
            targetDate.setDate(targetDate.getDate() + days);
            const y = targetDate.getFullYear();
            const m = String(targetDate.getMonth() + 1).padStart(2, '0');
            const d = String(targetDate.getDate()).padStart(2, '0');
            customDateInput.value = `${y}-${m}-${d}`;
        }
    }
    
    const btn7 = document.getElementById("btn-exp-7");
    const btn14 = document.getElementById("btn-exp-14");
    const btn30 = document.getElementById("btn-exp-30");
    if (btn7) btn7.classList.toggle("active", days === 7);
    if (btn14) btn14.classList.toggle("active", days === 14);
    if (btn30) btn30.classList.toggle("active", days === 30);
}

function setPresetExpiry(days) {
    const today = new Date();
    const targetDate = new Date();
    targetDate.setDate(today.getDate() + days);
    const y = targetDate.getFullYear();
    const m = String(targetDate.getMonth() + 1).padStart(2, '0');
    const d = String(targetDate.getDate()).padStart(2, '0');
    const dateStr = `${y}-${m}-${d}`;
    
    appState.applySimulation = true;
    if (elements.applySimulationToggle) {
        elements.applySimulationToggle.checked = true;
    }
    
    if (elements.expirySelect) {
        for (let i = 0; i < elements.expirySelect.options.length; i++) {
            if (elements.expirySelect.options[i].value === dateStr) {
                elements.expirySelect.selectedIndex = i;
                appState.selectedExpiry = dateStr;
                break;
            }
        }
    }
    
    syncCustomExpiryUI(days, dateStr);
    recalculateAndRender();
}

// Listeners for selectors
elements.expirySelect.addEventListener("change", (e) => {
    appState.selectedExpiry = e.target.value;
    appState.selectedStrike = "ALL"; // Reset strike filter on expiry change
    
    // Estimate expiry days automatically based on select date
    let diffDays = 30;
    try {
        const today = new Date();
        today.setHours(0,0,0,0);
        const exp = new Date(appState.selectedExpiry + 'T00:00:00');
        exp.setHours(0,0,0,0);
        diffDays = Math.max(Math.round((exp - today) / (1000 * 60 * 60 * 24)), 1);
    } catch (err) {
        console.error(err);
        diffDays = 30;
    }
    
    syncCustomExpiryUI(diffDays, appState.selectedExpiry);
    recalculateAndRender();
});

// Custom Date & Presets Handlers
const customDateInput = document.getElementById("custom-expiry-date");
if (customDateInput) {
    customDateInput.addEventListener("change", (e) => {
        const val = e.target.value;
        if (!val) return;
        const selected = new Date(val + 'T00:00:00');
        if (isNaN(selected.getTime())) return;
        
        const today = new Date();
        today.setHours(0,0,0,0);
        selected.setHours(0,0,0,0);
        const diff = Math.max(Math.round((selected - today) / (1000 * 60 * 60 * 24)), 1);
        
        if (elements.expirySelect) {
            for (let i = 0; i < elements.expirySelect.options.length; i++) {
                if (elements.expirySelect.options[i].value === val) {
                    elements.expirySelect.selectedIndex = i;
                    appState.selectedExpiry = val;
                    break;
                }
            }
        }
        
        appState.applySimulation = true;
        if (elements.applySimulationToggle) {
            elements.applySimulationToggle.checked = true;
        }
        
        syncCustomExpiryUI(diff, val);
        recalculateAndRender();
    });
}

document.getElementById("btn-exp-7")?.addEventListener("click", () => setPresetExpiry(7));
document.getElementById("btn-exp-14")?.addEventListener("click", () => setPresetExpiry(14));
document.getElementById("btn-exp-30")?.addEventListener("click", () => setPresetExpiry(30));

// Search button trigger
document.getElementById("main-search-btn").addEventListener("click", () => {
    const symbol = elements.symbolSearchInput.value.trim().toUpperCase();
    if (symbol) {
        closeSuggestions();
        fetchTickerData(symbol);
    }
});

// Refresh button trigger
elements.reloadBtn.addEventListener("click", () => {
    const act = appState.symbol || "NIFTY";
    fetchTickerData(act);
});

// Download CSV trigger
elements.downloadCsvBtn.addEventListener("click", downloadCSV);

// Reset BSM input panel to latest API loaded market metrics
elements.resetMarketBtn.addEventListener("click", () => {
    appState.spot = appState.marketSpot;
    
    // Restore volatility, days, rate, div
    const chainRows = appState.optionChains[appState.selectedExpiry] || [];
    let avgIV = 15.0;
    if (chainRows.length > 0) {
        let sumIV = 0, count = 0;
        chainRows.forEach(r => {
            if (r.call?.iv > 0) { sumIV += r.call.iv; count++; }
            if (r.put?.iv > 0) { sumIV += r.put.iv; count++; }
        });
        if (count > 0) avgIV = sumIV / count;
    }
    appState.volatility = avgIV;
    
    try {
        const today = new Date();
        today.setHours(0,0,0,0);
        const exp = new Date(appState.selectedExpiry + 'T00:00:00');
        exp.setHours(0,0,0,0);
        appState.daysToExpiry = Math.max(Math.round((exp - today) / (1000 * 60 * 60 * 24)), 1);
    } catch (e) {
        appState.daysToExpiry = 30;
    }
    
    appState.riskFreeRate = appState.marketRate || ((appState.symbol === "AAPL" || appState.symbol === "TSLA") ? 5.25 : 6.50);
    appState.dividendYield = appState.marketYield || 0.0;
    
    // Reset simulation toggles
    appState.applySimulation = false;
    if (elements.applySimulationToggle) {
        elements.applySimulationToggle.checked = false;
    }
    
    // Refresh control visual values
    elements.bsmSpot.value = appState.spot;
    elements.bsmSpotSlider.value = appState.spot;
    elements.bsmVol.value = appState.volatility;
    elements.bsmVolSlider.value = appState.volatility;
    elements.bsmDays.value = appState.daysToExpiry;
    elements.bsmDaysSlider.value = appState.daysToExpiry;
    elements.bsmRate.value = appState.riskFreeRate;
    elements.bsmRateSlider.value = appState.riskFreeRate;
    elements.bsmDiv.value = appState.dividendYield;
    elements.bsmDivSlider.value = appState.dividendYield;
    
    syncCustomExpiryUI(appState.daysToExpiry, appState.selectedExpiry);
    recalculateAndRender();
});

function startHeaderClock() {
    if (!elements.underlyingTime) return;

    function update() {
        const now = new Date();
        
        let hours = now.getHours();
        const minutes = String(now.getMinutes()).padStart(2, '0');
        const seconds = String(now.getSeconds()).padStart(2, '0');
        const ampm = hours >= 12 ? 'pm' : 'am';
        hours = hours % 12;
        hours = hours ? hours : 12; // the hour '0' should be '12'
        const hoursStr = String(hours).padStart(2, '0');
        
        const day = String(now.getDate()).padStart(2, '0');
        const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        const monthStr = months[now.getMonth()];
        const year = now.getFullYear();
        
        elements.underlyingTime.textContent = `${day} ${monthStr} ${year} ${hoursStr}:${minutes}:${seconds} ${ampm}`;
        
        // Update elapsed time since last price update
        if (elements.underlyingTimeElapsed && appState.lastPriceUpdated) {
            const diffMs = now - appState.lastPriceUpdated;
            const diffSec = Math.floor(diffMs / 1000);
            if (diffSec < 0) {
                elements.underlyingTimeElapsed.textContent = "(updated live)";
            } else if (diffSec <= 1) {
                elements.underlyingTimeElapsed.textContent = "(updated live)";
            } else {
                elements.underlyingTimeElapsed.textContent = `(updated ${diffSec}s ago)`;
            }
        }
    }
    
    update();
    setInterval(update, 1000);
}

function renderTechnicalsUnavailable(symbol) {
    const sym = symbol || appState.symbol || "NIFTY";
    const symbolLbl = document.getElementById("tech-symbol-lbl");
    if (symbolLbl) symbolLbl.textContent = sym;

    const badgeEl = document.getElementById("tech-overall-badge");
    if (badgeEl) {
        badgeEl.textContent = "UNAVAILABLE";
        badgeEl.className = "tech-badge badge-neutral";
    }

    const countsEl = document.getElementById("tech-summary-counts");
    if (countsEl) countsEl.textContent = "Data unavailable";

    const updateVal = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    };
    const updatePill = (id, label, cls) => {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = label;
            el.className = `tech-pill ${cls}`;
        }
    };

    updateVal("tech-rsi-val", "--");
    updatePill("tech-rsi-pill", "--", "pill-neutral");

    updateVal("tech-macd-val", "--");
    updateVal("tech-macd-hist", "--");
    updatePill("tech-macd-pill", "--", "pill-neutral");

    updateVal("tech-bb-upper", "--");
    updateVal("tech-bb-middle", "--");
    updateVal("tech-bb-lower", "--");
    updatePill("tech-bb-pill", "--", "pill-neutral");

    updateVal("tech-sma20-val", "--");
    updatePill("tech-sma20-pill", "--", "pill-neutral");
    updateVal("tech-sma50-val", "--");
    updatePill("tech-sma50-pill", "--", "pill-neutral");
    updateVal("tech-ema20-val", "--");
    updatePill("tech-ema20-pill", "--", "pill-neutral");
    updateVal("tech-ema50-val", "--");
    updatePill("tech-ema50-pill", "--", "pill-neutral");

    updateVal("tech-atr-val", "--");

    ["tech-pivot-p", "tech-pivot-r1", "tech-pivot-r2", "tech-pivot-r3", "tech-pivot-s1", "tech-pivot-s2", "tech-pivot-s3"].forEach(id => {
        updateVal(id, "--");
    });
}

// Technicals Tab Logic
async function fetchAndRenderTechnicals(symbol) {
    const sym = symbol || appState.symbol || "NIFTY";
    const spot = appState.marketSpot || appState.spot;
    const symbolLbl = document.getElementById("tech-symbol-lbl");
    if (symbolLbl) symbolLbl.textContent = sym;

    if (!spot || spot <= 0) {
        renderTechnicalsUnavailable(sym);
        return;
    }

    try {
        const url = `/v1/derivatives/${encodeURIComponent(sym)}/technicals?spot=${spot}`;
        const res = await fetch(url);
        if (res.ok) {
            const data = await res.json();
            appState.technicals = data;
            renderTechnicalsData(data);
            return;
        }
    } catch (err) {
        console.warn("Backend technicals endpoint unavailable:", err);
    }

    renderTechnicalsUnavailable(sym);
}



function renderTechnicalsData(data) {
    if (!data) return;

    try {
        // Overall summary badge
        const badgeEl = document.getElementById("tech-overall-badge");
        const countsEl = document.getElementById("tech-summary-counts");

        if (badgeEl && data.summary) {
            badgeEl.textContent = data.summary.overall_signal;
            badgeEl.className = "tech-badge " + (
                data.summary.overall_badge === "BULLISH" ? "badge-bullish" :
                data.summary.overall_badge === "BEARISH" ? "badge-bearish" : "badge-neutral"
            );
        }
        if (countsEl && data.summary) {
            countsEl.textContent = `${data.summary.bullish_count} Buy | ${data.summary.neutral_count} Neutral | ${data.summary.bearish_count} Sell`;
        }

        // RSI
        if (data.rsi) {
            const rsiValEl = document.getElementById("tech-rsi-val");
            if (rsiValEl) rsiValEl.textContent = formatNumber(data.rsi.value, 2);
            const pill = document.getElementById("tech-rsi-pill");
            if (pill) {
                pill.textContent = data.rsi.label || data.rsi.signal;
                pill.className = "tech-pill " + (
                    data.rsi.signal === "BULLISH" ? "pill-bullish" :
                    data.rsi.signal === "BEARISH" ? "pill-bearish" : "pill-neutral"
                );
            }
        }

        // MACD
        if (data.macd) {
            const macdValEl = document.getElementById("tech-macd-val");
            if (macdValEl) macdValEl.textContent = `${formatNumber(data.macd.macd, 2)} (Hist: ${formatNumber(data.macd.histogram, 2)})`;
            const pill = document.getElementById("tech-macd-pill");
            if (pill) {
                pill.textContent = data.macd.label || data.macd.signal;
                pill.className = "tech-pill " + (
                    data.macd.signal === "BULLISH" ? "pill-bullish" :
                    data.macd.signal === "BEARISH" ? "pill-bearish" : "pill-neutral"
                );
            }
        }

        // Bollinger Bands
        if (data.bollinger) {
            const bbSubEl = document.getElementById("tech-bb-sub");
            if (bbSubEl) bbSubEl.textContent = `Upper: ${formatNumber(data.bollinger.upper, 2)} | Lower: ${formatNumber(data.bollinger.lower, 2)}`;
            const pill = document.getElementById("tech-bb-pill");
            if (pill) {
                pill.textContent = data.bollinger.label || data.bollinger.signal;
                pill.className = "tech-pill " + (
                    data.bollinger.signal === "BULLISH" ? "pill-bullish" :
                    data.bollinger.signal === "BEARISH" ? "pill-bearish" : "pill-neutral"
                );
            }
        }

        // Moving Averages
        if (data.moving_averages) {
            data.moving_averages.forEach(ma => {
                let valId = "";
                let pillId = "";
                if (ma.name === "SMA 20") { valId = "tech-sma20-val"; pillId = "tech-sma20-pill"; }
                else if (ma.name === "SMA 50") { valId = "tech-sma50-val"; pillId = "tech-sma50-pill"; }
                else if (ma.name === "EMA 20") { valId = "tech-ema20-val"; pillId = "tech-ema20-pill"; }
                else if (ma.name === "EMA 50") { valId = "tech-ema50-val"; pillId = "tech-ema50-pill"; }

                if (valId && document.getElementById(valId)) {
                    document.getElementById(valId).textContent = formatNumber(ma.value, 2);
                }
                if (pillId && document.getElementById(pillId)) {
                    const pill = document.getElementById(pillId);
                    pill.textContent = ma.signal;
                    pill.className = "tech-pill " + (
                        ma.signal === "BULLISH" ? "pill-bullish" :
                        ma.signal === "BEARISH" ? "pill-bearish" : "pill-neutral"
                    );
                }
            });
        }

        // Volatility & Pivots
        if (data.atr && document.getElementById("tech-atr-val")) {
            document.getElementById("tech-atr-val").textContent = formatNumber(data.atr, 2);
        }
        if (data.pivots) {
            if (document.getElementById("tech-r3")) document.getElementById("tech-r3").textContent = formatNumber(data.pivots.r3, 2);
            if (document.getElementById("tech-r2")) document.getElementById("tech-r2").textContent = formatNumber(data.pivots.r2, 2);
            if (document.getElementById("tech-r1")) document.getElementById("tech-r1").textContent = formatNumber(data.pivots.r1, 2);
            if (document.getElementById("tech-pivot")) document.getElementById("tech-pivot").textContent = formatNumber(data.pivots.p, 2);
            if (document.getElementById("tech-s1")) document.getElementById("tech-s1").textContent = formatNumber(data.pivots.s1, 2);
            if (document.getElementById("tech-s2")) document.getElementById("tech-s2").textContent = formatNumber(data.pivots.s2, 2);
            if (document.getElementById("tech-s3")) document.getElementById("tech-s3").textContent = formatNumber(data.pivots.s3, 2);
        }
    } catch (err) {
        console.error("Error rendering technicals data:", err);
    }
}


function setupTabSwitching() {
    const tabOptionChain = document.getElementById("tab-option-chain");
    const tabTechnicals = document.getElementById("tab-technicals");
    const optionChainContainer = document.getElementById("option-chain-view-container") || document.querySelector(".main-content");
    const technicalsContainer = document.getElementById("technicals-view-container");

    if (!tabOptionChain || !tabTechnicals || !optionChainContainer || !technicalsContainer) {
        console.warn("Tab elements not found yet:", { tabOptionChain, tabTechnicals, optionChainContainer, technicalsContainer });
        return;
    }

    function showOptionChain() {
        tabOptionChain.classList.add("active");
        tabTechnicals.classList.remove("active");
        optionChainContainer.style.setProperty("display", "block", "important");
        technicalsContainer.style.setProperty("display", "none", "important");
    }

    function showTechnicals() {
        tabTechnicals.classList.add("active");
        tabOptionChain.classList.remove("active");
        optionChainContainer.style.setProperty("display", "none", "important");
        technicalsContainer.style.setProperty("display", "block", "important");
        fetchAndRenderTechnicals(appState.symbol);
    }

    tabOptionChain.onclick = (e) => {
        if (e) e.preventDefault();
        showOptionChain();
    };

    tabTechnicals.onclick = (e) => {
        if (e) e.preventDefault();
        showTechnicals();
    };
}

// Global delegated fallback listener
document.addEventListener("click", (e) => {
    const target = e.target.closest("#tab-technicals, #tab-option-chain");
    if (!target) return;
    e.preventDefault();

    if (target.id === "tab-technicals") {
        document.getElementById("tab-technicals")?.classList.add("active");
        document.getElementById("tab-option-chain")?.classList.remove("active");
        const optContainer = document.getElementById("option-chain-view-container") || document.querySelector(".main-content");
        const techContainer = document.getElementById("technicals-view-container");
        if (optContainer) optContainer.style.setProperty("display", "none", "important");
        if (techContainer) techContainer.style.setProperty("display", "block", "important");
        fetchAndRenderTechnicals(appState.symbol);
    } else if (target.id === "tab-option-chain") {
        document.getElementById("tab-option-chain")?.classList.add("active");
        document.getElementById("tab-technicals")?.classList.remove("active");
        const optContainer = document.getElementById("option-chain-view-container") || document.querySelector(".main-content");
        const techContainer = document.getElementById("technicals-view-container");
        if (optContainer) optContainer.style.setProperty("display", "block", "important");
        if (techContainer) techContainer.style.setProperty("display", "none", "important");
    }
});

// --- Theme Switching System ---
function initThemeSystem() {
    const themeBtn = document.getElementById("theme-toggle-btn");
    const darkIcon = document.getElementById("theme-toggle-dark-icon");
    const lightIcon = document.getElementById("theme-toggle-light-icon");
    
    if (!themeBtn || !darkIcon || !lightIcon) return;
    
    // Read cached preference or default to light
    let currentTheme = localStorage.getItem("shaniTheme") || "light";
    appState.theme = currentTheme;
    
    function applyTheme(theme) {
        if (theme === "light") {
            document.body.classList.add("light-theme");
            darkIcon.style.display = "block";
            lightIcon.style.display = "none";
        } else {
            document.body.classList.remove("light-theme");
            darkIcon.style.display = "none";
            lightIcon.style.display = "block";
        }
    }
    
    // Initial apply
    applyTheme(currentTheme);
    
    // Toggle on click
    themeBtn.onclick = () => {
        const newTheme = appState.theme === "dark" ? "light" : "dark";
        appState.theme = newTheme;
        localStorage.setItem("shaniTheme", newTheme);
        applyTheme(newTheme);
    };
}

// --- Layout Switcher System ---
function initLayoutSystem() {
    const stdBtn = document.getElementById("view-standard-btn");
    const callsBtn = document.getElementById("view-calls-btn");
    const putsBtn = document.getElementById("view-puts-btn");
    const greeksBtn = document.getElementById("view-greeks-btn");
    
    const buttons = [stdBtn, callsBtn, putsBtn, greeksBtn];
    
    function setBtnActive(activeBtn) {
        buttons.forEach(btn => {
            if (btn) btn.classList.remove("active");
        });
        if (activeBtn) activeBtn.classList.add("active");
    }
    
    if (stdBtn) {
        stdBtn.onclick = () => {
            appState.layoutMode = "standard";
            setBtnActive(stdBtn);
            recalculateAndRender();
        };
    }
    if (callsBtn) {
        callsBtn.onclick = () => {
            appState.layoutMode = "calls";
            setBtnActive(callsBtn);
            recalculateAndRender();
        };
    }
    if (putsBtn) {
        putsBtn.onclick = () => {
            appState.layoutMode = "puts";
            setBtnActive(putsBtn);
            recalculateAndRender();
        };
    }
    if (greeksBtn) {
        greeksBtn.onclick = () => {
            appState.layoutMode = "greeks";
            setBtnActive(greeksBtn);
            recalculateAndRender();
        };
    }
}

// Background Particle Canvas streaming
function initCanvasBackground() {
    const canvas = document.getElementById("bg-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    window.addEventListener("resize", () => {
        width = (canvas.width = window.innerWidth);
        height = (canvas.height = window.innerHeight);
    });

    // Particle definition
    class Particle {
        constructor() {
            this.x = Math.random() * width;
            this.y = Math.random() * height;
            this.size = Math.random() * 1.5 + 0.5;
            this.speedX = Math.random() * 0.8 + 0.2; // Move right
            this.speedY = (Math.random() - 0.5) * 0.1;
            
            // Adjust colors/opacities depending on light theme
            const colors = [
                "rgba(99, 102, 241, 0.45)", // Indigo
                "rgba(6, 182, 212, 0.45)",  // Teal
                "rgba(243, 112, 33, 0.35)"   // Orange
            ];
            this.color = colors[Math.floor(Math.random() * colors.length)];
        }

        update() {
            this.x += this.speedX;
            this.y += this.speedY;

            // Loop around screen edge
            if (this.x > width) {
                this.x = 0;
                this.y = Math.random() * height;
            }
            if (this.y > height || this.y < 0) {
                this.y = Math.random() * height;
            }
        }

        draw() {
            ctx.beginPath();
            ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
            ctx.fillStyle = this.color;
            ctx.fill();
        }
    }

    // Create particle array (optimized count)
    const particles = [];
    const particleCount = Math.min(35, Math.max(15, Math.floor(width / 40)));
    for (let i = 0; i < particleCount; i++) {
        particles.push(new Particle());
    }

    // Draw connecting lines if particles are close
    function connect() {
        let maxDistance = 90;
        const isLight = document.body.classList.contains("light-theme");
        const lineOpacityMultiplier = isLight ? 0.18 : 0.08;
        
        for (let a = 0; a < particles.length; a++) {
            for (let b = a + 1; b < particles.length; b++) {
                let distSq = (particles[a].x - particles[b].x) ** 2 + 
                             (particles[a].y - particles[b].y) ** 2;
                if (distSq < maxDistance ** 2) {
                    let opacity = 1 - Math.sqrt(distSq) / maxDistance;
                    ctx.strokeStyle = `rgba(99, 102, 241, ${opacity * lineOpacityMultiplier})`;
                    ctx.lineWidth = 0.5;
                    ctx.beginPath();
                    ctx.moveTo(particles[a].x, particles[a].y);
                    ctx.lineTo(particles[b].x, particles[b].y);
                    ctx.stroke();
                }
            }
        }
    }

    // Animation loop throttled to ~30fps and paused when hidden
    let lastFrameTime = 0;
    let animId = null;

    function animate(timestamp) {
        if (document.hidden) {
            animId = null;
            return;
        }

        if (timestamp - lastFrameTime >= 33) {
            lastFrameTime = timestamp;
            ctx.clearRect(0, 0, width, height);
            particles.forEach(p => {
                p.update();
                p.draw();
            });
            connect();
        }
        animId = requestAnimationFrame(animate);
    }

    document.addEventListener("visibilitychange", () => {
        if (!document.hidden && !animId) {
            lastFrameTime = performance.now();
            animId = requestAnimationFrame(animate);
        }
    });

    animId = requestAnimationFrame(animate);
}

// App Entry Point
async function initApp() {
    initCanvasBackground();
    startHeaderClock();
    setupAutocomplete();
    setupTabSwitching();
    setupAlertsModal();
    setupBsmModal();
    initThemeSystem();
    initLayoutSystem();
    initResearchExportModal();
    await fetchTickerData("NIFTY");
}

window.onload = initApp;

function setupBsmModal() {
    const modal = elements.bsmModal || document.getElementById("bsm-modal");
    const openBtn = elements.openBsmModalBtn || document.getElementById("open-bsm-modal-btn");
    const closeBtn = elements.bsmModalClose || document.getElementById("bsm-modal-close");
    const applyToggle = elements.applySimulationToggle || document.getElementById("apply-simulation-toggle");
    const fullChainBtn = elements.toggleFullChainBtn || document.getElementById("toggle-full-chain-btn");

    if (openBtn && modal) {
        openBtn.onclick = () => {
            modal.classList.add("show");
        };
    }

    if (closeBtn && modal) {
        closeBtn.onclick = () => modal.classList.remove("show");
    }

    window.addEventListener("click", (event) => {
        if (event.target === modal) {
            modal.classList.remove("show");
        }
    });

    if (applyToggle) {
        applyToggle.addEventListener("change", (e) => {
            appState.applySimulation = e.target.checked;
            recalculateAndRender();
        });
    }

    if (fullChainBtn) {
        fullChainBtn.addEventListener("click", () => {
            appState.showFullChain = !appState.showFullChain;
            if (appState.showFullChain) {
                fullChainBtn.classList.add("active");
                fullChainBtn.textContent = "Show ATM +/- 20";
            } else {
                fullChainBtn.classList.remove("active");
                fullChainBtn.textContent = "Show Full Chain";
            }
            recalculateAndRender();
        });
    }

    const calculateBtn = elements.bsmCalculateBtn || document.getElementById("bsm-calculate-btn");
    if (calculateBtn) {
        calculateBtn.addEventListener("click", () => {
            activateSimulation();
            recalculateAndRender();
        });
    }
}

// --- Alerts & Notifications Modal & Toast Handlers ---
function setupAlertsModal() {
    const bellBtn = document.getElementById("notification-bell-btn");
    const alertsModal = document.getElementById("alerts-modal");
    const closeBtn = document.getElementById("alerts-modal-close");
    const form = document.getElementById("create-alert-form");

    if (!bellBtn || !alertsModal) return;

    bellBtn.onclick = () => {
        alertsModal.classList.add("show");
        loadActiveAlertRules();
    };

    if (closeBtn) {
        closeBtn.onclick = () => alertsModal.classList.remove("show");
    }

    if (form) {
        form.onsubmit = async (e) => {
            e.preventDefault();
            const symbol = document.getElementById("alert-symbol-input").value.trim().toUpperCase();
            const condition = document.getElementById("alert-condition-select").value;
            const threshold = parseFloat(document.getElementById("alert-threshold-input").value);
            const cooldown = parseInt(document.getElementById("alert-cooldown-input").value, 10);

            if (!symbol || isNaN(threshold)) {
                alert("Please provide valid symbol and threshold value");
                return;
            }

            try {
                const res = await fetch("/v1/notifications/alerts", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        symbol: symbol,
                        condition_type: condition,
                        threshold: threshold,
                        cooldown_seconds: cooldown,
                        channels: ["WEBSOCKET"]
                    })
                });
                if (res.ok) {
                    loadActiveAlertRules();
                    document.getElementById("alert-threshold-input").value = "";
                } else {
                    alert("Failed to create alert rule");
                }
            } catch (err) {
                console.error("Alert creation failed:", err);
            }
        };
    }
}

async function loadActiveAlertRules() {
    const listEl = document.getElementById("active-alerts-list");
    if (!listEl) return;
    try {
        const res = await fetch("/v1/notifications/alerts");
        if (res.ok) {
            const rules = await res.json();
            if (rules.length === 0) {
                listEl.innerHTML = '<div class="active-alert-empty">No alert rules configured.</div>';
                return;
            }
            listEl.innerHTML = rules.map(r => `
                <div class="active-alert-item">
                    <div>
                        <strong style="color: var(--accent-indigo);">${escapeHtml(r.symbol)}</strong>: ${escapeHtml(r.condition_type)} &gt; ${escapeHtml(String(r.threshold))} (Cooldown: ${r.cooldown_seconds}s)
                    </div>
                    <button onclick="deleteAlertRule('${escapeHtml(String(r.id))}')" style="background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 4px; padding: 4px 10px; font-size: 11px; font-weight: 600; cursor: pointer;">Delete</button>
                </div>
            `).join("");
        }
    } catch (err) {
        console.error("Failed to load active alert rules:", err);
    }
}

window.deleteAlertRule = async function(ruleId) {
    try {
        const res = await fetch(`/v1/notifications/alerts/${ruleId}`, { method: "DELETE" });
        if (res.ok) {
            loadActiveAlertRules();
        }
    } catch (err) {
        console.error("Failed to delete alert rule:", err);
    }
};

function showAlertToast(message) {
    const badge = document.getElementById("alert-badge-count");
    if (badge) {
        const cnt = parseInt(badge.textContent || "0", 10) + 1;
        badge.textContent = cnt;
        badge.style.display = "inline-block";
    }

    const toast = document.createElement("div");
    toast.style.cssText = "position: fixed; bottom: 20px; right: 20px; background: #1e1b4b; border: 1px solid #6366f1; color: white; padding: 14px 20px; border-radius: 8px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); z-index: 9999; font-size: 13px; font-weight: 500;";
    toast.innerHTML = `<strong style="color: #818cf8;">🔔 Market Alert</strong><br>${escapeHtml(message)}`;
    document.body.appendChild(toast);

    setTimeout(() => {
        toast.remove();
    }, 6000);
}

// --- Multi-Day Historical Research Export Modal Handler ---
function formatLocalDate(d) {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function initResearchExportModal() {
    const openBtn = document.getElementById("open-research-export-btn");
    const downloadCsvBtn = document.getElementById("download-csv-btn");
    const modal = document.getElementById("research-export-modal");
    const closeBtn = document.getElementById("research-export-modal-close");
    const triggerBtn = document.getElementById("trigger-research-export-btn");

    const symbolInput = document.getElementById("research-export-symbol");
    const startDateInput = document.getElementById("research-export-start-date");
    const endDateInput = document.getElementById("research-export-end-date");
    const layoutSelect = document.getElementById("research-export-layout");

    function setupDefaultDates(daysBack = 10) {
        if (symbolInput) {
            symbolInput.value = appState.symbol || "NIFTY";
        }
        const today = new Date();
        const past = new Date(today);
        past.setDate(today.getDate() - daysBack);

        if (endDateInput) {
            endDateInput.value = formatLocalDate(today);
        }
        if (startDateInput) {
            startDateInput.value = formatLocalDate(past);
        }
    }

    if (openBtn && modal) {
        openBtn.addEventListener("click", () => {
            setupDefaultDates(10);
            modal.classList.add("show");
        });
    }

    // Bind Quick Preset Buttons inside modal
    if (modal) {
        const presetBtns = modal.querySelectorAll(".preset-btn");
        presetBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                const days = parseInt(btn.getAttribute("data-days") || "10", 10);
                setupDefaultDates(days);
            });
        });
    }

    if (closeBtn && modal) {
        closeBtn.addEventListener("click", () => {
            modal.classList.remove("show");
        });
    }

    window.addEventListener("click", (e) => {
        if (e.target === modal) {
            modal.classList.remove("show");
        }
    });

    if (triggerBtn) {
        triggerBtn.addEventListener("click", async () => {
            const sym = symbolInput ? symbolInput.value.trim().toUpperCase() : "NIFTY";
            const startDt = startDateInput ? startDateInput.value : "";
            const endDt = endDateInput ? endDateInput.value : "";
            const layout = layoutSelect ? layoutSelect.value : "separate_tabs";

            if (!startDt || !endDt) {
                alert("Please select both Start Date and End Date.");
                return;
            }

            if (new Date(startDt) > new Date(endDt)) {
                alert("Start Date must be before or equal to End Date.");
                return;
            }

            triggerBtn.disabled = true;
            const originalHtml = triggerBtn.innerHTML;
            triggerBtn.innerHTML = `<span>Generating Multi-Day Excel...</span>`;

            try {
                const url = `/v1/export/research-eod?symbol=${encodeURIComponent(sym)}&start_date=${encodeURIComponent(startDt)}&end_date=${encodeURIComponent(endDt)}&layout_mode=${encodeURIComponent(layout)}`;
                const resp = await fetch(url);

                if (!resp.ok) {
                    const errJson = await resp.json().catch(() => ({ detail: "Export failed" }));
                    alert(`Export Error: ${errJson.detail || resp.statusText}`);
                    return;
                }

                const blob = await resp.blob();
                const downloadUrl = window.URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = downloadUrl;
                a.download = `AlphaStreams_${sym}_${startDt}_to_${endDt}.xlsx`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(downloadUrl);

                if (modal) modal.classList.remove("show");
            } catch (err) {
                console.error("Research Export Error:", err);
                alert(`Export Failed: ${err.message}`);
            } finally {
                triggerBtn.disabled = false;
                triggerBtn.innerHTML = originalHtml;
            }
        });
    }
}



