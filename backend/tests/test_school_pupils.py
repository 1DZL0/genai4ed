"""The pupils both benches share: the realism filter every written line passes before it is
sent, a canned line for every written move, and the writers. The model is never called here:
the writer's HTTP call is stood in for, and the free mode's writer calls nothing."""

import re

import httpx
import pytest

from app.config import get_settings
from bench import pupils
from bench.pupils import (
    BEATS,
    CANNED,
    FALLBACK,
    Beat,
    CannedWriter,
    Persona,
    PupilWriter,
    beat,
    realistic,
)

URL = "https://openrouter.ai/api/v1/chat/completions"
KEY = "dummy-key-for-the-tests"


def _completion(text: str) -> httpx.Response:
    """What the model sends back for a chat completion whose message is `text`."""
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": text}}]},
        request=httpx.Request("POST", URL),
    )


def _reply(status: int, **kwargs) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", URL), **kwargs)


def _model(monkeypatch, writer: PupilWriter, *replies) -> tuple[list[dict], list[float]]:
    """Stands in for the model: each call gets the next reply, raised when it is an error.
    Returns the requests as they are made, and the waits between tries, which are recorded
    instead of slept."""
    calls: list[dict] = []
    waits: list[float] = []

    async def post(url, **kwargs):
        calls.append(kwargs["json"])
        reply = replies[len(calls) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(writer.client, "post", post)
    monkeypatch.setattr(pupils, "sleep", sleep)
    return calls, waits


@pytest.fixture
async def writer(monkeypatch):
    monkeypatch.setattr(get_settings(), "openrouter_api_key", KEY)
    w = PupilWriter("pupil/model", "Step 1, Percentages: questions: 10% of 50. Answers: 5")
    yield w
    await w.client.aclose()


# ---------- what a pupil could type ----------


def test_a_line_that_gives_the_game_away_is_not_realistic():
    for line in [
        "As an AI I think x = 5",
        "is this a test",
        "im a bot lol",
        "x = 5!",
        "x = 5 \u2014 easy",
        "line one\nline two",
        " ".join(["word"] * 46),
        "",
    ]:
        assert not realistic(line), line
    assert realistic("idk is it 5") and realistic("im so stressed about the maths test on friday")


def test_a_pupil_explaining_an_answer_in_a_sentence_or_two_is_realistic():
    # In the paid run of 22 November, real answers to a poem question ran 24 to 36 words and a
    # 22-word cap swapped most right answers for a canned line that was no answer at all.
    said = (
        'it\'s "lonely as a cloud". he compares himself to a cloud floating on its own, you can'
        " tell its a simile because of the word as, it compares two things"
    )
    assert 30 <= len(said.split()) <= 45
    assert realistic(said)


def test_the_words_that_give_it_away_count_only_as_whole_words():
    # "ai" is inside "said" and "again", "bot" inside "both": none of them gives anything away.
    assert realistic("my teacher said try again") and realistic("is it both of them")
    assert not realistic("im not an ai") and not realistic("ok I believe it is 5")
    assert not realistic("Sorry is it 5") and not realistic("wait this is a test right")


def test_other_names_for_a_machine_give_it_away_and_so_do_plurals():
    for line in [
        "we are all ais here",
        "lol we are just bots",
        "im a chatbot",
        "beep boop im a robot",
        "as a language model i cant",
        "im an a.i. lol",
        "are you an a.i",
    ]:
        assert not realistic(line), line


def test_a_pupil_may_talk_about_a_character_but_never_be_one():
    for line in ["the main character is sad", "the characters feel lonely"]:
        assert realistic(line), line
    # A pupil writing a story may have a character of their own.
    assert realistic("my character is called sam")
    for line in [
        "i am a character in this",
        "im a character lol",
        "I'm a character lol",
        f"I{chr(0x2019)}m a character",
        "im only playing a character",
    ]:
        assert not realistic(line), line


def test_an_apostrophe_neither_hides_a_word_that_gives_it_away_nor_makes_one():
    for line in [
        "the prompt's asking for a letter",
        "the simulation's broken",
        "the bench's wobbly",
        "the test pupil's line",
        "like an assistant's job",
        "is the chatbot's answer right",
        "the robot's voice lol",
        "a language model's answer",
        "the bot's answer",
        f"the bot{chr(0x2019)}s answer",
        "I'm a character",
    ]:
        assert not realistic(line), line
    for line in ["don't know", "its 5 isnt it", "my teacher said try again"]:
        assert realistic(line), line


def test_every_written_move_has_a_canned_line():
    written = [k for k in BEATS]
    assert all(FALLBACK.get(k) and realistic(FALLBACK[k]) for k in written)
    for kind in ("closer", "no_movement", "what_mean", "copied_wrong", "what_remember"):
        assert kind in BEATS


def test_a_canned_wrong_answer_is_too_short_to_pass_for_a_full_one():
    # The free mode's scripted tutor takes a reply of 9 or more words as a full answer.
    for kind in ("wrong", "bare_wrong", "confident_wrong", "copied_wrong"):
        assert len(re.findall(r"\w+", FALLBACK[kind])) < 9, kind


def test_the_fixed_texts_are_the_ones_given():
    assert CANNED["greek"] == "δεν καταλαβαίνω, μπορείς να το πεις πιο απλά;"
    paste = CANNED["long_paste"]
    assert 1400 <= len(paste) <= 1600 and "\n" not in paste


def test_a_move_the_driver_carries_out_has_no_words_and_an_unknown_move_is_refused():
    assert beat("closer") == Beat("closer", BEATS["closer"])
    for kind in ("ask_teacher", "leave", "greek", "long_paste", "button:why_wrong"):
        assert beat(kind) == Beat(kind, ""), kind
        assert kind not in BEATS, kind
    with pytest.raises(KeyError):
        beat("closr")


# ---------- the writers ----------


def test_a_writer_with_no_key_will_not_start(monkeypatch):
    for missing in ("", "  "):
        monkeypatch.setattr(get_settings(), "openrouter_api_key", missing)
        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
            PupilWriter("pupil/model", "Step 1")


async def test_after_three_lines_that_will_not_do_the_canned_line_goes(monkeypatch, writer):
    calls, _ = _model(monkeypatch, writer, *[_completion("As an AI I would say 5")] * 3)
    line, fell_back = await writer.write(Persona("p", "a pupil", []), beat("not_sure"), [])
    assert (line, fell_back) == (FALLBACK["not_sure"], True)
    assert len(calls) == 3


async def test_a_writer_that_keeps_failing_sends_the_canned_line(monkeypatch, writer):
    calls, _ = _model(
        monkeypatch,
        writer,
        httpx.ConnectError("no route"),
        _reply(503, text="busy"),
        _reply(200, json={"error": {"message": "upstream"}}),
    )
    line, fell_back = await writer.write(Persona("p", "a pupil", []), beat("wrong"), [])
    assert (line, fell_back) == (FALLBACK["wrong"], True)
    assert len(calls) == 3


NO_MESSAGE = "no message in the reply"


@pytest.mark.parametrize(
    ("reply", "why", "waits"),
    [
        (httpx.ConnectError("no route"), "ConnectError", [2, 2]),
        (_reply(401), "http 401", [2, 2]),
        (_reply(200, text="<html>busy</html>"), "JSONDecodeError", [2, 2]),
        (_reply(200, json={"error": {"message": "upstream"}}), NO_MESSAGE, [2, 2]),
        # Blank text is no message, just as null is: the same reason, and the same waits.
        (_reply(200, json={"choices": [{"message": {"content": None}}]}), NO_MESSAGE, [2, 2]),
        (_completion(""), NO_MESSAGE, [2, 2]),
        (_completion("   "), NO_MESSAGE, [2, 2]),
        (_completion('" "'), NO_MESSAGE, [2, 2]),
        # A line that will not do is asked for again at once.
        (_completion("As an AI I would say 5"), "unrealistic line", []),
    ],
)
async def test_after_a_fallback_the_writer_keeps_why(monkeypatch, writer, reply, why, waits):
    _, waited = _model(monkeypatch, writer, *[reply] * 3)
    line, fell_back = await writer.write(Persona("p", "a pupil", []), beat("wrong"), [])
    assert (line, fell_back) == (FALLBACK["wrong"], True)
    assert writer.last_failure == why and waited == waits


async def test_only_a_failed_call_with_a_try_still_to_come_waits_2_s(monkeypatch, writer):
    calls, waits = _model(
        monkeypatch,
        writer,
        httpx.ConnectError("no route"),  # fails: wait before the next try
        _completion("As an AI I would say 5"),  # will not do: try again straight away
        _reply(429),  # fails, but it was the last try: nothing to wait for
    )
    line, fell_back = await writer.write(Persona("p", "a pupil", []), beat("wrong"), [])
    assert (line, fell_back) == (FALLBACK["wrong"], True)
    assert len(calls) == 3 and waits == [2]


async def test_a_line_that_will_do_goes_as_the_model_wrote_it(monkeypatch, writer):
    calls, _ = _model(
        monkeypatch,
        writer,
        _completion("Sorry, is it 5?"),
        _completion('"is it 5 because 10% is 5"'),
    )
    lines = [{"who": "agent", "text": "What is 10% of 50?"}, {"who": "student", "text": "hm"}]
    line, fell_back = await writer.write(Persona("p", "a pupil", []), beat("right"), lines)
    assert (line, fell_back) == ("is it 5 because 10% is 5", False)
    assert len(calls) == 2
    # The model is shown the conversation and told the move.
    asked = calls[0]["messages"][1]["content"]
    assert "Tutor: What is 10% of 50?" in asked and "You: hm" in asked
    assert BEATS["right"] in asked


async def test_a_pupil_learning_english_is_written_that_way(monkeypatch, writer):
    calls, _ = _model(monkeypatch, writer, _completion("i no understand"), _completion("idk"))
    await writer.write(Persona("p", "a pupil", [], eal=True), beat("not_sure"), [])
    await writer.write(Persona("q", "a pupil", []), beat("not_sure"), [])
    learning, native = (c["messages"][0]["content"] for c in calls)
    assert "learning English" in learning and "learning English" not in native


async def test_the_free_writer_never_calls_a_model():
    writer = CannedWriter()
    line, fell_back = await writer.write(Persona("p", "a pupil", []), beat("not_sure"), [])
    assert (line, fell_back) == (FALLBACK["not_sure"], True)
    # Its stand-in lines say why, as the model writer's do when it falls back.
    assert writer.last_failure == "free practice run"


async def test_the_free_writer_refuses_a_move_it_has_no_line_for():
    with pytest.raises(KeyError):
        await CannedWriter().write(Persona("p", "a pupil", []), beat("ask_teacher"), [])


def test_the_old_bench_still_reads_the_same_names():
    from bench import run_bench

    assert run_bench.BEATS is BEATS and run_bench.PupilWriter is PupilWriter
