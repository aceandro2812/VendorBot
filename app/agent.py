from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from google.adk.agents.context import Context
from google.adk.apps.app import App
from google.adk.events.event import Event
from google.adk.workflow import Edge, Workflow, node, START
from google.adk.agents.llm_agent import LlmAgent
from google.adk.workflow._function_node import RequestInput

# Import config and mock tools
from app.config import llm_model, BUDGET_PREMIUM_THRESHOLD, MAX_NEGOTIATION_TURNS
from app.tools import (
    get_sku_buffer_health,
    get_supplier_meta,
    read_contract_pdf,
    scrape_supplier_marketplace,
    send_vendor_negotiation_email,
    log_slack_escalation,
    update_active_po,
    sanitize_text
)

# ==========================================
# Pydantic Schemas for Agent Outputs
# ==========================================

class LegalAnalysis(BaseModel):
    supplier_name: str = Field(..., description="The name of the supplier extracted from the SLA contract.")
    liquidated_damages_per_day: float = Field(..., description="Liquidated damages per day in USD.")
    total_penalty: float = Field(..., description="Calculated total penalty in USD for the delayed days.")
    force_majeure_applies: bool = Field(..., description="True if Force Majeure applies to this disruption, False otherwise.")
    reasoning: str = Field(..., description="Brief legal reasoning based on the SLA contract clauses.")

class SourcingOption(BaseModel):
    vendor: str = Field(..., description="Vendor name.")
    price: float = Field(..., description="Unit price.")
    avail: int = Field(..., description="Quantity available.")
    delivery_days: int = Field(..., description="Delivery lead time in days.")

class SourcingAnalysis(BaseModel):
    options: List[SourcingOption] = Field(..., description="All available options found in the B2B marketplace.")
    best_option: Optional[SourcingOption] = Field(None, description="Recommended best alternative sourcing option.")
    price_premium_percent: float = Field(..., description="Percentage unit price premium compared to the standard supplier's price. Example: if standard is $100 and best spot is $105, premium is 5.0.")

class NegotiationState(BaseModel):
    email_drafted: str = Field(..., description="The professional B2B email proposal drafted for the vendor.")
    vendor_email: str = Field(..., description="The vendor sales contact email.")
    status: str = Field(..., description="Status (e.g. 'DRAFTED', 'EMAIL_SENT', 'RESOLVED').")

# ==========================================
# Deterministic Python Nodes & Gates
# ==========================================

