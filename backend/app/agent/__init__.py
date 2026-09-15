"""The class agent.

One agent, working with the teacher and with every student in a lesson. What it
is shown differs by conversation, and `context` is where that is decided: a
student's agent sees the lesson brief, the teacher's rules and that student's
own record, and nothing else.

    teacher -> agent (design) -> brief, materials, rules
            -> agent (student) <-> student
            -> assessments, signals, evidence
            -> agent (classroom) -> teacher
"""
