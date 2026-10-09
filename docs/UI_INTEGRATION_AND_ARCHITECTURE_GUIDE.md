# AI Trading Copilot: UI Integration & Architecture Guide

Welcome to the **AI Trading Copilot** project! This guide is for the frontend and backend engineering teams. It explains the core architecture, the "Golden Zone" reasoning layer we just implemented, and exactly what needs to be built next to hook up the UI.

---

## 1. Core Concept: Human-in-the-Loop & Derivatives RAG
The absolute golden rule of this platform is **Intent-Execution Isolation**. 
The LLM chatbot does **not** execute trades. It only extracts what the user wants to do. We then pass that intent through our proprietary mathematical models (Derivatives RAG) to find the "Golden Zone" (the optimal price limit to enter the trade). Finally, the system stages a preview for the user, and the trade is ONLY sent to the exchange when the user clicks **Confirm**.

---

## 2. What Is Already Built?

We have successfully migrated the math/derivatives engine and built the core AI reasoning and execution loops inside `domains/`:

### A. The Reasoning Layer (`domains/copilot/application/reasoning_layer.py`)
This is the brain. The `CopilotReasoningEngine` takes an AI-extracted `TradeIntent` and calculates whether the trade should happen right now, or if it should wait for a better price (Golden Zone).
* **For Stocks**: It uses `TechnicalIndicatorsEngine` (RSI, Bollinger Bands). If a user says "Buy TCS" but TCS is severely overbought, it will recommend waiting for a pullback to the lower Bollinger Band.
* **For Options**: It uses `BsmCalculatorDomainService`. If a user says "Buy Nifty Calls" but the implied volatility is severely inflated above fair value, it recommends a limit order closer to the Black-Scholes theoretical price.

### B. The Order Execution Layer (`domains/trading/application/order_service.py`)
This is the `OrderManagementService`. It is the bridge between the UI and the 021 Trade API.
* **`stage_order_proposal()`**: It takes the AI's recommendation and saves it in a `PENDING_APPROVAL` state, returning a `proposal_id`.
* **`execute_approved_order()`**: When the UI sends the confirmation, this method fires the payload to the 021 Trade Exchange via `Zero21TradeClient`. If the trade was a "Golden Zone" trade, it sends a Limit Order (`RL`) so the exchange holds it until the price hits.

---

## 3. What Needs to be Built Next? (The "To-Do" List)

The backend and frontend teams need to wire up the following endpoints and UI components:

### Backend Tasks (FastAPI API Layer)
You need to expose the core domain services over HTTP in `app/api/`.

1. **`POST /api/chat`**
   * **Input**: User's natural language string (e.g., "Buy 50 reliance shares at best price").
   * **Action**: Pass this to the LLM. The LLM function-calls and returns a `TradeIntent`. Pass the `TradeIntent` into `CopilotReasoningEngine.evaluate_intent()`. Then pass that output to `OrderManagementService.stage_order_proposal()`.
   * **Output**: Return the `ReasoningOutput` JSON and the `proposal_id` to the frontend.

2. **`POST /api/orders/{proposal_id}/confirm`**
   * **Action**: Calls `OrderManagementService.execute_approved_order(proposal_id)`.
   * **Output**: Success status and exchange Order ID.

### Frontend Tasks (Next.js / React)
The UI needs to gracefully handle the staged proposal.

1. **The Chat Interface**
   * Send the user's message to `POST /api/chat`.
   * Render the chatbot's text response.
   
2. **The Golden Zone Confirmation Modal (Crucial)**
   * When the chat API returns a `ReasoningOutput`, render a rich UI card in the chat.
   * **Display Data**: 
     * Show the `human_readable_summary` (e.g., "TCS is currently overbought. We recommend a limit order in the Golden Zone between ₹3,800 - ₹3,820").
     * Show the Limit Price being proposed.
   * **Buttons**: 
     * `[Confirm Trade]`: Calls `POST /api/orders/{proposal_id}/confirm`.
     * `[Reject/Cancel]`: Discards the proposal.

3. **Standing Instructions / Orders Dashboard**
   * Build a page to view open Limit Orders. Since Golden Zone trades are sent as `RL` (Regular Limit) orders to the 021 Trade API, they will show up as pending limit orders in the user's brokerage account until the optimal price is hit.

---

## 4. Example Payload Flow

**1. LLM Outputs to Reasoning Engine:**
```json
{
  "action": "BUY",
  "symbol": "RELIANCE",
  "quantity": 50,
  "instrument_type": "EQUITY"
}
```

**2. Reasoning Engine Outputs to UI (via API):**
```json
{
  "decision": "WAIT_FOR_ZONE",
  "golden_zone": {
    "price_low": 2800.0,
    "price_high": 2820.0,
    "technical_justification": "Lower Bollinger Band support at 2810."
  },
  "human_readable_summary": "Reliance is slightly overbought right now. Recommending a limit order in the Golden Zone.",
  "proposed_order_payload": {
    "exchange": "NSE",
    "qty": 50,
    "price": 282000, 
    "book": "RL",
    "product": "INTRADAY"
  }
}
```
*Note: The price is converted to paise (`282000`) for the 021 Trade API!*
