import uuid
import json
import logging
from typing import Dict, Any, Optional, Literal
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from google.adk.runners import InMemoryRunner
from google.genai import types

# Import our workflow agent
from app.agent import app as adk_app

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fast_api_app")

# Initialize FastAPI
app = FastAPI(
    title="Autonomous SLA Breach & Supply-Chain Negotiator API",
    description="Backend orchestration engine and session state manager.",
    version="1.0.0"
)

# Enable CORS for frontend connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Instantiate the ADK local runner
runner = InMemoryRunner(app=adk_app)
# Enable auto session creation
runner.auto_create_session = True

def clean_non_serializable(obj: Any) -> Any:
    import datetime
    import uuid
    from pydantic import BaseModel
    if isinstance(obj, dict):
        return {str(k): clean_non_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple, set)):
        return [clean_non_serializable(x) for x in obj]
    elif isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except UnicodeDecodeError:
            return obj.decode("latin-1")
    elif isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    elif isinstance(obj, uuid.UUID):
        return str(obj)
    elif isinstance(obj, BaseModel):
        return clean_non_serializable(obj.model_dump())
    elif hasattr(obj, "to_json"):
        try:
            return clean_non_serializable(obj.to_json())
        except Exception:
            pass
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)

# Helper to normalize event list for JSON serialization
def serialize_event(event: Any) -> Dict[str, Any]:
    try:
        # Check if it has a Pydantic dict or model_dump
        if hasattr(event, "model_dump"):
            data = event.model_dump()
        elif hasattr(event, "dict"):
            data = event.dict()
        else:
            try:
                data = dict(event)
            except Exception:
                data = {"value": str(event)}
        
        # Safe serialize timestamps and non-serializable fields
        data["event_type"] = type(event).__name__
        return clean_non_serializable(data)
    except Exception as e:
        return {"event_type": type(event).__name__, "raw": str(event)}

# Curated list of Gemini API Free Tier models (updated Jul 2026)
# Reference: https://ai.google.dev/gemini-api/docs/pricing
GEMINI_FREE_TIER_MODELS = {
    # --- Generation 3.x (Latest) ---
    "gemini-3.5-flash",       # Newest: current standard high-performance
    "gemini-3.1-flash-lite",  # Newest lite: high-volume low-latency
    # --- Generation 2.5 ---
    "gemini-2.5-flash",       # Best price/performance in 2.5 series
    "gemini-2.5-flash-lite",  # Fastest 2.5 variant
    "gemini-2.5-pro",         # Most capable 2.5 reasoning model
    # --- Generation 1.5 (Legacy) ---
    "gemini-1.5-flash",       # Stable legacy flash
    "gemini-1.5-flash-8b",    # Smallest legacy option
    "gemini-1.5-pro",         # Legacy high-capability
}

class TriggerPayload(BaseModel):
    sku: str = "SKU-404X"
    factory_code: str = "FAC-12"
    delayed_days: int = 5
    model_name: str = "gemini-2.5-flash"

    @field_validator("model_name")
    @classmethod
    def validate_model(cls, v: str) -> str:
        if v not in GEMINI_FREE_TIER_MODELS:
            raise ValueError(
                f"Model '{v}' is not a supported free-tier Gemini model. "
                f"Choose from: {sorted(GEMINI_FREE_TIER_MODELS)}"
            )
        return v

def update_llm_models(model_name: str):
    from app.config import GEMINI_API_KEY
    from google.adk.models.google_llm import Gemini
    from app.agent import legal_sla_agent, sourcing_agent, negotiation_agent
    logger.info(f"[MODEL SWITCH] Switching all LLM agents to: {model_name}")
    new_model = Gemini(model=model_name, api_key=GEMINI_API_KEY)
    legal_sla_agent.model = new_model
    sourcing_agent.model = new_model
    negotiation_agent.model = new_model

