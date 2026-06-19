import json
import logging 
from typing import List, Optional
from app.core.config import settings
from app.schemas.arena import QuestionSchema
from google.genai.errors import APIError 
from google.genai import Client, types

logger = logging.getLogger(__name__)

class AIQuestionGenerationService:
    """Service for AI-powered question generation using Gemini with automatic model failover"""

    @staticmethod
    def _parse_ai_response(response_text: str) -> List[dict]:
        """Parses and cleans the JSON response from Gemini."""
        try:
            clean_text = response_text.replace("```json", "").replace("```", "").strip()
            return json.loads(clean_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response: {e}")
            raise ValueError(f"Invalid JSON in AI response: {str(e)}")

    @staticmethod
    async def generate_questions(
        subject: str,
        num_questions: int = 5,
        difficulty: str = "medium",
        language: str = "en"
    ) -> List[QuestionSchema]:
        
        client = Client(api_key=settings.GEMINI_API_KEY)
        
        prompt = AIQuestionGenerationService._build_prompt(
            subject=subject, 
            num_questions=num_questions, 
            difficulty=difficulty,
            language=language
        )

        # High-capacity fallback sequence to beat temporary server spikes
        models_to_try = ["gemini-3.5-flash", "gemini-2.5-flash"]
        response_text: Optional[str] = None

        for model_name in models_to_try:
            try:
                logger.info(f"Attempting arena question generation with model: {model_name}")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={"temperature": 0.7}
                )
                
                if response.text:
                    response_text = response.text
                    break  # Success! Break the retry loop.
                    
            except APIError as e:
                # Catch temporary high demand spikes (503) or rate limits (429)
                is_temporary_spike = (
                    e.code in [429, 503] or 
                    "demand" in str(e).lower() or 
                    "temporary" in str(e).lower()
                )
                
                if is_temporary_spike and model_name != models_to_try[-1]:
                    logger.warning(
                        f"Model {model_name} failed with temporary error code {e.code}. "
                        f"Attempting failover to fallback engine..."
                    )
                    continue  # Jump directly to the next model layout block
                else:
                    # If it's a permanent structural issue, or our last available fallback also failed
                    logger.error(f"Gemini API execution crash on {model_name} [{e.code}]: {e}")
                    
                    if e.code == 503 or "demand" in str(e).lower() or "temporary" in str(e).lower():
                        user_friendly_msg = "Please wait a moment and try generating again!"
                    elif e.code == 429:
                        user_friendly_msg = "Slow down a bit! Try again in a minute."
                    else:
                        user_friendly_msg = f"Gemini system error: {e.message}"
                    raise ValueError(user_friendly_msg)

            except Exception as e:
                logger.error(f"Gemini API unknown error on model {model_name}: {e}")
                raise ValueError("An unexpected issue occurred while styling your questions. Please try again.")

        # Reconcile downstream parsing schemas using our validated response text
        if response_text:
            questions_data = AIQuestionGenerationService._parse_ai_response(response_text)
        else:
            logger.error("Received empty response string across all active Gemini generation engines")
            questions_data = []
            
        questions = []
        for q_data in questions_data:
            try:
                from app.services.token_service import TokenService
                token_cost = TokenService.calculate_question_cost(
                    len(q_data.get("prompt_text") or q_data.get("question") or ""),
                    len(q_data.get("options", [])),
                    use_ai_generation=True
                )
                
                question = QuestionSchema(
                    prompt_text=str(q_data.get("prompt_text") or q_data.get("question") or "Untitled Question"),
                    options=q_data.get("options", []),
                    correct_option_index=q_data.get("correct_option_index", 0),
                    time_limit_seconds=q_data.get("time_limit_seconds", 30),
                    point_value=q_data.get("point_value", 10),
                    is_ai_generated=True,
                    ai_tokens_cost=token_cost,
                    status="ready",
                )
                questions.append(question)
            except Exception as e:
                logger.warning(f"Skipping malformed question item: {e}")
                continue

        return questions

    @staticmethod
    def _build_prompt(subject: str, num_questions: int, difficulty: str, language: str) -> str:
        dialect_rules = {
            "en": "Write the questions and options cleanly in standard global English.",
            
            "en-wa": (
                "Write the questions and options primarily in English, but heavily infuse popular "
                "West African dialects, local expressions, and West African Pidgin English context. "
                "Naturally incorporate terms like 'Chale', 'Abeg', 'Gobe', 'No wahala', or 'Comot' "
                "where contextually appropriate to make it fun and immersive for a gaming quiz."
            ),
            
            "en-ea": (
                "Write the questions and options primarily in English, but heavily infuse East African "
                "colloquialisms, cultural concepts, and popular Sheng/Swahili slang words used in daily conversation. "
                "Integrate localized expressions like 'Mambo vipi', 'Kuwa mpole', 'Kula raba', 'Chonjo', "
                "or context referencing local elements like 'Matatus' and 'Bodabodas'."
            ),
            
            "fr": "Write the questions and options cleanly in standard global French.",
            
            "fr-wa": (
                "Write the questions and options primarily in French, but infuse West African French "
                "colloquialisms and popular slang terms frequently used in urban centers like Abidjan or Douala. "
                "Integrate vibrant terms like 'Ambianceur', 'Dja', 'Boucan', or 'Chicotter' naturally."
            )
        }

        specific_language_rule = dialect_rules.get(
            language, 
            f"Write the questions and options cleanly in the specified global language: '{language}'."
        )

        return f"""Generate exactly {num_questions} quiz questions on: "{subject}".
        Difficulty Level: {difficulty}.
        
        Linguistic & Dialect Style Rule:
        {specific_language_rule}
        
        CRITICAL OUTPUT FORMAT RULES:
        Return ONLY a raw JSON array. Do not wrap the JSON output inside markdown block markers like ```json ... ```. Do not include any trailing conversational text or extra metadata outside the array.
        
        JSON Structure Format:
        [ {{"prompt_text": "...", "options": ["A", "B", "C", "D"], "correct_option_index": 0, "time_limit_seconds": 30, "point_value": 10}} ]"""

class QuestionContentService:
    """Service for validating and enriching question content"""

    @staticmethod
    def validate_question(question: QuestionSchema) -> tuple[bool, Optional[str]]:
        """
        Validate a question schema
        
        Returns:
            (is_valid, error_message)
        """
        if not question.prompt_text or len(question.prompt_text.strip()) < 5:
            return False, "Question text must be at least 5 characters"

        if len(question.options) < 2:
            return False, "Question must have at least 2 options"

        if question.correct_option_index is None:
            return False, "correct_option_index is required"

        if question.correct_option_index >= len(question.options):
            return False, "correct_option_index out of range"

        if question.correct_option_index < 0:
            return False, "correct_option_index cannot be negative"

        if question.time_limit_seconds < 5 or question.time_limit_seconds > 300:
            return False, "time_limit_seconds must be between 5 and 300"

        if question.point_value < 1 or question.point_value > 1000:
            return False, "point_value must be between 1 and 1000"

        return True, None

    @staticmethod
    def calculate_tokens_for_questions(questions: List[QuestionSchema]) -> int:
        """Calculate total token cost for a list of questions"""
        from app.services.token_service import TokenService

        total = 0
        for q in questions:
            if q.is_ai_generated:
                cost = TokenService.calculate_question_cost(
                    len(q.prompt_text),
                    len(q.options),
                    use_ai_generation=True
                )
                total += cost
        return total