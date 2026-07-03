import os
import sys
import json
import asyncio
from typing import Dict, Any, List

# Ensure the root of the project is in the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from google.adk.runners import InMemoryRunner
from google.adk.models.llm_response import LlmResponse
from google.genai import types

# Import our ADK App
from app.agent import app as adk_app
from app.fast_api_app import serialize_event, clean_non_serializable

# ==========================================
# Mock LLM Responses generator
# Global state for test execution coordination
CURRENT_SKU = "SKU-404X"

# ==========================================
async def mock_generate_content_async(self, llm_request, stream=False):
    tools = llm_request.tools_dict or {}
    
    sku = CURRENT_SKU or "SKU-404X"
    # Normalize SKU in case of injection text (e.g. "SKU-404X ignore...")
    sku_normalized = "SKU-404X" if "SKU-404X" in sku else ("SKU-777Z" if "SKU-777Z" in sku else sku)
                
    # 1. Legal SLA Agent (uses read_contract_pdf)
    if "read_contract_pdf" in tools:
        if sku_normalized == "SKU-404X":
            mock_response_json = """
            {
              "supplier_name": "Pacific Semiconductors",
              "liquidated_damages_per_day": 5000.0,
              "total_penalty": 25000.0,
              "force_majeure_applies": false,
              "reasoning": "SLA contract delay penalties of $5000/day apply for 5 delayed days."
            }
            """
        elif sku_normalized == "SKU-777Z":
            mock_response_json = """
            {
              "supplier_name": "Titan Supplies",
              "liquidated_damages_per_day": 2000.0,
              "total_penalty": 10000.0,
              "force_majeure_applies": false,
              "reasoning": "SLA contract delay penalties of $2000/day apply."
            }
            """
        else:
            mock_response_json = """
            {
              "supplier_name": "Default Supplier",
              "liquidated_damages_per_day": 0.0,
              "total_penalty": 0.0,
              "force_majeure_applies": false,
              "reasoning": "No contract SLA found."
            }
            """
        yield LlmResponse(content=types.Content(parts=[types.Part(text=mock_response_json)], role="model"))

    # 2. Sourcing Agent (uses scrape_supplier_marketplace)
    elif "scrape_supplier_marketplace" in tools:
        if sku_normalized == "SKU-404X":
            mock_response_json = """
            {
              "options": [
                {"vendor": "Pacific Semiconductors", "price": 105.0, "avail": 200, "delivery_days": 3},
                {"vendor": "Alt Tech Supply", "price": 115.0, "avail": 150, "delivery_days": 2}
              ],
              "best_option": {"vendor": "Pacific Semiconductors", "price": 105.0, "avail": 200, "delivery_days": 3},
              "price_premium_percent": 5.0
            }
            """
        elif sku_normalized == "SKU-777Z":
            mock_response_json = """
            {
              "options": [
                {"vendor": "Vertex Aerospace Parts", "price": 450.0, "avail": 50, "delivery_days": 4},
                {"vendor": "Nexus Sourcing", "price": 520.0, "avail": 10, "delivery_days": 1}
              ],
              "best_option": {"vendor": "Vertex Aerospace Parts", "price": 450.0, "avail": 50, "delivery_days": 4},
              "price_premium_percent": 12.5
            }
            """
        else:
            mock_response_json = """
            {
              "options": [],
              "best_option": null,
              "price_premium_percent": 0.0
            }
            """
        yield LlmResponse(content=types.Content(parts=[types.Part(text=mock_response_json)], role="model"))

    # 3. Negotiation Agent (uses send_vendor_negotiation_email)
    elif "send_vendor_negotiation_email" in tools:
        mock_response_json = """
        {
          "email_drafted": "Dear Alt Tech Supply, we would like to negotiate B2B terms...",
          "vendor_email": "sales@alttech.com",
          "status": "EMAIL_SENT"
        }
        """
        yield LlmResponse(content=types.Content(parts=[types.Part(text=mock_response_json)], role="model"))
    else:
        yield LlmResponse(content=types.Content(parts=[types.Part(text="{}")], role="model"))