def get_field(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        val = obj[key]
        if val is not None:
            return val
    except Exception:
        pass
    return getattr(obj, key, default)

@node
def disruption_detector_node(ctx: Context, node_input: Any):
    """
    Entrypoint: Ingests webhook disruption event and checks ERP health buffers.
    Expected node_input: {"sku": "SKU-404X", "factory_code": "FAC-12", "delayed_days": 5}
    """
    import json
    from google.genai import types

    parsed_input = {}
    if isinstance(node_input, dict):
        parsed_input = node_input
    elif isinstance(node_input, types.Content):
        parts_text = "".join([part.text for part in node_input.parts if part.text is not None])
        try:
            parsed_input = json.loads(parts_text)
        except json.JSONDecodeError:
            pass
    elif isinstance(node_input, str):
        try:
            parsed_input = json.loads(node_input)
        except json.JSONDecodeError:
            pass

    sku = parsed_input.get("sku", "SKU-404X")
    delayed_days = parsed_input.get("delayed_days", 3)
    factory_code = parsed_input.get("factory_code", "FAC-DEFAULT")
    model_name = parsed_input.get("model_name", "gemini-2.5-flash")
    
    # Query ERP Inventory buffer
    erp_health_json = get_sku_buffer_health(sku)
    
    # Save parameters and health status into graph Context state
    ctx.state["sku"] = sku
    ctx.state["delayed_days"] = delayed_days
    ctx.state["factory_code"] = factory_code
    ctx.state["selected_model"] = model_name
    ctx.state["erp_health"] = erp_health_json
    ctx.state["latest_vendor_reply"] = ""
    
    # Map SKU to original supplier name and standard unit price for SLA contract lookup
    sku_upper = sku.strip().upper() if isinstance(sku, str) else str(sku).strip().upper()
    if sku_upper == "SKU-404X":
        ctx.state["supplier_name"] = "Pacific Semiconductors"
        ctx.state["standard_unit_price"] = 100.0
    elif sku_upper == "SKU-777Z":
        ctx.state["supplier_name"] = "Titan Supplies"
        ctx.state["standard_unit_price"] = 400.0
    elif sku_upper == "SKU-100Y":
        ctx.state["supplier_name"] = "Steel Housing Supplier"
        ctx.state["standard_unit_price"] = 200.0
    else:
        ctx.state["supplier_name"] = "Default Supplier"
        ctx.state["standard_unit_price"] = 100.0
    
    yield Event(data=ctx.state)

@node
def security_screen_node(ctx: Context, node_input: Any):
    """
    Pre-LLM Security Checkpoint:
    1. Redacts PII (SSNs and CCs) from inputs.
    2. Detects prompt injection attempts and routes them straight to manual queue, bypassing LLMs.
    """
    import re
    from app.tools import sanitize_text, salt_contract_data
    
    # 1. Scrub PII from state fields (e.g. factory_code)
    factory_code = get_field(ctx.state, "factory_code", "")
    sku = get_field(ctx.state, "sku", "")
    
    print(f"\n[DEBUG SECURITY] raw factory_code: {factory_code!r}, raw sku: {sku!r}")
    
    # Redact SSNs in factory_code and sku
    ssn_pattern = r"\b\d{3}-\d{2}-\d{4}\b"
    clean_factory = re.sub(ssn_pattern, "[REDACTED_SSN]", str(factory_code))
    clean_sku = re.sub(ssn_pattern, "[REDACTED_SSN]", str(sku))
    
    print(f"[DEBUG SECURITY] clean factory_code: {clean_factory!r}, clean sku: {clean_sku!r}")
    
    ctx.state["factory_code"] = clean_factory
    ctx.state["sku"] = clean_sku
    
    # 2. Check for Prompt Injection in any inputs
    injection_patterns = [
        "ignore previous instructions",
        "ignore all previous",
        "system override",
        "developer mode",
        "bypass all rules",
        "auto-approve this"
    ]
    
    combined_inputs = f"{sku} {factory_code}".lower()
    has_injection = any(p in combined_inputs for p in injection_patterns)
    
    if has_injection:
        ctx.state["security_alert"] = True
        ctx.state["security_reason"] = "Prompt injection attempt detected in webhook payload."
        yield Event(data=ctx.state, route="escalated")
    else:
        yield Event(data=ctx.state, route="clean")

@node(rerun_on_resume=True)
def legal_approval_gate(ctx: Context, node_input: Any):
    """
    HITL approval gate for SLA breached damages claim.
    """
    # Check if we have received resume input for legal approval
    resume_data = ctx.resume_inputs.get("legal_approval")
    
    if resume_data is None:
        # Check if already approved in state
        if ctx.state.get("legal_approved") is not None:
            # We already have approval, route accordingly
            route = "approved" if ctx.state.get("legal_approved") else "rejected"
            yield Event(data=ctx.state, route=route)
            return
            
        # First execution, need to yield a RequestInput to pause the workflow
        legal_data = ctx.state.get("legal_analysis", {})
        total_penalty = legal_data.get("total_penalty", 0.0)
        
        yield RequestInput(
            interrupt_id="legal_approval",
            message=f"Legal SLA Audit finished. Calculated liquid damages penalty: ${total_penalty:.2f}. Approve breach claim?",
            payload={
                "calculated_penalty": total_penalty,
                "supplier_name": legal_data.get("supplier_name", "Unknown"),
                "reasoning": legal_data.get("reasoning", "")
            }
        )
    else:
        # Workflow resumed with human input
        approved = resume_data.get("approved", False)
        override_val = resume_data.get("override_damages")
        
        if override_val is None or override_val == "":
            override_damages = ctx.state.get("legal_analysis", {}).get("total_penalty", 0.0)
        else:
            try:
                override_damages = float(override_val)
            except (ValueError, TypeError):
                override_damages = ctx.state.get("legal_analysis", {}).get("total_penalty", 0.0)
        
        ctx.state["legal_approved"] = approved
        ctx.state["approved_damages"] = override_damages
        
        route = "approved" if approved else "rejected"
        yield Event(data=ctx.state, route=route)

@node(rerun_on_resume=True)
def procurement_agent(ctx: Context, node_input: Any):
    """
    Reconciles alternative vendor prices against internal company constraints.
    """
    sourcing_data = ctx.state.get("sourcing_analysis")
    premium_percent = get_field(sourcing_data, "price_premium_percent", 0.0)
    best_opt = get_field(sourcing_data, "best_option", None)
    
    # Check if best_opt is None or empty
    if not best_opt:
        ctx.state["procurement_approved"] = False
        ctx.state["rejection_reason"] = "No alternative sourcing option available."
        yield Event(data=ctx.state, route="rejected")
        return
        
    # Route automatically if premium <= 10%
    if premium_percent <= 10.0:
        ctx.state["procurement_approved"] = True
        ctx.state["final_sourcing_option"] = best_opt
        yield Event(data=ctx.state, route="approved")
        return
        
    # Exceeds threshold, check for resume input
    resume_data = ctx.resume_inputs.get("budget_approval")
    
    if resume_data is None:
        if ctx.state.get("procurement_approved") is not None:
            route = "approved" if ctx.state.get("procurement_approved") else "rejected"
            yield Event(data=ctx.state, route=route)
            return
            
        # Log simulated Slack escalation alert
        best_opt_vendor = get_field(best_opt, "vendor", "Unknown")
        best_opt_price = get_field(best_opt, "price", 0.0)
        alert_msg = f"ALERT: Premium for SKU {ctx.state.get('sku')} is {premium_percent:.1f}%, exceeding 10% ceiling. Vendor: {best_opt_vendor} (${best_opt_price:.2f}/unit)."
        log_slack_escalation("#finance-approvals", alert_msg)
        
        # Pause execution
        yield RequestInput(
            interrupt_id="budget_approval",
            message=f"Spot price premium is {premium_percent:.1f}%, exceeding 10% limit. Require manual override.",
            payload={
                "premium_percent": premium_percent,
                "best_option": best_opt,
                "standard_price": ctx.state.get("standard_unit_price")
            }
        )
    else:
        # Resumed
        approved = resume_data.get("approved", False)
        ctx.state["procurement_approved"] = approved
        ctx.state["final_sourcing_option"] = best_opt
        
        route = "approved" if approved else "rejected"
        yield Event(data=ctx.state, route=route)

@node(rerun_on_resume=True)
def negotiation_wait_gate(ctx: Context, node_input: Any):
    """
    Asynchronous state management for vendor email correspondence.
    Loops negotiation or escalates if limits are breached.
    """
    # Track iteration turn counter
    turns = ctx.state.get("negotiation_turns", 0)
    
    # Check for inbound vendor response from FastAPI webhook
    vendor_reply = ctx.resume_inputs.get("vendor_reply")
    
    if vendor_reply is None:
        # Check if already resolved
        if ctx.state.get("negotiation_resolved"):
            yield Event(data=ctx.state, route="resolved")
            return
        if turns >= MAX_NEGOTIATION_TURNS:
            yield Event(data=ctx.state, route="escalated")
            return
            
        # First execution or next turn email was just dispatched, suspend and wait
        neg_state = ctx.state.get("negotiation_state")
        neg_email = get_field(neg_state, "vendor_email", "")
        neg_draft = get_field(neg_state, "email_drafted", "")
        yield RequestInput(
            interrupt_id="vendor_reply",
            message=f"Procurement email dispatched to {neg_email}. Awaiting response.",
            payload={
                "turns_completed": turns,
                "latest_email_sent": neg_draft
            }
        )
    else:
        # Vendor reply received!
        turns += 1
        ctx.state["negotiation_turns"] = turns
        
        reply_text = vendor_reply.get("reply_body", "")
        # Sanitize vendor replies to prevent indirect prompt injections
        clean_reply = sanitize_text(reply_text)
        
        if "negotiation_thread" not in ctx.state:
            ctx.state["negotiation_thread"] = []
            
        ctx.state["negotiation_thread"].append({
            "sender": "Vendor Sales Representative",
            "message": clean_reply
        })
        
        # Determine if terms are resolved (simple logic or LLM can evaluate. For prototype we check keywords)
        resolved = any(keyword in clean_reply.lower() for keyword in ["accept", "agree", "confirm", "deal", "yes"])
        
        if resolved:
            ctx.state["negotiation_resolved"] = True
            # Update contract details in state with final agreed price
            # Extrapolate final agreed price (assume a 5% discount from spot or final vendor offered price)
            final_option = ctx.state.get("final_sourcing_option")
            final_price = get_field(final_option, "price", 100.0)
            # Simulate a negotiation discount if they agreed
            ctx.state["negotiation_final_price"] = final_price * 0.95
            yield Event(data=ctx.state, route="resolved")
        elif turns >= MAX_NEGOTIATION_TURNS:
            ctx.state["negotiation_escalated"] = True
            yield Event(data=ctx.state, route="escalated")
        else:
            # Continue the negotiation conversation loop
            ctx.state["latest_vendor_reply"] = clean_reply
            yield Event(data=ctx.state, route="continue_negotiation")

@node(rerun_on_resume=True)
def contract_signing_node(ctx: Context, node_input: Any):
    """
    Final validation gate: holds PO in PENDING_PO_SIGNATURE buffer state.
    """
    resume_data = ctx.resume_inputs.get("po_signature")
    
    sku = ctx.state.get("sku", "SKU-404X")
    qty = 100  # Default order quantity
    final_option = ctx.state.get("final_sourcing_option")
    default_price = get_field(final_option, "price", 100.0)
    final_price = ctx.state.get("negotiation_final_price", default_price)
    po_total = qty * final_price
    
    if resume_data is None:
        if ctx.state.get("po_signed"):
            yield Event(data=ctx.state)
            return
            
        yield RequestInput(
            interrupt_id="po_signature",
            message=f"Purchase Order ready for final signature. SKU: {sku}, Qty: {qty}, Total: ${po_total:.2f}.",
            payload={
                "po_id": f"PO-{sku}-AUTO",
                "sku": sku,
                "quantity": qty,
                "unit_price": final_price,
                "total_cost": po_total
            }
        )
    else:
        # Operations Director signed
        signed = resume_data.get("signed", False)
        ctx.state["po_signed"] = signed
        
        if signed:
            po_id = f"PO-{sku}-AUTO"
            # Call ERP connector to commit database record
            db_res = update_active_po(po_id, sku, qty, final_price, "SIGNED")
            ctx.state["po_database_result"] = db_res
            
        yield Event(data=ctx.state)

@node
def fetch_contract_node(ctx: Context, node_input: Any):
    """
    Deterministic pre-LLM step: fetch and scrub SLA contract text before legal audit.
    Avoids multi-turn tool calling in the LLM, which breaks Gemini history after HITL resume.
    """
    supplier_name = ctx.state.get("supplier_name", "Default Supplier")
    ctx.state["contract_text"] = read_contract_pdf(supplier_name)
    yield Event(data=ctx.state)

@node
def fetch_marketplace_node(ctx: Context, node_input: Any):
    """
    Deterministic pre-LLM step: scrape marketplace data before sourcing analysis.
    """
    sku = ctx.state.get("sku", "SKU-404X")
    ctx.state["marketplace_data"] = scrape_supplier_marketplace(sku)
    yield Event(data=ctx.state)

@node
def prepare_negotiation_context_node(ctx: Context, node_input: Any):
    """
    Deterministic pre-LLM step: resolve vendor contact metadata before drafting email.
    """
    import json

    final_option = ctx.state.get("final_sourcing_option")
    vendor_name = get_field(final_option, "vendor", "Unknown Vendor")
    meta = json.loads(get_supplier_meta(vendor_name))
    ctx.state["vendor_name"] = vendor_name
    ctx.state["vendor_email"] = meta.get("contact_email", "")
    yield Event(data=ctx.state)

@node
def dispatch_negotiation_email_node(ctx: Context, node_input: Any):
    """
    Deterministic post-LLM step: send the drafted negotiation email.
    """
    neg_state = ctx.state.get("negotiation_state", {})
    email_body = get_field(neg_state, "email_drafted", "")
    vendor_email = ctx.state.get("vendor_email", get_field(neg_state, "vendor_email", ""))
    session_id = ctx.state.get("session_id", "default")

    send_vendor_negotiation_email(session_id, vendor_email, email_body)

    updated_state = {
        "email_drafted": email_body,
        "vendor_email": vendor_email,
        "status": "EMAIL_SENT",
    }
    ctx.state["negotiation_state"] = updated_state
    yield Event(data=ctx.state)

@node
def manual_ticket_queue(ctx: Context, node_input: Any):
    """
    Escalates the contract breach or spot sourcing dispute to a human buyer's manual ticket queue.
    """
    ctx.state["manual_queue_escalated"] = True
    ctx.state["ticket_id"] = f"TICKET-BREACH-{ctx.state.get('sku')}"
    yield Event(data=ctx.state)

# ==========================================
# LLM Agents (Task Mode / Singleton Mode)
# ==========================================

def log_active_model(callback_context, llm_request):
    import logging
    logger = logging.getLogger("fast_api_app")
    logger.info(f"[LLM ACTIVE EXECUTION] Calling model ID: {llm_request.model}")
    return None

legal_sla_agent = LlmAgent(
    name="legal_sla_agent",
    model=llm_model,
    instruction="""
You are an expert corporate legal auditor.

CONTEXT (injected from session state):
- Supplier to audit: {supplier_name}
- Delay duration: {delayed_days} days
- SKU involved: {sku}
- SLA contract text (pre-fetched): {contract_text}

Your job:
1. Read the contract text carefully and extract the liquidated damages penalty per day.
2. Calculate total_penalty = liquidated_damages_per_day × {delayed_days}.
3. Determine if Force Majeure exclusions apply (Acts of God, war, riot, government embargo).
4. Write a brief legal reasoning string.

MANDATORY STRUCTURAL RULE:
Your response must be a raw JSON object containing exactly these fields:
- "supplier_name": String (name of the supplier from context)
- "liquidated_damages_per_day": Float (e.g. 5000.0)
- "total_penalty": Float (liquidated_damages_per_day * delayed_days)
- "force_majeure_applies": Boolean (true or false)
- "reasoning": String (explanation)

OUTPUT RULE: Output ONLY raw valid JSON conforming to the fields above. No conversational text.
    """,
    output_key="legal_analysis",
    output_schema=LegalAnalysis,
    before_model_callback=log_active_model,
)

sourcing_agent = LlmAgent(
    name="sourcing_agent",
    model=llm_model,
    instruction="""
You are an AI spot-sourcing agent.

CONTEXT (injected from session state):
- SKU to source: {sku}
- Standard unit price on contract: ${standard_unit_price}
- Marketplace data (pre-fetched): {marketplace_data}

Your job:
1. Parse the marketplace table of vendors, prices, availability, and delivery lead times.
2. For each vendor, compute price_premium_percent = ((vendor_price - {standard_unit_price}) / {standard_unit_price}) * 100.
3. Select the best_option as the vendor with the lowest price that still has stock.
4. Set price_premium_percent on the best_option's price relative to {standard_unit_price}.

MANDATORY STRUCTURAL RULE:
Your response must be a raw JSON object containing exactly these fields:
- "options": List of objects, each containing:
    * "vendor": String
    * "price": Float
    * "avail": Integer
    * "delivery_days": Integer
- "best_option": Object (or null if no options found) matching the option schema above
- "price_premium_percent": Float (premium relative to standard price)

OUTPUT RULE: Output ONLY raw valid JSON conforming to the fields above. No conversational text.
If the marketplace returns no results, output options=[], best_option=null, price_premium_percent=0.0.
    """,
    output_key="sourcing_analysis",
    output_schema=SourcingAnalysis,
    before_model_callback=log_active_model,
)

negotiation_agent = LlmAgent(
    name="negotiation_agent",
    model=llm_model,
    instruction="""
You are a senior B2B Procurement Negotiator.

CONTEXT (injected from session state):
- SKU: {sku}
- Vendor name: {vendor_name}
- Vendor email: {vendor_email}
- Approved SLA damages leverage: ${approved_damages}
- Delay duration: {delayed_days} days
- Latest vendor reply (if any): {latest_vendor_reply}

Your job:
1. Draft a professional procurement email requesting a discounted price or fast delivery, using the ${{approved_damages}} SLA damages as leverage.
2. If latest_vendor_reply exists in state, acknowledge and respond to it firmly but politely.

MANDATORY STRUCTURAL RULE:
Your response must be a raw JSON object containing exactly these fields:
- "email_drafted": String (the email text)
- "vendor_email": String (use {vendor_email} from context)
- "status": String (must be "DRAFTED")

OUTPUT RULE: Output ONLY raw valid JSON conforming to the fields above. No conversational text.
    """,
    output_key="negotiation_state",
    output_schema=NegotiationState,
    before_model_callback=log_active_model,
)


# ==========================================
# ADK 2.0 Graph Topology Configuration
# ==========================================

root_workflow = Workflow(
    name="supply_chain_negotiator_workflow",
    edges=[
        # 1. Start -> Ingest -> Security Screen -> Legal Auditor (if clean) or Manual Queue (if escalated)
        Edge(from_node=START, to_node=disruption_detector_node),
        Edge(from_node=disruption_detector_node, to_node=security_screen_node),
        Edge(from_node=security_screen_node, to_node=fetch_contract_node, route="clean"),
        Edge(from_node=security_screen_node, to_node=manual_ticket_queue, route="escalated"),
        Edge(from_node=fetch_contract_node, to_node=legal_sla_agent),
        Edge(from_node=legal_sla_agent, to_node=legal_approval_gate),
        
        # 2. Legal Approval Branching
        Edge(from_node=legal_approval_gate, to_node=fetch_marketplace_node, route="approved"),
        Edge(from_node=legal_approval_gate, to_node=manual_ticket_queue, route="rejected"),
        Edge(from_node=fetch_marketplace_node, to_node=sourcing_agent),
        
        # 3. Sourcing -> Procurement Constraints Check
        Edge(from_node=sourcing_agent, to_node=procurement_agent),
        
        # 4. Procurement Approval Branching
        Edge(from_node=procurement_agent, to_node=prepare_negotiation_context_node, route="approved"),
        Edge(from_node=procurement_agent, to_node=manual_ticket_queue, route="rejected"),
        Edge(from_node=prepare_negotiation_context_node, to_node=negotiation_agent),
        
        # 5. Negotiation Conversation Loop
        Edge(from_node=negotiation_agent, to_node=dispatch_negotiation_email_node),
        Edge(from_node=dispatch_negotiation_email_node, to_node=negotiation_wait_gate),
        Edge(from_node=negotiation_wait_gate, to_node=negotiation_agent, route="continue_negotiation"),
        
        # 6. Negotiation Resolution Branches
        Edge(from_node=negotiation_wait_gate, to_node=contract_signing_node, route="resolved"),
        Edge(from_node=negotiation_wait_gate, to_node=manual_ticket_queue, route="escalated"),
    ],
)

app = App(name="supply-chain-negotiator", root_agent=root_workflow)
