"""As-of readers for the five hand-kept roster files (resume_board.*_as_of).

Each test writes a small YAML file into a temporary config directory and points resume_board.CFG at it,
so the real config/ is never read. Covers the since/until boundaries, the old undated format and its
deprecation note, old-style lines inside a new-format list, and the validation errors.
"""
from pathlib import Path

import pandas as pd
import pytest

from mmalab import resume_board as rb


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(rb, "CFG", tmp_path)
    monkeypatch.setattr(rb, "_LEGACY_NOTED", set())
    return tmp_path


def write(cfg: Path, name: str, text: str) -> None:
    (cfg / name).write_text(text)


DATED_LAYOFFS = """
- {fighter: "Open Ended", since: 2026-01-10, until: null, reason: "surgery", source: "https://example.org/a"}
- {fighter: "Closed Window", since: 2026-02-01, until: 2026-03-01, reason: "healed", source: "https://example.org/b"}
"""


def test_since_boundary_inclusive_until_exclusive(cfg):
    write(cfg, "layoffs.yaml", DATED_LAYOFFS)
    assert rb.layoffs_as_of(pd.Timestamp("2026-01-09")) == set()
    assert rb.layoffs_as_of(pd.Timestamp("2026-01-10")) == {"Open Ended"}           # since <= as_of applies
    assert rb.layoffs_as_of(pd.Timestamp("2026-01-31")) == {"Open Ended"}
    assert rb.layoffs_as_of(pd.Timestamp("2026-02-01")) == {"Open Ended", "Closed Window"}
    assert rb.layoffs_as_of(pd.Timestamp("2026-02-28")) == {"Open Ended", "Closed Window"}
    assert rb.layoffs_as_of(pd.Timestamp("2026-03-01")) == {"Open Ended"}           # as_of < until: ends on until
    assert rb.layoffs_as_of(pd.Timestamp("2030-12-31")) == {"Open Ended"}           # until null never ends


def test_as_of_accepts_strings_and_dates(cfg):
    write(cfg, "layoffs.yaml", DATED_LAYOFFS)
    assert rb.layoffs_as_of("2026-02-15") == {"Open Ended", "Closed Window"}
    assert rb.layoffs_as_of(pd.Timestamp("2026-02-15").date()) == {"Open Ended", "Closed Window"}


def test_exclusions_with_return_window(cfg):
    write(cfg, "roster_exclusions.yaml", """
- {fighter: "Gone For Good", since: 2025-07-20, until: null, reason: "retired", source: "https://example.org"}
- {fighter: "Came Back", since: 2026-03-29, until: 2026-09-09, reason: "retired, then returned", source: "https://example.org"}
""")
    assert rb.exclusions_as_of(pd.Timestamp("2025-07-19")) == set()
    assert rb.exclusions_as_of(pd.Timestamp("2026-03-28")) == {"Gone For Good"}
    assert rb.exclusions_as_of(pd.Timestamp("2026-06-01")) == {"Gone For Good", "Came Back"}
    assert rb.exclusions_as_of(pd.Timestamp("2026-09-09")) == {"Gone For Good"}
    assert rb.exclusions_as_of(pd.Timestamp("2026-10-18")) == {"Gone For Good"}


def test_division_overrides_mapping_and_later_entry_wins(cfg):
    write(cfg, "division_overrides.yaml", """
- {fighter: "Mover", division: "Middleweight", since: 2024-01-01, until: 2026-02-27, reason: "first move", source: "s"}
- {fighter: "Mover", division: "Heavyweight", since: 2026-02-27, until: null, reason: "second move", source: "s"}
- {fighter: "Stayer", division: "Welterweight", since: 2026-07-19, until: null, reason: "one-off at 185", source: "s"}
""")
    assert rb.division_overrides_as_of(pd.Timestamp("2023-12-31")) == {}
    assert rb.division_overrides_as_of(pd.Timestamp("2025-06-01")) == {"Mover": "Middleweight"}
    assert rb.division_overrides_as_of(pd.Timestamp("2026-02-27")) == {"Mover": "Heavyweight"}
    assert rb.division_overrides_as_of(pd.Timestamp("2026-08-01")) == {"Mover": "Heavyweight", "Stayer": "Welterweight"}


def test_reserved_and_interim_are_division_keyed(cfg):
    write(cfg, "reserved.yaml", """
- {division: "Heavyweight", fighter: "Hurt Champ", since: 2026-09-14, until: null, reason: "vacated, injury", source: "s"}
""")
    write(cfg, "interim_champions.yaml", """
- {division: "Heavyweight", fighter: "Stand In", since: 2026-06-15, until: 2026-09-20, reason: "interim belt", source: "s"}
""")
    assert rb.reserved_as_of(pd.Timestamp("2026-09-13")) == {}
    assert rb.reserved_as_of(pd.Timestamp("2026-09-14")) == {"Heavyweight": "Hurt Champ"}
    assert rb.interim_as_of(pd.Timestamp("2026-06-14")) == {}
    assert rb.interim_as_of(pd.Timestamp("2026-06-15")) == {"Heavyweight": "Stand In"}
    assert rb.interim_as_of(pd.Timestamp("2026-09-19")) == {"Heavyweight": "Stand In"}
    assert rb.interim_as_of(pd.Timestamp("2026-09-20")) == {}


