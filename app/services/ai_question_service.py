"""
AI Question Generation Service
Handles generating quiz questions using AI APIs (OpenAI, etc.)
"""
import json
import logging
from typing import Optional, List
import re

import httpx
from app.core.config import settings
from app.schemas.arena import QuestionSchema

logger = logging.getLogger(__name__)


class AIQuestionGenerationService:
    """Service for AI-powered question generation"""

    @staticmethod
    def _parse_ai_response(response_text: str) -> List[dict]:
        """
        Parse AI response into question objects
        Expects JSON array format
        """
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\[[\s\S]*\]', response_text)
            if json_match:
                questions_data = json.loads(json_match.group())
                return questions_data
            else:
                raise ValueError("No JSON array found in response")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response: {e}")
            raise ValueError(f"Invalid JSON in AI response: {str(e)}")

    @staticmethod
    async def generate_questions(
        subject: str,
        num_questions: int = 5,
        difficulty: str = "medium",
        language: str = "en"
    ) -> List[QuestionSchema]:
        """
        Generate quiz questions using OpenAI API
        
        Args:
            subject: Topic/subject for the questions
            num_questions: Number of questions to generate
            difficulty: Question difficulty (easy, medium, hard)
            language: Language code (en, es, fr, etc.)
        
        Returns:
            List of QuestionSchema objects ready to be added to arena
        
        Raises:
            ValueError: If API fails or response is invalid
        """
        
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not configured")
        
        if num_questions < 1 or num_questions > 50:
            raise ValueError("num_questions must be between 1 and 50")

        prompt = AIQuestionGenerationService._build_prompt(
            subject=subject,
            num_questions=num_questions,
            difficulty=difficulty,
            language=language
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "gpt-3.5-turbo",
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are an expert educational content creator. Generate high-quality quiz questions."
                            },
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        "temperature": 0.7,
                        "max_tokens": 2000,
                    }
                )

                if response.status_code != 200:
                    error_msg = response.text
                    logger.error(f"OpenAI API error ({response.status_code}): {error_msg}")
                    raise ValueError(f"OpenAI API error: {error_msg}")

                response_data = response.json()
                ai_response = response_data["choices"][0]["message"]["content"]

                # Parse the response into question objects
                questions_data = AIQuestionGenerationService._parse_ai_response(ai_response)

                # Convert to QuestionSchema objects
                questions = []
                for q_data in questions_data:
                    try:
                        question = QuestionSchema(
                            prompt_text=q_data.get("prompt_text") or q_data.get("question"),
                            options=q_data.get("options", []),
                            correct_option_index=q_data.get("correct_option_index", 0),
                            time_limit_seconds=q_data.get("time_limit_seconds", 30),
                            point_value=q_data.get("point_value", 10),
                            is_ai_generated=True,
                            ai_tokens_cost=0  # Will be calculated later
                        )
                        questions.append(question)
                    except Exception as e:
                        logger.warning(f"Failed to parse question: {e}, skipping")
                        continue

                if not questions:
                    raise ValueError("No valid questions could be extracted from AI response")

                logger.info(f"Generated {len(questions)} questions for subject: {subject}")
                return questions

        except httpx.RequestError as e:
            logger.error(f"HTTP request failed: {e}")
            raise ValueError(f"Failed to connect to OpenAI API: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error during question generation: {e}")
            raise ValueError(f"Error generating questions: {str(e)}")

    @staticmethod
    def _build_prompt(
        subject: str,
        num_questions: int,
        difficulty: str,
        language: str
    ) -> str:
        """Build the prompt for OpenAI"""
        
        difficulty_desc = {
            "easy": "beginner/easy level",
            "medium": "intermediate level",
            "hard": "advanced/difficult level"
        }.get(difficulty, "intermediate level")

        return f"""Generate exactly {num_questions} multiple-choice quiz questions on the subject: "{subject}"

Requirements:
- Difficulty level: {difficulty_desc}
- Language: {language}
- Each question should have 4 options (A, B, C, D)
- Each question should be clear and educational
- Time limit: 30 seconds per question
- Points: 10 points per question

Return ONLY valid JSON in this exact format (no markdown, no code blocks):
[
  {{
    "prompt_text": "Question text here?",
    "options": ["Option A", "Option B", "Option C", "Option D"],
    "correct_option_index": 0,
    "time_limit_seconds": 30,
    "point_value": 10
  }},
  ...
]

Make sure:
1. The JSON is valid and parseable
2. correct_option_index is 0-3
3. All 4 options are provided
4. Questions are unique and varied
5. No duplicate questions"""


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
