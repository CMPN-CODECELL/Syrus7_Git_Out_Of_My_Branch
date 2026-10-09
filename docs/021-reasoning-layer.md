# AI Trading Copilot: Reasoning Layer & 021 Trade Integration

## 1. Overview
As part of the AI Trading Copilot, we have implemented a **Derivatives RAG (Retrieval-Augmented Generation) Reasoning Layer**. 
Instead of relying entirely on the LLM to make trading decisions, the LLM is restricted strictly to **Intent Extraction**. Once the intent is extracted, it is passed to our deterministic mathematical reasoning layer, which uses existing derivatives and technical analysis code to recommend the optimal action and "Golden Zone" for execution.

## 2. Architecture & Components

We created two new bounded contexts (domains) to keep the architecture clean and strictly isolated:

### A. The Copilot Domain (`domains/copilot`)
This domain handles the AI reasoning logic.

* **`domains/copilot/domain/entities.py`**:
  * Defines the structured `TradeIntent` that the LLM extracts (action, symbol, qty, instrument type).
  * Defines the `GoldenZone` which represents the optimal price range to execute a trade.
  * Defines the `ReasoningOutput` which contains the final decision (`EXECUTE_NOW`, `WAIT_FOR_ZONE`, `REJECT`), justification, and the structured order payload.

* **`domains/copilot/application/reasoning_layer.py` (`CopilotReasoningEngine`)**:
  * Acts as the core of our RAG system.
  * **For Equities**: Uses `TechnicalIndicatorsEngine` (RSI, Bollinger Bands) to find if the stock is overbought/oversold. If it's a bad time to buy, it calculates a `GoldenZone` (e.g., lower Bollinger Band) and recommends a limit order.
  * **For Options**: Uses `BsmCalculatorDomainService` to calculate theoretical prices and Greeks. If the market price of the option is inflated compared to the theoretical Black-Scholes price, it recommends a `GoldenZone` for a limit order at fair value.

### B. The Trading Domain (`domains/trading`)
This domain handles the actual paper execution via the 021 Trade API.

* **`domains/trading/infrastructure/outbound/trade_client.py` (`Zero21TradeClient`)**:
  * An asynchronous HTTP client wrapper for the `021 Trade API`.
  * Handles authentication (`/auth/token`) and order placement (`POST /orders`).
  
* **`domains/trading/application/order_service.py` (`OrderManagementService`)**:
  * Enforces the **Human-in-the-Loop** safety architecture.
  * `stage_order_proposal()`: Takes the output from the Reasoning Engine and stages it with a `PENDING_APPROVAL` status. The UI will show this to the user.
  * `execute_approved_order()`: Only called when the user explicitly clicks "Confirm". It sends the exact proposed payload to the 021 Trade API.
  * **Auto-Execution (Golden Zone)**: If the Reasoning Layer recommended a Golden Zone, the order is sent to the 021 API with `book: "RL"` (Regular Limit). The exchange holds the order ready and auto-executes it only when the optimal price is hit, satisfying the requirement to keep orders ready for the right time.

## 3. Workflow Summary

1. **User Types**: "Buy Nifty call options"
2. **LLM Extracts**: `{action: BUY, symbol: NIFTY, instrument: OPTION}`
3. **Reasoning Layer**: 
   - Queries `BsmCalculatorDomainService`
   - Sees market price is 20% higher than theoretical fair value.
   - Outputs: `WAIT_FOR_ZONE`, Limit Order payload at fair value.
4. **Order Service**:
   - Stages the order as `PENDING_APPROVAL`.
5. **UI Modal**:
   - Shows user: "Options are currently overpriced (high IV). We recommend placing a limit order at ₹150 (Fair Value)."
6. **User Action**:
   - Clicks "Confirm".
7. **Execution**:
   - `OrderManagementService` sends the Limit Order to the 021 Trade API.
   - The exchange executes it automatically when the price drops to the Golden Zone.
