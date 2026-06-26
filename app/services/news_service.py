import logging
import json
import random
import time
from datetime import datetime
from typing import List, Optional

from app.core.config import settings
from app.schemas.news import NewsCreate
from google.genai import Client, types
from google.genai.errors import APIError

logger = logging.getLogger(__name__)


class NewsGenerationService:
    """Generate short news posts about AI in education using Gemini with failover."""

    @staticmethod
    def _parse_response_text(text: str) -> dict:
        try:
            clean_text = text.replace("```json", "").replace("```", "").strip()
            return json.loads(clean_text)
        except Exception as e:
            logger.error("Failed to parse AI news response: %s", e)
            raise

    @staticmethod
    def _build_prompt(topic: str) -> str:
        return (
            f"Generate a short, engaging news post about AI in education on the topic: '{topic}'. "
            "Include a one-sentence summary, a 2-4 sentence body that covers origin, present state, and future benefits, "
            "and return output as a JSON object with keys: title, summary, content, topic, origin. "
            "Do not include markdown fences or extra commentary. Keep content SEO-friendly and attention-grabbing."
        )

    @staticmethod
    def generate_for_topic(topic: str, models_to_try: Optional[List[str]] = None) -> NewsCreate:
        client = Client(api_key=settings.GEMINI_API_KEY)
        prompt = NewsGenerationService._build_prompt(topic)

        # Add extra fallbacks: try smaller Gemini, then Vertex AI text-bison if available.
        if models_to_try is None:
            models_to_try = [
                "gemini-3.5-flash",
                "gemini-2.5-flash",
                "gemini-1.0",            # older/smaller Gemini family
                "text-bison@001",       # Vertex AI text model fallback
            ]

        response_text: Optional[str] = None
        used_model = None

        # Retry strategy per model with exponential backoff + jitter
        max_attempts_per_model = 3
        for model in models_to_try:
            attempt = 0
            while attempt < max_attempts_per_model and response_text is None:
                try:
                    attempt += 1
                    logger.info("Generating news using model %s (attempt %d)", model, attempt)
                    response = client.models.generate_content(
                        model=model, contents=prompt, config={"temperature": 0.3}
                    )
                    if getattr(response, "text", None):
                        response_text = response.text
                        used_model = model
                        break
                    # If response exists but no text, treat as failure
                    logger.warning("Model %s returned empty text (attempt %d)", model, attempt)

                except APIError as e:
                    # Treat 429/503 and similar as temporary and retry with backoff
                    is_temp = e.code in (429, 503) or "temporary" in str(e).lower() or "demand" in str(e).lower()
                    logger.warning("Model %s failed (attempt %d): %s", model, attempt, e)
                    if not is_temp:
                        # Non-retriable error for this model — escalate
                        raise

                except Exception as e:
                    logger.exception("Unexpected error while calling model %s: %s", model, e)
                    # For unexpected errors, break attempts for this model and try next
                    break

                # Backoff before next attempt on this model
                if response_text is None and attempt < max_attempts_per_model:
                    backoff = (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    logger.info("Backing off %.2fs before retrying model %s", backoff, model)
                    time.sleep(backoff)

            if response_text:
                break

        if not response_text:
            logger.error("No response from any AI models after retries: %s", models_to_try)
            raise RuntimeError("No response from AI models")

        parsed = NewsGenerationService._parse_response_text(response_text)

        title = parsed.get("title") or f"AI & Education: {topic}"
        summary = parsed.get("summary") or parsed.get("excerpt")
        content = parsed.get("content") or parsed.get("body")
        origin = parsed.get("origin") or "AI Generated"

        # Estimate token cost lightly (placeholder)
        estimated_tokens = max(10, len((content or "")) // 4)

        return NewsCreate(
            title=title,
            summary=summary,
            content=content,
            topic=topic,
            origin=origin,
            ai_generated=True,
            ai_model=used_model,
            ai_tokens_cost=estimated_tokens,
        )

    @staticmethod
    def random_topic() -> str:
        topics = [
            "AI tutors for personalized learning",
            "Automated grading and feedback systems",
            "Using AI to detect student disengagement",
            "Generative AI for classroom content creation",
            "AI-driven accessibility tools in education",
            "Ethical considerations of AI in schools",
            "AI-powered formative assessment techniques",
            "Adaptive learning platforms powered by AI",
        ]
        return random.choice(topics)
