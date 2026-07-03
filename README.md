# 🤖 VendorBot — Multi-Agent SLA Enforcement & Spot Sourcing System

> **Kaggle 5-Day Gen AI Agents Intensive — Capstone Project**  
> Built with **ADK 2.0** · **FastAPI** · **React + Vite** · **Google Gemini Free Tier** · **MCP**

VendorBot is an enterprise-grade, event-driven **multi-agent graph workflow** that autonomously detects supply chain disruptions, enforces SLA contract penalties, sources alternative vendors, negotiates deals via email, and routes high-stakes decisions through Human-In-The-Loop (HITL) approval gates — all powered by Google's ADK 2.0 agentic framework.

---

## ✨ Features

| Agent / Node | Role |
|---|---|
| `disruption_detector_node` | Ingests SKU disruption webhooks, checks ERP inventory buffers, maps suppliers |
| `security_screen_node` | Pre-LLM PII scrubbing & prompt injection quarantine |
| `legal_sla_agent` | LLM parses contract SLA → calculates liquidated damages → HITL approval gate |
| `sourcing_agent` | LLM scrapes B2B spot catalog via MCP → identifies best alternative vendor |
| `procurement_agent` | Auto-approves ≤10% premium · escalates >10% to Finance via Slack-style alert |
| `negotiation_agent` | Async LLM email negotiator · loops until vendor agrees or escalates |
| `contract_signing_node` | Final PO signing gate with digital signature & ERP database commit |
| `manual_ticket_queue` | Fallback escalation for unknown SKUs, injections, or failed sourcing |

### Key Capabilities
- 🛡️ **Pre-LLM Security**: SSN/PII redaction + prompt injection detection before any LLM call
- 🔌 **Custom MCP Server**: Stdio FastMCP server exposing contract, inventory & catalog tools
- 🎛️ **Dynamic Model Selection**: Switch between 8 Gemini Free Tier models at runtime from the UI
- 📊 **Real-time Audit Trail**: Terminal-style pipeline event log in the React dashboard
- 🔁 **HITL Gates**: Legal approval, budget override, vendor reply simulation, PO signature
- 📈 **LLM-as-Judge Evaluation**: 5.0/5.0 on Routing Correctness & Security Containment

---

## 🏗️ Architecture

```
Webhook Trigger
      │
      ▼
disruption_detector_node  ──→  security_screen_node
                                      │
                         ┌────────────┴────────────┐
                     (clean)                  (escalated)
                         │                         │
                         ▼                         ▼
               legal_sla_agent            manual_ticket_queue
                         │
               legal_approval_gate (HITL)
                         │
                         ▼
               sourcing_agent (MCP)
                         │
               procurement_agent
                         │
               ┌─────────┴──────────┐
           (≤10%)               (>10%)
               │                   │
               ▼            budget_approval (HITL)
       negotiation_agent
               │
       negotiation_wait_gate (HITL loop)
               │
       contract_signing_node (HITL)
               │
       ERP Database Commit ✓
```

---

## 🧰 Tech Stack

| Layer | Tool |
|---|---|
| Agent Framework | ADK 2.0 (`google-adk>=2.0.0a0`) |
| Model Provider | Google Gemini (AI Studio Free Tier) |
| External Tools | Custom FastMCP stdio server |
| Backend API | FastAPI + Uvicorn |
| Frontend | React 18 + Vite + Vanilla CSS (glassmorphic dark UI) |
| Package Manager | `uv` |
| Security | Semgrep + pre-commit hooks + `.agents/hooks.json` |
| Tests | pytest + LLM-as-Judge eval (`grade_traces.py`) |

---

## 🚀 Getting Started

### Prerequisites
- Python 3.11+
- `uv` package manager (`pip install uv`)
- Node.js 18+

### 1. Install dependencies

```bash
cd supply-chain-negotiator
uv sync
cd frontend && npm install && cd ..
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and add your Gemini API key:
# GEMINI_API_KEY="your-key-from-aistudio.google.com"
```

### 3. Start the backend

```bash
uv run uvicorn app.fast_api_app:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Start the frontend

```bash
cd frontend
npm run dev
# → http://localhost:5173
```

### 5. (Optional) ADK Playground

```bash
uv run adk web
```

---

## 🧪 Testing & Evaluation

```bash
# Run unit tests (5 routing + security tests)
uv run pytest

# Generate synthetic evaluation traces
uv run python tests/eval/generate_traces.py

# Grade traces with LLM-as-Judge
uv run python tests/eval/grade_traces.py
```

**Target scores:** Routing Correctness **5.0/5.0** · Security Containment **5.0/5.0**

---

## 🔐 Security Design

- **PII Scrubbing**: SSNs redacted with `[REDACTED_SSN]` before any LLM call
- **Prompt Injection Defense**: Known injection patterns quarantine the session instantly
- **Metric Salting**: Sensitive financial targets replaced with random tokens in contract text
- **Indirect Injection Defense**: Vendor email replies sanitized before re-entering agent context
- **Model Allowlist**: Only approved Gemini Free Tier model IDs accepted at the API layer
- **No Hardcoded Secrets**: All keys loaded from `.env` at runtime

---

## 🤖 Supported AI Models (Free Tier)

| Model | Badge | Best For |
|---|---|---|
| `gemini-3.5-flash` | NEW | Current standard, newest gen |
| `gemini-3.1-flash-lite` | NEW LITE | Ultra-low latency |
| `gemini-2.5-flash` | DEFAULT | Best price/performance |
| `gemini-2.5-pro` | PRECISION | Most capable reasoning |
| `gemini-2.5-flash-lite` | FAST | High-volume tasks |
| `gemini-1.5-flash` | LEGACY | Stable legacy |
| `gemini-1.5-flash-8b` | MINI | Smallest & cheapest |
| `gemini-1.5-pro` | LEGACY-PRO | Legacy high-capability |

---

## 📁 Project Structure

```
vendorbot/
├── app/
│   ├── agent.py          # ADK 2.0 Workflow graph, nodes & LlmAgents
│   ├── config.py         # Model & env-driven settings
│   ├── fast_api_app.py   # FastAPI backend + session management
│   ├── mcp_server.py     # Custom FastMCP stdio server (contracts, catalog, inventory)
│   └── tools.py          # Deterministic Python tools
├── frontend/             # React + Vite dashboard
├── tests/
│   ├── test_routing.py   # pytest security & routing unit tests
│   └── eval/             # Synthetic dataset, trace generator, LLM-as-Judge grader
├── .agents/              # CONTEXT.md, hooks.json, pre-LLM guardrails
├── .semgrep/rules.yaml   # Secret scanning rules
├── threat_model.md       # STRIDE threat model
├── pyproject.toml
├── Makefile
└── README.md
```

---

## 📜 License

MIT — built for the Kaggle 5-Day Gen AI Agents Intensive Capstone.
