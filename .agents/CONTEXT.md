# Local Project Context & Secure Coding Standards

## 1. Paved Roads & Security Controls
- Tool Parameter Validation: Every tool exposed to an agent must use an explicit Pydantic schema for type validation; do not pass un-vetted primitive strings or raw dictionary payloads directly to LLMs.
- Indirect Prompt Injection Defense: Web scraped outputs, incoming emails, and untrusted vendor communication strings must pass through a sanitization function to strip adversarial markdown injection vectors before hitting agent prompt nodes.
- PII & Metric Salting: Before processing vendor contract PDFs, replace sensitive corporate entity identifiers and internal financial targets with temporary contextual placeholder tokens.
