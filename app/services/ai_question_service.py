import json
import logging 
from typing import List, Optional
from app.core.config import settings
from app.schemas.arena import QuestionSchema
 
from google.genai import Client, types

logger = logging.getLogger(__name__)

class AIQuestionGenerationService:
    """Service for AI-powered question generation using Gemini 3.5 Flash"""

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

        try:
            response = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=prompt,
                config={"temperature": 0.7}
            )

            if response.text:
                questions_data = AIQuestionGenerationService._parse_ai_response(response.text)
            else:
                logger.error("Received empty response from Gemini")
                questions_data = []
                
            questions = []
            for q_data in questions_data:
                try:
                    # Calculate token cost for this question
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
                    logger.warning(f"Skipping malformed question: {e}")
                    continue

            return questions

        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise ValueError(f"Error generating questions via Gemini: {str(e)}")

    @staticmethod
    def _build_prompt(subject: str, num_questions: int, difficulty: str, language: str) -> str:
        return f"""Generate exactly {num_questions} quiz questions on: "{subject}".
        Difficulty: {difficulty}. Language: {language}.
        Return ONLY a raw JSON array. Do not include markdown formatting or extra text.
        Format: [ {{"prompt_text": "...", "options": ["A", "B", "C", "D"], "correct_option_index": 0, "time_limit_seconds": 30, "point_value": 10}} ]"""
        

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
