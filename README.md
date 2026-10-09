# AI Trading Copilot

Welcome to the **AI Trading Copilot** project. This project implements a **Derivatives RAG (Retrieval-Augmented Generation) Reasoning Layer**. Instead of relying entirely on the LLM to make trading decisions, the LLM is restricted strictly to **Intent Extraction**. Once the intent is extracted, it is passed to our deterministic mathematical reasoning layer, which uses existing derivatives and technical analysis code to recommend the optimal action and "Golden Zone" for execution.

## Core Concept: Human-in-the-Loop & Derivatives RAG
The absolute golden rule of this platform is **Intent-Execution Isolation**. 
The LLM chatbot does **not** execute trades. It only extracts what the user wants to do. We then pass that intent through our proprietary mathematical models (Derivatives RAG) to find the "Golden Zone" (the optimal price limit to enter the trade). Finally, the system stages a preview for the user, and the trade is ONLY sent to the exchange when the user clicks **Confirm**.

## Architecture & Components
We created two bounded contexts (domains) to keep the architecture clean and strictly isolated:

### 1. The Copilot Domain (`domains/copilot`)
This domain handles the AI reasoning logic.
* Defines the structured `TradeIntent` that the LLM extracts (action, symbol, qty, instrument type).
* Defines the `GoldenZone` which represents the optimal price range to execute a trade.
* Acts as the core of our RAG system, using technical indicators and Black-Scholes-Merton (BSM) options pricing to calculate the fair value for orders.

### 2. The Trading Domain (`domains/trading`)
This domain handles the actual paper execution via the 021 Trade API.
* Handles authentication and order placement.
* Enforces the **Human-in-the-Loop** safety architecture. Staging an order proposal as `PENDING_APPROVAL` to be confirmed via UI.
* **Auto-Execution (Golden Zone)**: Sent to the 021 API with `book: "RL"` (Regular Limit) to execute only when the optimal price is hit.

## Documentation
- **[021 Reasoning Layer](docs/021-reasoning-layer.md)** — Architectural design of the Derivatives RAG Reasoning Layer.
- **[UI Integration & Architecture](docs/UI_INTEGRATION_AND_ARCHITECTURE_GUIDE.md)** — Guide on how to integrate the frontend UI with the Copilot AI and Trading execution loop.

## Getting Started

1. Clone and configure:
```bash
cp .env.example .env
```

2. Start the system via Docker:
```bash
docker compose up -d
```
