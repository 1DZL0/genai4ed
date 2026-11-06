"""Lessons the tests share, as plain data."""

from app.agent.brief import LessonBrief

THREE = LessonBrief.model_validate(
    {
        "title": "Linear equations",
        "subject": "mathematics",
        "age": 13,
        "activity": "answers",
        "objectives": ["Solve equations with the unknown on both sides"],
        "steps": [
            {
                "name": "Warm up",
                "kind": "question",
                "goal": "Solve 3x + 4 = 19",
                "prompt_ideas": ["Solve 3x + 4 = 19"],
                "success_criteria": ["x = 5 with working"],
                "reference_answer": "5",
            },
            {
                "name": "Both sides",
                "kind": "practice",
                "goal": "Solve 5x - 7 = 2x + 8",
                "prompt_ideas": ["Solve 5x - 7 = 2x + 8"],
                "success_criteria": ["x = 5 with the x terms collected"],
                "reference_answer": "5",
            },
            {
                "name": "Brackets",
                "kind": "check",
                "goal": "Solve 2(x - 3) = 18",
                "prompt_ideas": ["Solve 2(x - 3) = 18"],
                "success_criteria": ["x = 12"],
                "reference_answer": "12",
            },
        ],
        "topics": ["linear equations"],
    }
)
