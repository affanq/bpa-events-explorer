import pytest

from bpa_app.data import (
    NormalizationError,
    clean_str,
    normalize_division,
    normalize_participation,
    normalize_type,
    parse_bool,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("High School", ["HS"]),
        ("Highschool", ["HS"]),
        ("College", ["College"]),
        ("High School/College", ["HS", "College"]),
        ("Highschool/College", ["HS", "College"]),
        ("Middle School", ["MS"]),
        ("College/HS/MS", ["MS", "HS", "College"]),
        (" High School ", ["HS"]),
    ],
)
def test_normalize_division(raw: str, expected: list[str]) -> None:
    assert normalize_division(raw) == expected


@pytest.mark.parametrize("raw", ["Grad School", "", None])
def test_normalize_division_rejects_unknown_and_names_event(raw: str | None) -> None:
    with pytest.raises(NormalizationError, match="Event 123"):
        normalize_division(raw, "123")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Testing", ["Testing"]),
        ("Testing ", ["Testing"]),
        ("Judged", ["Judged"]),
        ("Testing/Judged", ["Testing", "Judged"]),
    ],
)
def test_normalize_type(raw: str, expected: list[str]) -> None:
    assert normalize_type(raw) == expected


def test_normalize_type_rejects_unknown() -> None:
    with pytest.raises(NormalizationError, match="Event 7"):
        normalize_type("Written", "7")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Individual", "Individual"),
        ("IndividuaI", "Individual"),  # typo in the workbook (capital i)
        ("Team", "Team"),
        ("Individual ", "Individual"),
    ],
)
def test_normalize_participation(raw: str, expected: str) -> None:
    assert normalize_participation(raw) == expected


def test_normalize_participation_rejects_unknown() -> None:
    with pytest.raises(NormalizationError, match="Event 490"):
        normalize_participation("Group", "490")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("TRUE", True),
        ("FALSE", False),
        ("True", True),
        ("false", False),
        (True, True),
        (False, False),
        ("", None),
        ("  ", None),
        (None, None),
        (float("nan"), None),
    ],
)
def test_parse_bool(raw: object, expected: bool | None) -> None:
    assert parse_bool(raw) is expected


def test_parse_bool_rejects_unknown() -> None:
    with pytest.raises(NormalizationError):
        parse_bool("maybe", "100")


def test_clean_str_strips_event_id_whitespace() -> None:
    assert clean_str("V15 ") == "V15"
    assert clean_str("  ") is None
    assert clean_str(None) is None
