/* --- Shani Premium Landing Page Script --- */
document.addEventListener("DOMContentLoaded", () => {
    // 1. Particle Canvas Streaming Background
    initCanvasBackground();

    // 2. Interactive Black-Scholes-Merton (BSM) Calculator
    initBsmSimulator();

    // 3. Dynamic Sentiment Indicator Stream
    initSentimentStream();

    // 4. Supabase Session Check
    checkSupabaseSession();
});

async function checkSupabaseSession() {
    if (typeof initSupabase !== 'undefined') {
        const supabase = await initSupabase();
        if (supabase) {
            const { data: { session } } = await supabase.auth.getSession();
            if (session) {
                // Change Login buttons to Dashboard
                const navLaunch = document.getElementById("nav-launch");
                if (navLaunch) {
                    navLaunch.textContent = "Dashboard";
                    navLaunch.href = "/dashboard.html";
                    
                    // Add Logout button next to it
                    const logoutBtn = document.createElement('button');
                    logoutBtn.textContent = "Logout";
                    logoutBtn.style.cssText = "background: transparent; color: white; border: 1px solid rgba(255,255,255,0.2); border-radius: 8px; padding: 0.5rem 1rem; cursor: pointer; font-size: 0.9rem; font-weight: 500; margin-left: 10px; font-family: inherit;";
                    logoutBtn.onmouseover = () => logoutBtn.style.backgroundColor = "rgba(255,255,255,0.1)";
                    logoutBtn.onmouseout = () => logoutBtn.style.backgroundColor = "transparent";
                    
                    logoutBtn.onclick = async () => {
                        await supabase.auth.signOut();
                        window.location.reload();
                    };
                    
                    navLaunch.parentNode.appendChild(logoutBtn);
                }
                const heroCtaBtn = document.getElementById("hero-cta-btn");
                if (heroCtaBtn) {
                    heroCtaBtn.textContent = "Go to Dashboard";
                    heroCtaBtn.href = "/dashboard.html";
                }
                const footerCtaBtn = document.getElementById("footer-cta-btn");
                if (footerCtaBtn) {
                    footerCtaBtn.textContent = "Go to Dashboard";
                    footerCtaBtn.href = "/dashboard.html";
                }
            }
        }
    }
}

/**
 * 1. Particles stream in a canvas background, flowing horizontally
 * representing option chains data streaming in real time.
 */
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
            // Palette matches the indigo, teal, orange gradient
            const colors = [
                "rgba(99, 102, 241, 0.4)", // Indigo
                "rgba(6, 182, 212, 0.4)",  // Teal
                "rgba(243, 112, 33, 0.3)"   // Orange
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

    // Create particle array
    const particles = [];
    const particleCount = Math.min(100, Math.floor(width / 15));
    for (let i = 0; i < particleCount; i++) {
        particles.push(new Particle());
    }

    // Draw connecting lines if particles are close
    function connect() {
        let maxDistance = 100;
        for (let a = 0; a < particles.length; a++) {
            for (let b = a; b < particles.length; b++) {
                let distSq = (particles[a].x - particles[b].x) ** 2 + 
                             (particles[a].y - particles[b].y) ** 2;
                if (distSq < maxDistance ** 2) {
                    let opacity = 1 - Math.sqrt(distSq) / maxDistance;
                    ctx.strokeStyle = `rgba(99, 102, 241, ${opacity * 0.08})`;
                    ctx.lineWidth = 0.5;
                    ctx.beginPath();
                    ctx.moveTo(particles[a].x, particles[a].y);
                    ctx.lineTo(particles[b].x, particles[b].y);
                    ctx.stroke();
                }
            }
        }
    }

    // Animation loop
    function animate() {
        ctx.clearRect(0, 0, width, height);
        particles.forEach(p => {
            p.update();
            p.draw();
        });
        connect();
        requestAnimationFrame(animate);
    }

    animate();
}

/**
 * 2. Real-Time Interactive Black-Scholes-Merton Calculator Widget
 */
function initBsmSimulator() {
    const spotSlider = document.getElementById("calc-spot");
    const strikeSlider = document.getElementById("calc-strike");
    const volSlider = document.getElementById("calc-vol");
    const daysSlider = document.getElementById("calc-days");

    const spotVal = document.getElementById("calc-spot-val");
    const strikeVal = document.getElementById("calc-strike-val");
    const volVal = document.getElementById("calc-vol-val");
    const daysVal = document.getElementById("calc-days-val");

    const callPriceEl = document.getElementById("res-call-price");
    const putPriceEl = document.getElementById("res-put-price");
    const callDeltaEl = document.getElementById("res-call-delta");
    const gammaEl = document.getElementById("res-gamma");

    if (!spotSlider) return;

    function calculateBSM() {
        const S = parseFloat(spotSlider.value);
        const K = parseFloat(strikeSlider.value);
        const ivPercent = parseFloat(volSlider.value);
        const days = parseFloat(daysSlider.value);

        // Update labels
        spotVal.textContent = S.toFixed(0);
        strikeVal.textContent = K.toFixed(0);
        volVal.textContent = ivPercent.toFixed(1) + "%";
        daysVal.textContent = days.toFixed(0);

        // Inputs for math
        const T = Math.max(0.0001, days / 365.0);
        const sigma = Math.max(0.01, ivPercent / 100.0);
        const r = 0.065; // 6.5% constant risk free rate
        const q = 0.012; // 1.2% constant dividend yield

        // Math Formulation
        const d1 = (Math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * Math.sqrt(T));
        const d2 = d1 - sigma * Math.sqrt(T);

        const nd1 = normalCDF(d1);
        const nd2 = normalCDF(d2);
        const nnd1 = normalCDF(-d1);
        const nnd2 = normalCDF(-d2);

        // Pricing
        const callPrice = S * Math.exp(-q * T) * nd1 - K * Math.exp(-r * T) * nd2;
        const putPrice = K * Math.exp(-r * T) * nnd2 - S * Math.exp(-q * T) * nnd1;

        // Delta
        const callDelta = Math.exp(-q * T) * nd1;
        
        // Gamma
        const normalPDF = Math.exp(-0.5 * d1 * d1) / Math.sqrt(2 * Math.PI);
        const gamma = (Math.exp(-q * T) * normalPDF) / (S * sigma * Math.sqrt(T));

        // Update UI
        callPriceEl.textContent = "₹" + Math.max(0.05, callPrice).toFixed(2);
        putPriceEl.textContent = "₹" + Math.max(0.05, putPrice).toFixed(2);
        callDeltaEl.textContent = callDelta.toFixed(3);
        gammaEl.textContent = gamma.toFixed(5);
    }

    // Attach listeners
    [spotSlider, strikeSlider, volSlider, daysSlider].forEach(slider => {
        slider.addEventListener("input", calculateBSM);
    });

    // Initial calculation
    calculateBSM();
}

