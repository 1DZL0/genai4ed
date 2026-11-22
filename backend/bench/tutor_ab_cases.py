"""The nine situations of the tutor A/B, one or more for each change in the learning-science
guidance (docs/superpowers/specs/2026-11-22-tutor-learning-science-design.md, T1 to T7).

Each is a lesson step, the teacher's rules, whether the tutor may adapt, what it remembers of
the student, the student's messages in order, and what its replies must show. The student's
words are fixed, so today's prompt and the new one meet the same student.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Situation:
    id: str
    targets: tuple[str, ...]
    subject: str
    age: int
    steps: tuple[dict, ...]
    student: tuple[str, ...]
    criteria: tuple[str, ...]
    rules: dict | None = None
    adapt: bool = False
    # How the student learns (every lesson) and what they know (this subject only).
    memory_learns: tuple[str, ...] = ()
    memory_knows: tuple[str, ...] = ()


def step(name: str, kind: str, question: str, done_when: str, answer: str | None = None) -> dict:
    return {
        "name": name,
        "kind": kind,
        "goal": question,
        "prompt_ideas": [question],
        "success_criteria": [done_when],
        "reference_answer": answer,
    }


SITUATIONS: tuple[Situation, ...] = (
    Situation(
        id="1-misconception",
        targets=("T1", "T3"),
        subject="mathematics",
        age=11,
        steps=(
            step(
                "Adding",
                "question",
                "What is 1/3 + 1/4?",
                "7/12, with a common denominator",
                "7/12",
            ),
        ),
        student=("2/7",),
        criteria=(
            "The tutor's reply to '2/7' names the specific wrong idea (adding the tops and adding "
            "the bottoms) and shows why it cannot be right, with a reason or a counter-example, "
            "without giving the answer 7/12.",
            "The tutor does not label the student or name an error type to them: no 'knowledge "
            "error', no 'misconception' or similar said to the student.",
        ),
    ),
    Situation(
        id="2-reasoning-slip",
        targets=("T1", "T3"),
        subject="mathematics",
        age=13,
        steps=(step("Solve", "question", "Solve 2x + 5 = 19", "x = 7 with working", "7"),),
        student=("2x = 24",),
        criteria=(
            "The tutor's reply points to the exact move that went wrong (adding 5 instead of "
            "taking 5 away from both sides), rather than only saying it is wrong or asking the "
            "whole question again.",
        ),
    ),
    Situation(
        id="3-clumsy-english",
        targets=("T1", "T4"),
        subject="science",
        age=12,
        steps=(
            step(
                "Floating",
                "question",
                "Explain why ice floats on water.",
                "says ice is less dense than water: the same amount weighs less",
            ),
        ),
        student=("ice is more less heavy for same big so it go up on water",),
        criteria=(
            "The tutor treats the idea (ice is lighter for the same size, less dense) as there or "
            "nearly there, and helps with how to say it, rather than treating the student as not "
            "understanding.",
            "The tutor keeps the thinking asked of the student: it still asks them to explain or "
            "use the idea, and does not switch to an easier question.",
        ),
    ),
    Situation(
        id="4-after-hints",
        targets=("T2",),
        subject="mathematics",
        age=12,
        steps=(
            step("Two steps", "question", "Solve 3x - 4 = 17", "x = 7 with working", "7"),
            step("Practice", "practice", "Solve 5x + 3 = 38", "x = 7 with working", "7"),
        ),
        student=("idk", "add 4?", "3x = 21 so x = 7"),
        criteria=(
            "After the student gets it right with help, the tutor either asks one brief comparable "
            "question for them to do without help, or clearly gives less help on the next "
            "question than before. It does not simply praise and carry on as if the step were "
            "mastered.",
        ),
    ),
    Situation(
        id="5-struggling",
        targets=("T5",),
        subject="history",
        age=12,
        adapt=True,
        memory_learns=(
            "Usually needs help twice before getting a step right.",
            "Finished 0 of 3 lessons.",
        ),
        memory_knows=("History: 2 of 5 steps right.",),
        steps=(
            step(
                "Roads",
                "question",
                "Why did the Romans build roads? Give one reason and explain how it helped them.",
                "gives a reason (the army, trade or control) and explains how roads helped",
            ),
        ),
        student=("not sure",),
        criteria=(
            "Across the tutor's replies, the student is still asked to give a reason and explain "
            "it (the step's own thinking), with support offered such as a choice, a first move or "
            "an example, rather than an easier question that only asks them to name or recall "
            "something.",
        ),
    ),
    Situation(
        id="6-switched-off",
        targets=("T6",),
        subject="mathematics",
        age=14,
        steps=(step("Brackets", "question", "Solve 4(x - 2) = 20", "x = 7 with working", "7"),),
        student=("this is boring", "whatever"),
        criteria=(
            "The tutor checks in briefly on how the student is feeling or what is getting in the "
            "way, rather than only repeating the task.",
            "The tutor does not make the task easier because the student seems switched off.",
        ),
    ),
    Situation(
        id="7-second-language",
        targets=("T4", "T5"),
        subject="science",
        age=13,
        adapt=True,
        memory_learns=(
            "Usually gets a step right on the first try, without help.",
            "Writes short answers and reads in a second language.",
        ),
        memory_knows=("Science: 9 of 9 steps right.",),
        steps=(
            step(
                "Melting",
                "question",
                "What happens to the particles in ice when it melts?",
                "particles gain energy, move more and leave their fixed places",
            ),
        ),
        student=("they move more",),
        criteria=(
            "The tutor uses plain words and short sentences with this student.",
            "The tutor still asks for reasoning or more depth (for example why they move more, or "
            "what gives them the energy), not a simpler question.",
        ),
    ),
    Situation(
        id="8-overload",
        targets=("T3",),
        subject="mathematics",
        age=12,
        steps=(
            step(
                "Shopping",
                "question",
                "Pens cost 45p and pencils 30p. Sam buys 3 pens and some pencils and pays £2.25. "
                "How many pencils did Sam buy, and how much change would Sam get from £5?",
                "3 pencils and £2.75 change",
                "3 pencils, £2.75",
            ),
        ),
        student=("there's too many bits i dont get it",),
        criteria=(
            "The tutor breaks the problem up and asks about just one part first, rather than the "
            "whole problem again.",
        ),
    ),
    Situation(
        id="9-raise-thinking",
        targets=("T7",),
        subject="history",
        age=14,
        adapt=True,
        memory_learns=(
            "Usually gets a step right on the first try, without help.",
            "Gives specific examples without being asked.",
        ),
        memory_knows=("History: steps right first time in 3 lessons.",),
        steps=(
            step(
                "Causes",
                "question",
                "Name two causes of the First World War.",
                "names two causes (alliances, militarism, imperialism, nationalism, the "
                "assassination)",
            ),
            step(
                "Alliances",
                "question",
                "Which two alliances faced each other in 1914?",
                "the Triple Entente and the Triple Alliance",
            ),
        ),
        student=("alliances and the assassination of franz ferdinand",),
        criteria=(
            "At least once, the tutor asks this student for more than recall: to explain, compare, "
            "judge which mattered most, or connect causes, not only for more facts of the same "
            "kind.",
        ),
    ),
)
