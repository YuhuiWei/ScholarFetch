import os

OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
S2_API_KEY: str = os.environ.get("S2_API_KEY", "")
POLITE_POOL_EMAIL: str = os.environ.get("NEXUS_EMAIL", "nexus@research.local")
OPENREVIEW_BASEURL: str = os.environ.get("OPENREVIEW_BASEURL", "https://api2.openreview.net")
OPENREVIEW_USERNAME: str = os.environ.get("OPENREVIEW_USERNAME", "")
OPENREVIEW_PASSWORD: str = os.environ.get("OPENREVIEW_PASSWORD", "")

OPENALEX_TIMEOUT: float = 30.0
S2_TIMEOUT: float = 20.0
OPENREVIEW_TIMEOUT: float = 15.0
OPENREVIEW_SEARCH_PAGE_SIZE: int = int(os.environ.get("OPENREVIEW_SEARCH_PAGE_SIZE", "50"))