def test_old_mapping_format_applies_to_every_date_with_one_note(cfg, capsys):
    write(cfg, "layoffs.yaml", "Old Timer: knee surgery (somewhere.com)\nOther Guy: back\n")
    write(cfg, "division_overrides.yaml", "Old Mover: Heavyweight   # moved up\n")
    write(cfg, "reserved.yaml", "Heavyweight: Old Champ\n")
    assert rb.layoffs_as_of(pd.Timestamp("1999-01-01")) == {"Old Timer", "Other Guy"}
    assert rb.layoffs_as_of(pd.Timestamp("2099-01-01")) == {"Old Timer", "Other Guy"}
    assert rb.division_overrides_as_of(pd.Timestamp("2026-10-18")) == {"Old Mover": "Heavyweight"}
    assert rb.reserved_as_of(pd.Timestamp("2026-10-18")) == {"Heavyweight": "Old Champ"}
    out = capsys.readouterr().out
    assert out.count("[layoffs.yaml] deprecated") == 1          # noted once per file, not once per call
    assert out.count("[division_overrides.yaml] deprecated") == 1
    assert out.count("[reserved.yaml] deprecated") == 1


def test_old_style_line_inside_new_list_is_always_in_effect(cfg, capsys):
    write(cfg, "roster_exclusions.yaml", """
- {fighter: "Dated Exit", since: 2026-02-11, until: null, reason: "released", source: "s"}
- Undated Exit: retired last week
""")
    assert rb.exclusions_as_of(pd.Timestamp("2020-01-01")) == {"Undated Exit"}
    assert rb.exclusions_as_of(pd.Timestamp("2026-02-11")) == {"Dated Exit", "Undated Exit"}
    assert "[roster_exclusions.yaml] deprecated" in capsys.readouterr().out


def test_single_dated_entry_without_leading_dash(cfg):
    write(cfg, "reserved.yaml", 'division: "Heavyweight"\nfighter: "Solo"\nsince: 2026-09-14\nuntil: null\nreason: "r"\nsource: "s"\n')
    assert rb.reserved_as_of(pd.Timestamp("2026-09-13")) == {}
    assert rb.reserved_as_of(pd.Timestamp("2026-09-14")) == {"Heavyweight": "Solo"}


def test_missing_or_empty_file_means_no_entries(cfg):
    assert rb.layoffs_as_of(pd.Timestamp("2026-10-18")) == set()
    write(cfg, "interim_champions.yaml", "# nothing yet\n{}\n")
    assert rb.interim_as_of(pd.Timestamp("2026-10-18")) == {}
    write(cfg, "reserved.yaml", "# nothing yet\n")
    assert rb.reserved_as_of(pd.Timestamp("2026-10-18")) == {}


def test_new_format_entry_without_since_is_an_error(cfg):
    write(cfg, "layoffs.yaml", '- {fighter: "No Date", reason: "hurt", source: "s"}\n')
    with pytest.raises(ValueError, match="needs a 'since' date"):
        rb.layoffs_as_of(pd.Timestamp("2026-10-18"))


def test_bad_date_and_missing_name_are_errors(cfg):
    write(cfg, "layoffs.yaml", '- {fighter: "Bad Date", since: "soon", until: null, reason: "r", source: "s"}\n')
    with pytest.raises(ValueError, match="'since' must be a date"):
        rb.layoffs_as_of(pd.Timestamp("2026-10-18"))
    write(cfg, "reserved.yaml", '- {division: "Heavyweight", since: 2026-09-14, until: null, reason: "r", source: "s"}\n')
    with pytest.raises(ValueError, match="has no 'fighter'"):
        rb.reserved_as_of(pd.Timestamp("2026-10-18"))


def test_missing_source_is_reported_but_still_applies(cfg, capsys):
    write(cfg, "layoffs.yaml", '- {fighter: "No Source", since: 2026-01-01, until: null, reason: "r"}\n')
    assert rb.layoffs_as_of(pd.Timestamp("2026-10-18")) == {"No Source"}
    assert "has no source" in capsys.readouterr().out


def test_real_config_files_parse_and_hold_dated_entries():
    """The committed files load in the new format; today's state is non-empty where expected."""
    today = pd.Timestamp("2026-10-18")
    assert rb.layoffs_as_of(today) >= {"Petr Yan", "Tom Aspinall", "Valentina Shevchenko", "Kayla Harrison"}
    assert "Dustin Poirier" in rb.exclusions_as_of(today)
    assert "Niko Price" not in rb.exclusions_as_of(today)
    assert "Niko Price" in rb.exclusions_as_of(pd.Timestamp("2026-06-01"))
    assert rb.division_overrides_as_of(today)["Alex Pereira"] == "Heavyweight"
    assert rb.reserved_as_of(today)["Heavyweight"] == "Tom Aspinall"
    assert rb.interim_as_of(today) == {}
    assert rb.interim_as_of(pd.Timestamp("2026-08-01")) == {"Heavyweight": "Ciryl Gane"}
    for name in ("layoffs.yaml", "roster_exclusions.yaml", "division_overrides.yaml", "reserved.yaml",
                 "interim_champions.yaml"):
        raw = rb._yaml(name)
        assert isinstance(raw, list) and raw, name
        for e in raw:
            assert e.get("since") and e.get("source"), (name, e)
