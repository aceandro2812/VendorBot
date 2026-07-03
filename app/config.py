import os
from dotenv import load_dotenv
from google.adk.models.google_llm import Gemini

# Load environment variables
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Root path for database / file mock operations
DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# LLM Config
# We use gemini-2.5-flash for balanced latency, accuracy, and cost
llm_model = Gemini(
    model="gemini-2.5-flash",
    api_key=GEMINI_API_KEY
)

# Business Rule Thresholds
BUDGET_PREMIUM_THRESHOLD = 0.10  # 10% maximum premium allowed before routing to Finance for manual approval
MAX_NEGOTIATION_TURNS = 4