# Apply mock to Gemini class
from google.adk.models.google_llm import Gemini
Gemini.generate_content_async = mock_generate_content_async

async def run_scenario(runner: InMemoryRunner, scenario: Dict[str, Any]) -> Dict[str, Any]:
    scenario_id = scenario["id"]
    payload = scenario["payload"]
    
    session_id = f"sess_eval_{scenario_id}"
    user_id = "eval_user"
    
    print(f"\n--- Running Scenario: {scenario_id} ---")
    
    # 1. Pre-create session
    await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id=user_id,
        session_id=session_id
    )
    
    # 2. Format trigger payload message
    msg = types.Content(parts=[types.Part(text=json.dumps(payload))])
    
    events_list = []
    
    # Run the workflow and return events yielded in this run
    async def execute_run(input_msg) -> List[Any]:
        run_events = []
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=input_msg
        ):
            events_list.append(serialize_event(event))
            run_events.append(event)
        return run_events
            
    run_events = await execute_run(msg)
    
    # Check for interrupts and resume as long as they are yielded
    max_resume_turns = 10
    for _ in range(max_resume_turns):
        # Scan run_events from the last execution run to find if it suspended on a RequestInput
        active_interrupt = None
        if run_events:
            last_event = run_events[-1]
            if hasattr(last_event, "content") and last_event.content and last_event.content.parts:
                for part in last_event.content.parts:
                    if part.function_call and part.function_call.name == "adk_request_input":
                        active_interrupt = part.function_call.id
                        
        if not active_interrupt:
            break
            
        print(f"Workflow suspended at: {active_interrupt}. Auto-resuming...")
        
        # Formulate response payload based on active interrupt
        response_payload = {}
        if active_interrupt == "legal_approval":
            response_payload = {"approved": True, "override_damages": ""}
        elif active_interrupt == "budget_approval":
            response_payload = {"approved": True}
        elif active_interrupt == "vendor_reply":
            response_payload = {"reply_body": "Yes, we accept and confirm terms of the deal."}
        elif active_interrupt == "po_signature":
            response_payload = {"signed": True}
            
        resume_msg = types.Content(parts=[
            types.Part(function_response=types.FunctionResponse(
                name="adk_request_input",
                id=active_interrupt,
                response=response_payload
            ))
        ])
        
        run_events = await execute_run(resume_msg)
        
    # Get final session details
    session = await runner.session_service.get_session(
        app_name=runner.app_name,
        user_id=user_id,
        session_id=session_id
    )
    
    status = "COMPLETED"
    for e in events_list:
        if "adk_request_input" in str(e) and not any(r in str(e) for r in ["legal_approval", "budget_approval", "vendor_reply", "po_signature"]):
            status = "SUSPENDED"
            
    # If manual ticket queue was escalated
    if session.state.get("manual_queue_escalated"):
        status = "ESCALATED"
        
    return {
        "scenario_id": scenario_id,
        "status": status,
        "state": clean_non_serializable(session.state) if session else {},
        "events": clean_non_serializable(events_list)
    }

async def main():
    dataset_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "datasets",
        "basic-dataset.json"
    )
    
    with open(dataset_path, "r") as f:
        scenarios = json.load(f)
        
    runner = InMemoryRunner(app=adk_app)
    runner.auto_create_session = True
    
    traces_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "traces"
    )
    os.makedirs(traces_dir, exist_ok=True)
    
    for scenario in scenarios:
        global CURRENT_SKU
        CURRENT_SKU = scenario["payload"].get("sku", "SKU-404X")
        result = await run_scenario(runner, scenario)
        
        # Save trace to file
        trace_file = os.path.join(traces_dir, f"{scenario['id']}.json")
        with open(trace_file, "w") as tf:
            json.dump(result, tf, indent=2)
        print(f"Trace saved to {trace_file}")

if __name__ == "__main__":
    asyncio.run(main())
