import re
import json
from typing import Dict, Any, List
from pydantic import BaseModel, Field

# ==========================================
# Security Sanitizers & Salting Defense
# ==========================================

def sanitize_text(text: str) -> str:
    """
    Indirect Prompt Injection Defense:
    Strips markdown injection, script tags, and malicious redirect directives
    before text is parsed by LLM agents.
    """
    if not text:
        return ""
    # Strip HTML script blocks
    text = re.sub(r"<script.*?>.*?</script>", "", text, flags=re.IGNORECASE | re.DOTALL)
    # Strip dangerous HTML style tags
    text = re.sub(r"<style.*?>.*?</style>", "", text, flags=re.IGNORECASE | re.DOTALL)
    # Strip potential markdown link injection attempts e.g. [click](javascript:...)
    text = re.sub(r"\[.*?\]\(javascript:.*?\)", "[BLOCKED_JS_LINK]", text, flags=re.IGNORECASE)
    # Strip system override phrases
    injection_phrases = [
        "ignore previous instructions",
        "ignore all previous",
        "system override",
        "developer mode",
        "bypass all rules",
        "auto-approve this"
    ]
    for phrase in injection_phrases:
        text = re.sub(re.escape(phrase), "[REDACTED_PROMPT_INJECTION_ATTEMPT]", text, flags=re.IGNORECASE)
    return text

def salt_contract_data(text: str) -> str:
    """
    PII & Metric Salting:
    Replaces sensitive corporate names, SSNs, credit cards, and internal financial targets
    with temporary contextual placeholders.
    """
    if not text:
        return ""
    # Redact SSNs
    text = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]", text)
    # Redact Credit Cards
    text = re.sub(r"\b(?:\d[ -]*?){13,16}\b", "[REDACTED_CARD_NUMBER]", text)
    # Salt sensitive company names
    text = re.sub(r"\bAcme\s+Industrial\b", "[CLIENT_CORP_SALT_A]", text, flags=re.IGNORECASE)
    text = re.sub(r"\bTitan\s+Supplies\b", "[VENDOR_CORP_SALT_B]", text, flags=re.IGNORECASE)
    # Salt internal target thresholds
    text = re.sub(r"\btarget\s+margin\s+of\s+[\d\.]+\s*%", "target margin of [SALTED_TARGET_MARGIN]%", text, flags=re.IGNORECASE)
    return text

# ==========================================
# In-Memory Mock Databases & Persistence
# ==========================================

MOCK_INVENTORY_DB = {
    "SKU-404X": {"buffer_stock": 120, "daily_burn": 30, "days_left": 4, "name": "Microchip Controller A"},
    "SKU-100Y": {"buffer_stock": 500, "daily_burn": 10, "days_left": 50, "name": "Steel Housing B"},
    "SKU-777Z": {"buffer_stock": 10, "daily_burn": 5, "days_left": 2, "name": "Titanium Connector C"},
}

MOCK_SUPPLIERS_DB = {
    "SKU-404X": [
        {"vendor": "Pacific Semiconductors", "price": 105.00, "avail": 200, "delivery_days": 3},
        {"vendor": "Alt Tech Supply", "price": 115.00, "avail": 150, "delivery_days": 2},
        {"vendor": "Global Chip Distributors", "price": 130.00, "avail": 500, "delivery_days": 1},
    ],
    "SKU-777Z": [
        {"vendor": "Vertex Aerospace Parts", "price": 450.00, "avail": 50, "delivery_days": 4},
        {"vendor": "Nexus Sourcing", "price": 520.00, "avail": 10, "delivery_days": 1},
    ]
}

MOCK_CONTRACTS_DB = {
    "Pacific Semiconductors": """
CONTRACT FOR SUPPLY OF MICROCHIP CONTROLLER A
This Service Level Agreement (SLA) is between Acme Industrial (hereafter 'Buyer') and Pacific Semiconductors (hereafter 'Seller').
SECTION 4: DELAYS AND PENALTIES
For every day of delayed delivery of SKU-404X, Seller shall pay Buyer liquidated damages of $5,000 per day.
SECTION 5: FORCE MAJEURE
Neither party will be liable for performance delays due to Acts of God, war, riot, or governmental embargoes.
Buyer internal target margin of 18.5%.
Contract manager SSN: 000-12-3456.
    """,
    "Titan Supplies": """
CONTRACT FOR SUPPLY OF TITANIUM CONNECTORS
This Agreement is between Acme Industrial and Titan Supplies.
SECTION 3: PENALTIES
Delay in shipping SKU-777Z will result in penalty tiers:
- 1 to 3 days delay: $2,000 per day.
- More than 3 days delay: $6,000 per day.
SECTION 8: FORCE MAJEURE
Standard Force Majeure exclusions apply, excluding general labor strikes unless nation-wide.
    """
}

# Session logs and PO database
ACTIVE_POS = {}
SLACK_ESCALATIONS = []
VENDOR_EMAIL_THREADS = {}

# ==========================================
# Tool 1: erp_connector_mcp
# ==========================================

class SkuBufferInput(BaseModel):
    sku: str = Field(..., description="The stock keeping unit (SKU) code.")

