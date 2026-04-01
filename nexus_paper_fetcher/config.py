import os

OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
S2_API_KEY: str = os.environ.get("S2_API_KEY", "")
POLITE_POOL_EMAIL: str = os.environ.get("NEXUS_EMAIL", "nexus@research.local")

OPENALEX_TIMEOUT: float = 30.0
S2_TIMEOUT: float = 20.0
OPENREVIEW_TIMEOUT: float = 15.0
