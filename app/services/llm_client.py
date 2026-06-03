import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.core.config import settings
from app.utils.helpers import clean_sql

logger = structlog.get_logger()

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

class LLMClient:
    def __init__(self):
        self.model = settings.LLM_MODEL
        self.api_key = settings.GROQ_API_KEY
        self._validate_config()

    def _validate_config(self):
        if not self.api_key or self.api_key == "your_groq_api_key_here":
            logger.warning(
                "groq_api_key_missing",
                message="GROQ_API_KEY not set. LLM calls will return placeholder SQL. "
                        "Get a free key at https://console.groq.com"
            )
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=30),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)),
    )
    async def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 1024) -> str:
        if not self.api_key or self.api_key == "your_groq_api_key_here":
            logger.warning("llm_skipped", reason="No API key configured")
            return "SELECT 'No API key configured. Set GROQ_API_KEY in .env' AS error;"

        logger.info("llm_request", model=self.model, prompt=user_prompt)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.1, 
                    "top_p": 0.95,
                },
            )
            response.raise_for_status()
        data = response.json()
        raw_output = data["choices"][0]["message"]["content"]
        logger.info("llm_response", response=raw_output)
        sql = clean_sql(raw_output)
        return sql