def get_sku_buffer_health(sku: str) -> str:
    """
    Get SKU Buffer Health:
    Retrieves internal stock level, daily run-rate, and remaining exhaustion window.
    """
    sku_upper = sku.strip().upper()
    if sku_upper not in MOCK_INVENTORY_DB:
        return f"Error: SKU '{sku}' not found in ERP Inventory DB."
    data = MOCK_INVENTORY_DB[sku_upper]
    return json.dumps({
        "sku": sku_upper,
        "item_name": data["name"],
        "buffer_stock": data["buffer_stock"],
        "daily_burn_rate": data["daily_burn"],
        "estimated_exhaustion_days": data["days_left"],
        "health_status": "CRITICAL" if data["days_left"] <= 5 else "OK"
    })

class SupplierMetaInput(BaseModel):
    supplier_name: str = Field(..., description="The name of the vendor/supplier.")

def get_supplier_meta(supplier_name: str) -> str:
    """
    Get Supplier Metadata:
    Retrieves historical vendor performance rating and default contact information.
    """
    # Simple mock response
    return json.dumps({
        "supplier_name": supplier_name,
        "rating": "A+" if "Pacific" in supplier_name else "B",
        "preferred_status": True,
        "contact_email": f"sales@{supplier_name.lower().replace(' ', '')}.com"
    })

class UpdatePoInput(BaseModel):
    po_id: str = Field(..., description="The Purchase Order identifier.")
    sku: str = Field(..., description="The SKU code being ordered.")
    quantity: int = Field(..., description="Quantity of items being purchased.")
    unit_price: float = Field(..., description="Agreed unit price.")
    status: str = Field(..., description="PO Status (e.g., 'ISSUED', 'SIGNED').")

def update_active_po(po_id: str, sku: str, quantity: int, unit_price: float, status: str) -> str:
    """
    Update Active PO:
    Registers or updates a Purchase Order record in the central database.
    """
    ACTIVE_POS[po_id] = {
        "po_id": po_id,
        "sku": sku,
        "quantity": quantity,
        "unit_price": unit_price,
        "total_cost": quantity * unit_price,
        "status": status
    }
    return f"Success: Purchase Order {po_id} updated. Status: {status}."

# ==========================================
# Tool 2: b2b_web_scraper_mcp
# ==========================================

class ScrapeSupplierInput(BaseModel):
    sku: str = Field(..., description="The SKU code to search on B2B catalogs.")

def scrape_supplier_marketplace(sku: str) -> str:
    """
    Scrape Supplier Marketplace:
    Scrapes external B2B supplier sites to find alternative vendors, pricing, and availability.
    Applies security sanitization before returning.
    """
    sku_upper = sku.strip().upper()
    if sku_upper not in MOCK_SUPPLIERS_DB:
        return sanitize_text(f"No alternative suppliers found for SKU {sku}.")
    
    raw_results = MOCK_SUPPLIERS_DB[sku_upper]
    text_grid = "VENDOR | UNIT PRICE | AVAILABILITY | DELIVERY LEAD TIME\n"
    for r in raw_results:
        text_grid += f"{r['vendor']} | ${r['price']:.2f} | {r['avail']} units | {r['delivery_days']} days\n"
    
    return sanitize_text(text_grid)

# ==========================================
# Tool 3: communications_mcp
# ==========================================

class EmailInput(BaseModel):
    session_id: str = Field(..., description="The session or workflow negotiation ID.")
    recipient_email: str = Field(..., description="The vendor sales contact email.")
    email_body: str = Field(..., description="The drafted email content.")

def send_vendor_negotiation_email(session_id: str, recipient_email: str, email_body: str) -> str:
    """
    Send Vendor Negotiation Email:
    Dispatches a B2B negotiation proposal. Standardizes formatting and logs thread state.
    """
    # Sanitize input email to block indirect prompt injections
    clean_body = sanitize_text(email_body)
    
    if session_id not in VENDOR_EMAIL_THREADS:
        VENDOR_EMAIL_THREADS[session_id] = []
        
    VENDOR_EMAIL_THREADS[session_id].append({
        "sender": "Agent (Procurement)",
        "recipient": recipient_email,
        "body": clean_body
    })
    
    return f"Success: Email dispatched to {recipient_email}. Session: {session_id}."

class SlackInput(BaseModel):
    channel: str = Field(..., description="The slack channel name (e.g. #finance-approvals).")
    message: str = Field(..., description="The markdown alert message block.")

def log_slack_escalation(channel: str, message: str) -> str:
    """
    Log Slack Escalation:
    Sends a block alert to the internal Slack channel for management visibility.
    """
    escalation_entry = {
        "channel": channel,
        "message": sanitize_text(message)
    }
    SLACK_ESCALATIONS.append(escalation_entry)
    return f"Success: Slack block notification pushed to {channel}."

# ==========================================
# Extra Tools (Contract PDF Reader)
# ==========================================

class ContractInput(BaseModel):
    supplier_name: str = Field(..., description="The name of the supplier to extract SLA contract for.")

def read_contract_pdf(supplier_name: str) -> str:
    """
    Read Contract PDF:
    Reads and extracts unstructured SLA contract segments for legal review.
    Applies PII scrubbing and metric salting before exposing contents to the LLM.
    """
    contract_text = None
    for key, text in MOCK_CONTRACTS_DB.items():
        if supplier_name.lower() in key.lower():
            contract_text = text
            break
            
    if not contract_text:
        return f"Error: No SLA contract found for supplier '{supplier_name}'."
        
    # Apply PII scrubbing and metric salting!
    scrubbed = salt_contract_data(contract_text)
    return scrubbed