@app.post("/api/sessions/trigger")
async def trigger_pipeline(payload: TriggerPayload):
    """
    Triggers a new supply chain negotiation workflow session.
    """
    session_id = f"sess_{uuid.uuid4().hex[:8]}"
    user_id = "default_operator"
    
    # 1. Pre-create the session
    await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id=user_id,
        session_id=session_id
    )
    
    # 2. Ingest the payload as a JSON message string
    payload_json = json.dumps({
        "sku": payload.sku,
        "factory_code": payload.factory_code,
        "delayed_days": payload.delayed_days,
        "model_name": payload.model_name
    })
    
    msg = types.Content(parts=[types.Part(text=payload_json)])
    
    events_list = []
    
    try:
        # Dynamically set model
        update_llm_models(payload.model_name)
        
        # 3. Run the workflow until it suspends or completes
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=msg
        ):
            events_list.append(serialize_event(event))
            
        # 4. Fetch the final state of the session
        session = await runner.session_service.get_session(
            app_name=runner.app_name,
            user_id=user_id,
            session_id=session_id
        )
        
        return {
            "session_id": session_id,
            "status": "SUSPENDED" if any("adk_request_input" in str(e) for e in events_list) else "COMPLETED",
            "state": clean_non_serializable(session.state) if session else {},
            "events": clean_non_serializable(events_list)
        }
    except Exception as e:
        logger.exception("Error running workflow session trigger")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sessions/{session_id}/resume/{interrupt_id}")
async def resume_session(session_id: str, interrupt_id: str, payload: Dict[str, Any] = Body(...)):
    """
    Resumes a suspended workflow session with human approval decision or email reply.
    """
    user_id = "default_operator"
    
    # Verify session exists
    session = await runner.session_service.get_session(
        app_name=runner.app_name,
        user_id=user_id,
        session_id=session_id
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
        
    # Construct the function response message matching the GenAI schema.
    # The name must be "adk_request_input" to match the RequestInput function call turn in history.
    response_msg = types.Content(parts=[
        types.Part(function_response=types.FunctionResponse(
            name="adk_request_input",
            id=interrupt_id,
            response=payload
        ))
    ])
    
    events_list = []
    try:
        # Dynamically set model based on state
        selected_model = session.state.get("selected_model", "gemini-2.5-flash") if session else "gemini-2.5-flash"
        update_llm_models(selected_model)
        
        # Resume execution
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=response_msg
        ):
            events_list.append(serialize_event(event))
            
        session = await runner.session_service.get_session(
            app_name=runner.app_name,
            user_id=user_id,
            session_id=session_id
        )
        
        return {
            "session_id": session_id,
            "status": "SUSPENDED" if any("adk_request_input" in str(e) for e in events_list) else "COMPLETED",
            "state": clean_non_serializable(session.state) if session else {},
            "events": clean_non_serializable(events_list)
        }
    except Exception as e:
        logger.exception("Error resuming workflow session")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sessions")
async def list_active_sessions():
    """
    Retrieves all workflow sessions from the in-memory store.
    """
    user_id = "default_operator"
    try:
        sessions_container = await runner.session_service.list_sessions(
            app_name=runner.app_name,
            user_id=user_id
        )
        
        results = []
        # Get list of Session objects from the container model
        sessions_list = getattr(sessions_container, "sessions", [])
        for s in sessions_list:
            # Determine status by scanning events
            is_suspended = False
            active_interrupt = None
            
            for event in s.events:
                if hasattr(event, "content") and event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.function_call and part.function_call.name == "adk_request_input":
                            is_suspended = True
                            active_interrupt = part.function_call.id
                            
            last_updated = None
            if s.last_update_time:
                from datetime import datetime
                if isinstance(s.last_update_time, (int, float)):
                    last_updated = datetime.fromtimestamp(s.last_update_time).isoformat()
                else:
                    try:
                        last_updated = s.last_update_time.isoformat()
                    except Exception:
                        last_updated = str(s.last_update_time)

            results.append({
                "session_id": s.id,
                "state": clean_non_serializable(s.state),
                "is_suspended": is_suspended,
                "active_interrupt": active_interrupt,
                "last_updated": last_updated
            })
        return results
    except Exception as e:
        logger.exception("Error listing sessions")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sessions/{session_id}")
async def get_session_details(session_id: str):
    """
    Retrieves details (state and events) for a single session.
    """
    user_id = "default_operator"
    session = await runner.session_service.get_session(
        app_name=runner.app_name,
        user_id=user_id,
        session_id=session_id
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
        
    serialized_events = [serialize_event(e) for e in session.events]
    
    # Find active interrupt
    is_suspended = False
    active_interrupt = None
    for event in session.events:
        if hasattr(event, "content") and event.content and event.content.parts:
            for part in event.content.parts:
                if part.function_call and part.function_call.name == "adk_request_input":
                    is_suspended = True
                    active_interrupt = part.function_call.id
                    
    return {
        "session_id": session.id,
        "state": clean_non_serializable(session.state),
        "is_suspended": is_suspended,
        "active_interrupt": active_interrupt,
        "events": clean_non_serializable(serialized_events)
    }