/**
 * Hastings' high-accuracy approximation of Cumulative Standard Normal Distribution.
 */
function normalCDF(x) {
    const b1 = 0.319381530;
    const b2 = -0.356563782;
    const b3 = 1.781477937;
    const b4 = -1.821255978;
    const b5 = 1.330274429;
    const p = 0.2316419;
    const t = 1.0 / (1.0 + p * Math.abs(x));
    const poly = t * (b1 + t * (b2 + t * (b3 + t * (b4 + t * b5))));
    const cdf = 1.0 - (1.0 / Math.sqrt(2 * Math.PI)) * Math.exp(-0.5 * x * x) * poly;
    return x >= 0 ? cdf : 1.0 - cdf;
}

/**
 * 3. Dynamic Sentiment Indicator Stream
 * Mimics active feeds and sweeps the needle randomly within a realistic zone.
 */
function initSentimentStream() {
    const needle = document.getElementById("sentiment-needle");
    const label = document.getElementById("sentiment-label");
    const confidence = document.getElementById("sentiment-confidence");
    const terminalBody = document.getElementById("nlp-terminal-body");

    if (!needle) return;

    // List of stock tickers and options symbols to simulate NLP parsing
    const assets = ["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"];
    const newsVerbs = [
        "breaking consolidation barrier, institutional block buys observed",
        "options call writing increases at ATM strike, solidifying resistance",
        "IV spikes 8% after positive macro guidance, fair prices adjusting",
        "block order processed for near-month calls; Crank-Nicolson PDE signal bullish",
        "relative volume hits 2.5x standard deviation, spot testing support",
        "unwinding of puts observed at key strikes, short cover rally probable"
    ];

    function updateSentiment() {
        // Generate pseudo-random sentiment score (-90deg to 90deg, 0deg being neutral)
        // Let's bias it slightly bullish (e.g. 15deg to 65deg)
        const degrees = 15 + Math.floor(Math.random() * 50) + (Math.random() > 0.6 ? 15 : -15);
        needle.style.transform = `rotate(${degrees}deg)`;

        // Calculate confidence score based on degree intensity
        const confPercent = 70 + Math.floor(Math.random() * 22);
        
        let sentimentText = "Neutral";
        let sentimentColor = "#f59e0b";
        
        if (degrees > 25) {
            sentimentText = "Strong Bullish";
            sentimentColor = "#10b981";
        } else if (degrees > 10) {
            sentimentText = "Bullish";
            sentimentColor = "#34d399";
        } else if (degrees < -25) {
            sentimentText = "Strong Bearish";
            sentimentColor = "#ef4444";
        } else if (degrees < -10) {
            sentimentText = "Bearish";
            sentimentColor = "#f87171";
        }

        label.textContent = sentimentText;
        label.style.color = sentimentColor;
        confidence.textContent = `Model Confidence: ${confPercent}% | Delta Shift: +${(degrees/90).toFixed(2)}`;

        // Add a line to the simulated NLP terminal
        if (terminalBody) {
            const timeStr = new Date().toLocaleTimeString();
            const symbol = assets[Math.floor(Math.random() * assets.length)];
            const verb = newsVerbs[Math.floor(Math.random() * newsVerbs.length)];
            const sentimentClass = sentimentText.includes("Bullish") ? "bullish" : (sentimentText.includes("Bearish") ? "bearish" : "");

            const newLine = document.createElement("div");
            newLine.className = "nlp-line";
            newLine.innerHTML = `
                <span class="time">[${timeStr}]</span> 
                <span class="model">NLP_INGEST_GROUP:</span> 
                <span class="text">Analyzed news for <strong>${symbol}</strong>: ${verb}</span> 
                <span class="sentiment ${sentimentClass}">[${sentimentText}]</span>
            `;
            
            terminalBody.appendChild(newLine);
            
            // Keep container clean by pruning old entries
            while (terminalBody.children.length > 20) {
                terminalBody.removeChild(terminalBody.firstChild);
            }
            
            // Scroll to bottom
            terminalBody.scrollTop = terminalBody.scrollHeight;
        }
    }

    // Run first update
    updateSentiment();

    // Recursive setTimeout for truly random interval each cycle
    function scheduleNext() {
        setTimeout(() => {
            updateSentiment();
            scheduleNext();
        }, 6000 + Math.random() * 4000);
    }
    scheduleNext();
}
