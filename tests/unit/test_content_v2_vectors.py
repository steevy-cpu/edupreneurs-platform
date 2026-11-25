"""Every shared test vector, run against BOTH implementations of the contracts:

* the JSON Schema files in packages/contracts/content (through ``jsonschema``,
  a development dependency), and
* the plain-Python validators and reference scoring in ``edu_api.content``
  (standard library only - what would run in production and in the pack builder).

A vector that one implementation accepts and the other rejects fails here, so
the published schemas and the code cannot drift apart silently. The phone's
implementation is expected to run the same files.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from edu_api.content.blocks import table_width_budget, validate_blocks
from edu_api.content.canonical import canonical_json, is_canonical_json
from edu_api.content.formats import (
    CLIENT_FORMATS_HEADER,
    DEFAULT_CLIENT_FORMATS,
    SUPPORTED_FORMATS,
    negotiate,
    parse_client_formats,
    required_format,
)
from edu_api.content.issues import Issue
from edu_api.content.math_notation import check_math_source
from edu_api.content.questions import validate_question
from edu_api.content.scoring import SCORING_VERSIONS, normalise_short_text, score
from tests.content_fixtures import (
    BLOCK_SCHEMAS,
    QUESTION_SCHEMAS,
    VECTORS,
    cases,
    load_schema,
    load_vectors,
    math_document,
    schema_accepts,
    schema_validator,
)


def by_id(name: str) -> list[Any]:
    return [pytest.param(case, id=case["id"]) for case in cases(name)]


def outcome(issues: list[Issue]) -> dict[str, Any]:
    """Shape the validator's findings like a vector's ``expect`` object."""
    if not issues:
        return {"valid": True}
    layers = {issue.layer for issue in issues}
    assert len(layers) == 1, "the semantic layer must only run on structurally valid input"
    if layers == {"schema"}:
        return {"valid": False, "layer": "schema"}
    return {"valid": False, "layer": "semantic", "rules": sorted({i.rule for i in issues})}


def test_the_vector_files_are_the_expected_set() -> None:
    assert sorted(path.name for path in VECTORS.glob("*.json")) == [
        "canonical-json.json",
        "lesson-blocks.json",
        "math-notation.json",
        "negotiation.json",
        "pack-manifest.json",
        "pack-verify.json",
        "plain-text.json",
        "questions.json",
        "scoring.json",
    ]


# ------------------------------------------------------------------ lesson blocks
@pytest.mark.parametrize("case", by_id("lesson-blocks.json"))
@pytest.mark.parametrize("content_format", SUPPORTED_FORMATS)
def test_lesson_block_vectors(case: dict[str, Any], content_format: int) -> None:
    expected = case["expect"][f"format_{content_format}"]
    document = case["document"]
    assert outcome(validate_blocks(document, content_format)) == expected
    # The JSON Schema is the structural layer: it rejects exactly the 'schema' cases.
    schema_ok = schema_accepts(BLOCK_SCHEMAS[content_format], document)
    assert schema_ok == (expected.get("layer") != "schema")


@pytest.mark.parametrize("case", by_id("lesson-blocks.json"))
def test_required_format_of_lesson_block_vectors(case: dict[str, Any]) -> None:
    if "required_format" not in case:
        return
    assert required_format(case["document"]) == case["required_format"]
    # ... and it really is the smallest format that accepts the document.
    for content_format in SUPPORTED_FORMATS:
        valid = not validate_blocks(case["document"], content_format)
        assert valid == (content_format >= case["required_format"])


def test_every_semantic_block_rule_has_a_vector() -> None:
    seen = {
        rule
        for case in cases("lesson-blocks.json")
        for rule in case["expect"]["format_2"].get("rules", [])
    }
    assert seen >= {
        "keys.unique",
        "table.row_width",
        "table.width_budget",
        "audio.transcript",
        "assets.consistent",
        "assets.image_budget",
    }
    assert [table_width_budget(n) for n in (2, 3, 4)] == [32, 30, 28]


def test_format_1_definitions_are_carried_into_format_2_unchanged() -> None:
    """'Every v1 block stays valid unchanged' - proven on the schema text itself."""
    v1, v2 = load_schema(BLOCK_SCHEMAS[1])["$defs"], load_schema(BLOCK_SCHEMAS[2])["$defs"]
    for name in ("text", "heading", "paragraph", "example", "callout"):
        assert v2[name] == v1[name], name
    assert v2["key"]["pattern"] == v1["key"]["pattern"]
    for name in ("minItems", "maxItems", "type"):
        assert load_schema(BLOCK_SCHEMAS[2])[name] == load_schema(BLOCK_SCHEMAS[1])[name]


# ------------------------------------------------------------------ math notation
@pytest.mark.parametrize("case", by_id("math-notation.json"))
def test_math_notation_vectors(case: dict[str, Any]) -> None:
    expected, document = case["expect"], math_document(case["source"])
    issues = validate_blocks(document, 2)
    schema_ok = schema_accepts(BLOCK_SCHEMAS[2], document)
    if expected["valid"]:
        assert issues == [] and schema_ok
        assert check_math_source(case["source"]) is None
    elif expected["layer"] == "schema":
        assert outcome(issues) == {"valid": False, "layer": "schema"} and not schema_ok
    else:
        assert schema_ok, "a semantic case must pass the structural layer"
        assert [(i.layer, i.rule, i.path) for i in issues] == [
            ("semantic", expected["rule"], "/0/source")
        ]
        assert check_math_source(case["source"]) == expected["rule"]


def test_every_math_rule_has_a_vector() -> None:
    seen = {case["expect"].get("rule") for case in cases("math-notation.json")} - {None}
    assert seen == {
        "math.syntax",
        "math.unknown_command",
        "math.missing_argument",
        "math.unbalanced",
        "math.depth",
        "math.script",
        "math.text",
    }


def test_the_math_checker_is_total_on_arbitrary_input() -> None:
    """Hostile or random text yields a rule code or None - never an exception, never a hang."""
    rng = random.Random(20261124)  # noqa: S311 - deterministic test data, not security
    alphabet = "xy12 +-^_{}[]\\%|,." + "\u00e9\u00d7<>$\n" + "frac sqrt text mathbb"
    for _ in range(4000):
        source = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        result = check_math_source(source)
        assert result is None or result.startswith("math.")
    assert check_math_source("{" * 5000) == "math.depth"
    assert check_math_source("\\frac" * 5000) == "math.missing_argument"
    # Review M2: a root index is a nesting level; no input can exhaust the stack.
    assert check_math_source("\\sqrt[" * 5000 + "x") == "math.depth"
    assert check_math_source("\\sqrt[" * 39 + "x" + "]{x}" * 39) == "math.depth"
    assert check_math_source("x^{" * 5000) == "math.depth"
    for not_text in (None, 1, 1.5, b"x", ["x"], {"x": 1}):
        assert check_math_source(not_text) == "math.syntax"
    # Review M1: called directly (without the structural layer) markup is still refused.
    for markup in ("<script>alert(1)</script>", "\\text{<b>x</b>}", "a<b"):
        assert check_math_source(markup) is not None
        assert validate_blocks(math_document(markup), 2)[0].layer == "schema"
        assert not schema_accepts(BLOCK_SCHEMAS[2], math_document(markup))
    assert check_math_source("a < b") is None


# ------------------------------------------------------------------ questions
@pytest.mark.parametrize("case", by_id("questions.json"))
def test_question_vectors(case: dict[str, Any]) -> None:
    expected = case["expect"]
    assert outcome(validate_question(case["kind"], case["document"])) == expected
    schema_ok = schema_accepts(QUESTION_SCHEMAS[case["kind"]], case["document"])
    assert schema_ok == (expected.get("layer") != "schema")


# ------------------------------------------------------------------ scoring
@pytest.mark.parametrize("case", by_id("scoring.json"))
def test_scoring_vectors(case: dict[str, Any]) -> None:
    kind, expected = case["kind"], dict(case["expect"])
    question = {
        "prompt": {"text": "?"},
        "response_spec": case["response_spec"],
        "answer_key": case["answer_key"],
        "explanation": {"text": "."},
    }
    assert validate_question(kind, question) == [], "scoring vectors use valid questions"
    assert schema_accepts(QUESTION_SCHEMAS[kind], question)

    result = score(kind, case["response_spec"], case["answer_key"], case["response"])
    normalised = expected.pop("normalised_response", None)
    actual = {"status": result.status, "scoring_version": result.scoring_version}
    if result.status == "scored":
        actual |= {"score": result.score, "is_correct": result.is_correct}
        assert result.score in (0, 1) and type(result.score) is int
        assert result.is_correct is (result.score == 1) and result.code is None
    else:
        actual |= {"code": result.code}
        assert result.score is None and result.is_correct is None
    assert actual == expected
    assert result.scoring_version == SCORING_VERSIONS[kind]
    assert result.scoring_version == case["answer_key"]["scoring_version"]

    # A response that does not even have the published shape is never scored.
    response_schema = {
        "$ref": "#/$defs/response",
        "$defs": load_schema(QUESTION_SCHEMAS[kind])["$defs"],
    }
    if (
        not schema_validator(QUESTION_SCHEMAS[kind])
        .evolve(schema=response_schema)
        .is_valid(case["response"])
    ):
        assert result.status == "invalid_response"

    if normalised is not None:
        spec = case["response_spec"]
        assert (
            normalise_short_text(
                case["response"]["text"],
                case_sensitive=spec["case_sensitive"],
                accent_sensitive=spec["accent_sensitive"],
            )
            == normalised
        )


def test_scoring_vectors_cover_every_outcome_of_every_kind() -> None:
    seen = {
        (case["kind"], case["expect"]["status"], case["expect"].get("code"))
        for case in cases("scoring.json")
    }
    assert {
        ("true_false", "invalid_response", "not_a_boolean"),
        ("numeric", "invalid_response", "not_a_number"),
        ("short_text", "invalid_response", "not_text"),
        ("short_text", "invalid_response", "too_long"),
        ("short_text", "invalid_response", "empty"),
    } <= seen
    for kind in SCORING_VERSIONS:
        scores = {c["expect"].get("score") for c in cases("scoring.json") if c["kind"] == kind}
        assert {0, 1} <= scores, kind


def test_scoring_is_total_on_malformed_responses() -> None:
    spec = {"numeric": {"allow_fraction": True}, "true_false": {}}
    spec["short_text"] = {"max_length": 10, "case_sensitive": False, "accent_sensitive": False}
    key = {
        "true_false": {"scoring_version": "true-false-v1", "correct": True},
        "numeric": {"scoring_version": "numeric-v1", "value": "1", "tolerance": "0"},
        "short_text": {"scoring_version": "short-text-v1", "accepted": ["a"]},
    }
    hostile: list[Any] = [None, 1, 1.5, "x", [], {}, {"text": None}, {"text": []}, {"value": {}}]
    hostile += [{"text": "9" * 500}, {"text": "1/" + "0" * 12}, {"a": 1, "b": 2}]
    for kind in SCORING_VERSIONS:
        for response in hostile:
            assert score(kind, spec[kind], key[kind], response).status == "invalid_response"
        # A control character is "some text": never an exception, never a correct answer.
        assert score(kind, spec[kind], key[kind], {"text": "\x00"}).is_correct is not True
    with pytest.raises(ValueError, match="no reference scoring rule"):
        score("mcq", {}, {}, {})


# ------------------------------------------------------------------ negotiation
@pytest.mark.parametrize("case", by_id("negotiation.json"))
def test_negotiation_vectors(case: dict[str, Any]) -> None:
    if case["type"] == "parse_header":
        assert parse_client_formats(case["header"]) == frozenset(case["expect_formats"])
    elif case["type"] == "negotiate":
        assert negotiate(case["client_formats"], case["available_formats"]) == case["expect"]
    else:
        blocks = [{"type": block_type} for block_type in case["block_types"]]
        assert required_format(blocks, case["question_kinds"]) == case["expect"]


def test_negotiation_invariants() -> None:
    assert CLIENT_FORMATS_HEADER == "Edu-Content-Formats"
    assert sorted(DEFAULT_CLIENT_FORMATS) == [1]
    assert SUPPORTED_FORMATS == (1, 2)
    # An app that does not declare format 2 is never offered format 2, whatever exists.
    for available in ([], [1], [2], [1, 2], [1, 2, 3]):
        assert negotiate(parse_client_formats(None), available) in (1, None)
        assert negotiate({1}, available) != 2
    with pytest.raises(ValueError, match="unknown block type"):
        required_format([{"type": "html"}])
    with pytest.raises(ValueError, match="unknown question kind"):
        required_format([], ["matching"])


# ------------------------------------------------------------------ the two implementations agree
def _mutations(rng: random.Random, value: Any) -> Any:
    """One random structural change somewhere inside a JSON value."""
    if isinstance(value, dict) and value and rng.random() < 0.7:
        name = rng.choice(sorted(value))
        changed = dict(value)
        roll = rng.random()
        if roll < 0.2:
            del changed[name]
        elif roll < 0.3:
            changed["extra"] = 1
        else:
            changed[name] = _mutations(rng, value[name])
        return changed
    if isinstance(value, list) and value and rng.random() < 0.7:
        index = rng.randrange(len(value))
        changed_list = list(value)
        roll = rng.random()
        if roll < 0.15:
            del changed_list[index]
        elif roll < 0.3:
            changed_list.append(value[index])
        else:
            changed_list[index] = _mutations(rng, value[index])
        return changed_list
    replacements: list[Any] = [None, True, 0, -1, 7, 10**7, "", "x", "<b>", "a\tb", [], {}, ["x"]]
    replacements += ["y" * 90, "z" * 5000, "A-Z", "0" * 64, "image/png", "audio/mpeg", "math"]
    return rng.choice(replacements)


def test_plain_validators_and_json_schemas_agree_on_mutated_documents() -> None:
    """Randomly damaged documents: both implementations give the same structural verdict
    and the plain validator never raises."""
    rng = random.Random(4242)  # noqa: S311 - deterministic test data, not security
    seeds = [
        c["document"]
        for c in cases("lesson-blocks.json")
        if c["expect"]["format_2"] == {"valid": True}
    ]
    checked = rejected = 0
    for _ in range(3000):
        document = _mutations(rng, rng.choice(seeds))
        for content_format in SUPPORTED_FORMATS:
            issues = validate_blocks(document, content_format)
            structurally_valid = not any(issue.layer == "schema" for issue in issues)
            assert structurally_valid == schema_accepts(BLOCK_SCHEMAS[content_format], document), (
                content_format,
                document,
            )
            checked += 1
            rejected += not structurally_valid
    assert checked == 6000 and 1000 < rejected < checked

    questions = [c for c in cases("questions.json") if c["expect"] == {"valid": True}]
    for _ in range(2000):
        case = rng.choice(questions)
        document = _mutations(rng, case["document"])
        issues = validate_question(case["kind"], document)
        structurally_valid = not any(issue.layer == "schema" for issue in issues)
        assert structurally_valid == schema_accepts(QUESTION_SCHEMAS[case["kind"]], document), (
            case["kind"],
            document,
        )


# ------------------------------------------------------------------ review M4: plain text
def _substituted(node: Any, text: str) -> Any:
    if node == "@TEXT@":
        return text
    if isinstance(node, dict):
        return {name: _substituted(value, text) for name, value in node.items()}
    if isinstance(node, list):
        return [_substituted(item, text) for item in node]
    return node


@pytest.mark.parametrize("case", by_id("plain-text.json"))
def test_plain_text_vectors(case: dict[str, Any]) -> None:
    targets = load_vectors("plain-text.json")["targets"]
    assert len(targets) == 10
    for target in targets:
        document = _substituted(target["document"], case["text"])
        if "kind" in target:
            issues = validate_question(target["kind"], document)
        else:
            issues = validate_blocks(document, 2)
        assert outcome(issues) == case["expect"], target["id"]
        assert schema_accepts(target["schema"], document) == case["expect"]["valid"], target["id"]


def test_plain_text_rule_boundaries_and_scope() -> None:
    """Every forbidden code point is refused, its neighbours are not; v1 blocks are untouched."""
    forbidden = [*range(0x80, 0xA0), *range(0x200B, 0x2010), *range(0x2028, 0x202F)]
    forbidden += [0x2060, *range(0x2066, 0x206A), 0xFEFF, 0xD800, 0xDBFF, 0xDC00, 0xDFFF]
    neighbours = [0x7E, 0xA0, 0x200A, 0x2010, 0x2027, 0x202F, 0x205F, 0x2061, 0x2065, 0x206A]
    neighbours += [0xFEFE, 0xD7FF, 0xE000, 0x1F600]
    target = load_vectors("plain-text.json")["targets"][0]
    for code in forbidden + neighbours:
        document = _substituted(target["document"], f"a{chr(code)}b")
        valid = code in neighbours
        assert (validate_blocks(document, 2) == []) == valid, hex(code)
        assert schema_accepts(target["schema"], document) == valid, hex(code)
    # Owner decision: the four format-1 block types are not tightened, in either format.
    for content_format in SUPPORTED_FORMATS:
        old = [{"key": "p", "type": "paragraph", "text": "a\u202eb\u200b"}]
        assert validate_blocks(old, content_format) == []
        assert schema_accepts(BLOCK_SCHEMAS[content_format], old)


# ------------------------------------------------------------------ review L1: canonical JSON
@pytest.mark.parametrize("case", by_id("canonical-json.json"))
def test_canonical_json_vectors(case: dict[str, Any]) -> None:
    data = case["utf8"].encode("utf-8", "surrogatepass")
    assert is_canonical_json(data) is case["expect"]["canonical"]


def test_integral_floats_are_not_integers_in_the_validators() -> None:
    """Review L1. JSON Schema calls 10.0 an integer; the contracts do not (README). The
    plain validators refuse it, and so does the canonical form every pack object must have."""
    image = _substituted(load_vectors("plain-text.json")["targets"][0]["document"], "x")
    for name in ("bytes", "width", "height"):
        for value in (10.0, 1e2):
            document = [{**image[0], "asset": {**image[0]["asset"], name: value}}]
            assert outcome(validate_blocks(document, 2)) == {"valid": False, "layer": "schema"}
            with pytest.raises(TypeError):
                canonical_json(document)


# ------------------------------------------------------------------ review L3: no raw exceptions
def test_required_format_and_canonical_json_raise_only_their_documented_errors() -> None:
    for odd in (["math"], {"a": 1}, 7, None, 1.5, True):
        with pytest.raises(ValueError, match="unknown block type"):
            required_format([{"type": odd}])
        if odd != "mcq":
            with pytest.raises(ValueError, match="unknown question kind"):
                required_format([], [odd])  # type: ignore[list-item]
    with pytest.raises(ValueError, match="unknown block type"):
        required_format(["paragraph"])  # type: ignore[list-item]
    for text in ("a\ud800", "\udfff", "a\ud800b"):
        with pytest.raises(TypeError, match="lone surrogate"):
            canonical_json({"t": text})
        assert not is_canonical_json(('{"t":"' + text + '"}').encode("utf-8", "surrogatepass"))
    deep: Any = []
    for _ in range(100_000):
        deep = [deep]
    with pytest.raises(TypeError):
        canonical_json(deep)
