import re
import json
from typing import Dict, Any, List
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("Supply Chain DB")

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
# In-Memory Mock Databases
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

# ==========================================
# MCP Tool Endpoints
# ==========================================

@mcp.tool()
def get_sku_buffer_health(sku: str) -> str:
    """
    Get SKU Buffer Health:
    Retrieves internal stock level, daily run-rate, and remaining exhaustion window.
    """
    if not sku or not isinstance(sku, str):
        return "Error: Invalid SKU code."
        
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

@mcp.tool()
def get_supplier_meta(supplier_name: str) -> str:
    """
    Get Supplier Metadata:
    Retrieves historical vendor performance rating and default contact information.
    """
    if not supplier_name or not isinstance(supplier_name, str):
        return "Error: Invalid supplier name."
        
    return json.dumps({
        "supplier_name": supplier_name,
        "rating": "A+" if "Pacific" in supplier_name else "B",
        "preferred_status": True,
        "contact_email": f"sales@{supplier_name.lower().replace(' ', '')}.com"
    })

@mcp.tool()
def read_contract_pdf(supplier_name: str) -> str:
    """
    Read Contract PDF:
    Reads and extracts unstructured SLA contract segments for legal review.
    Applies PII scrubbing and metric salting before exposing contents to the LLM.
    """
    if not supplier_name or not isinstance(supplier_name, str):
        return "Error: Invalid supplier name."
        
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

@mcp.tool()
def scrape_supplier_marketplace(sku: str) -> str:
    """
    Scrape Supplier Marketplace:
    Scrapes external B2B supplier sites to find alternative vendors, pricing, and availability.
    Applies security sanitization before returning.
    """
    if not sku or not isinstance(sku, str):
        return "Error: Invalid SKU code."
        
    sku_upper = sku.strip().upper()
    if sku_upper not in MOCK_SUPPLIERS_DB:
        return sanitize_text(f"No alternative suppliers found for SKU {sku}.")
    
    raw_results = MOCK_SUPPLIERS_DB[sku_upper]
    text_grid = "VENDOR | UNIT PRICE | AVAILABILITY | DELIVERY LEAD TIME\n"
    for r in raw_results:
        text_grid += f"{r['vendor']} | ${r['price']:.2f} | {r['avail']} units | {r['delivery_days']} days\n"
    
    return sanitize_text(text_grid)

if __name__ == "__main__":
    mcp.run()
