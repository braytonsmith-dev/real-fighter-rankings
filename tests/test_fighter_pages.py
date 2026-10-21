"""
Tests for mmalab.fighter_pages: the slug rules (accents, apostrophes, periods, hyphens, the parenthetical
suffixes used for same-name fighters, and collisions), one rendered page on a synthetic profile, and the index.
Everything here is synthetic; nothing reads the repository data.
"""
from __future__ import annotations

import html
import re

import pytest

from mmalab import fighter_pages as fp
from mmalab.fighter_pages import DISCLAIMER, render, render_index, slug, unique_slugs

EM_DASH = chr(0x2014)


# ---------------------------------------------------------------------------
# slugs

class TestSlug:
    @pytest.mark.parametrize("name, expected", [
        ("Max Holloway", "max-holloway"),
        ("Sean O'Malley", "sean-omalley"),
        ("Da'Mon Blackshear", "damon-blackshear"),
        ("Khalil Rountree Jr.", "khalil-rountree-jr"),
        ("Kai Kara-France", "kai-kara-france"),
        ("Abdul-Kareem Al-Selwady", "abdul-kareem-al-selwady"),
        ("Bruno Silva (Blindado)", "bruno-silva-blindado"),
        ("Tony Johnson (265 lbs)", "tony-johnson-265-lbs"),
        ("Mike Davis (c8661e20)", "mike-davis-c8661e20"),
        ("José Aldo", "jose-aldo"),
        ("Jiří Procházka", "jiri-prochazka"),
        ("Søren Ølsen", "soren-olsen"),
        ("Łukasz Brzeski", "lukasz-brzeski"),
        ("Sean O’Malley", "sean-omalley"),       # curly apostrophe
        ("  Double  Space ", "double-space"),
    ])
    def test_known_names(self, name: str, expected: str) -> None:
        assert slug(name) == expected

    def test_ascii_lower_case_hyphens_only(self) -> None:
        for name in ["Ñandú Ébène", "J.T Taylor", "He-Man Gipson", "Raquel Pa'aluhi", "Dos Caras Jr."]:
            s = slug(name)
            assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", s), s

    def test_stable(self) -> None:
        assert slug("Charles Oliveira") == slug("Charles Oliveira")

    def test_empty_falls_back(self) -> None:
        assert slug("") == "fighter"
        assert slug("???") == "fighter"

    def test_unique_slugs_suffix_collisions_deterministically(self) -> None:
        names = ["Sean O'Malley", "Sean OMalley", "Sean O’Malley", "Max Holloway"]
        out = unique_slugs(names)
        assert out["Max Holloway"] == "max-holloway"
        # the three spellings collide on sean-omalley; sorted order decides who keeps the plain slug
        got = sorted(out[n] for n in names[:3])
        assert got == ["sean-omalley", "sean-omalley-2", "sean-omalley-3"]
        assert len(set(out.values())) == len(names)
        assert unique_slugs(reversed(names)) == out      # input order does not matter

    def test_unique_slugs_keeps_suffixed_same_name_fighters_apart(self) -> None:
        out = unique_slugs(["Bruno Silva", "Bruno Silva (Blindado)"])
        assert out == {"Bruno Silva": "bruno-silva", "Bruno Silva (Blindado)": "bruno-silva-blindado"}


# ---------------------------------------------------------------------------
# a synthetic profile

def board_entry(**over) -> dict:
    base = {"label": "#2", "rank": 2, "champion": False, "interim": False, "reserved": False, "band": "2-3",
            "score": 1.55, "rating_term": 0.92, "ledger_term": 0.63, "form_penalty": 0.0, "rating": 1872.0,
            "rating_raw": 1872.0, "inactivity_penalty": 0.0, "injury": False, "rd": 105.0, "ufc_bouts": 33,
            "last5": "3-2", "streak": "W1", "days_since": 99, "last_fight": "2026-07-11", "quality_wins": 7.4,
            "ledger_detail": "+8.4 QW +0.0 proof -1.0 blowout -0.0 weak", "entrenched": True, "quality_wins_15y": 17,
            "top10_wins_15y": 15, "top15_wins_15y": 15, "placement": "score order #1; head-to-head -> #2",
            "division_source": "fight record", "rating_order": 1, "division_size": 103, "champion_rating": 1740.0,
            "ko_risk": 0.0}
    base.update(over)
    return base


def stat(value, pct) -> dict:
    return {"value": value, "pct": pct}


@pytest.fixture
def profile() -> dict:
    stats = {c: stat(1.0, 50) for c in fp.STAT_COLS}
    stats.update({"slpm": stat(6.92, 93), "sapm": stat(4.6, 63), "sig_acc": stat(0.48, 52), "sig_def": stat(0.59, 83),
                  "ko_losses": stat(1.0, 61), "sub_losses": stat(1.0, 82), "cum_sig_absorbed": stat(2457.0, 100),
                  "age": stat(34.9, 75), "debut_age": stat(20.2, 1), "ufc_years": stat(14.7, 94), "n_bouts": stat(33.0, 96),
                  "minutes": stat(534.0, 100), "finish_rate_for": stat(None, None)})
    dates = ["2023-10-06", "2024-04-12", "2025-01-17", "2026-10-17"]
    return {
        "name": "Test O'Fighter <Jr.>", "slug": "test-ofighter-jr", "division": "Lightweight", "as_of": "2026-10-17",
        "last_bout": "2026-07-11", "snapshot_dates": dates,
        "v10": board_entry(), "v11": board_entry(label="#3", rank=3, score=1.52, placement="score order #1; placement rules -> #3"),
        "tape": {"age": 34.9, "dob": "1991-12-04", "height_in": 71.0, "reach_in": 69.0, "stance": "Orthodox"},
        "stats": stats, "style": "striker", "td_rate": 0.4, "last_ko_loss_days": 722.0, "ko_losses_3y": 1,
        "bouts": [
            {"date": "2026-07-11", "event": "UFC 329: A vs. B", "division": "Welterweight", "opponent": "Some Opponent",
             "opponent_slug": "some-opponent", "opp_rank": "unranked", "result": "W", "method": "KO/TKO", "round": 1,
             "time": "1:09", "title_fight": False, "p": 0.88},
            {"date": "2026-03-07", "event": "UFC 326: C vs. D", "division": "Lightweight", "opponent": "Other & Co",
             "opponent_slug": None, "opp_rank": "#3", "result": "L", "method": "unanimous decision", "round": 5,
             "time": "5:00", "title_fight": True, "p": 0.68},
            {"date": "2025-07-19", "event": "UFC 318", "division": "Lightweight", "opponent": "Third Man",
             "opponent_slug": None, "opp_rank": "n/a", "result": "NC", "method": "no contest", "round": None,
             "time": None, "title_fight": False, "p": None},
        ],
        "rank_history": [{"date": dates[0], "position": 1, "division": "Featherweight"},
                         {"date": dates[1], "position": 0, "division": "Featherweight"},
                         {"date": dates[3], "position": 2, "division": "Lightweight"}],
        "rating_history": [{"date": "2012-02-04", "rating": 1500.0, "opponent": "Debut Foe", "result": "L"},
                           {"date": "2026-07-11", "rating": 1865.2, "opponent": "Some Opponent", "result": "W"}],
    }


class TestRender:
    def test_page_shape_and_disclaimer(self, profile: dict) -> None:
        page = render(profile)
        assert page.startswith("<!doctype html>")
        assert page.rstrip().endswith("</html>")
        assert page.count("<html") == page.count("</html>") == 1
        assert page.count("<body>") == page.count("</body>") == 1
        for tag in ("table", "svg", "h2", "ul", "p", "tr", "td", "a"):
            assert len(re.findall(rf"<{tag}[\s>]", page)) == page.count(f"</{tag}>"), tag
        assert html.escape(DISCLAIMER) in page
        assert "<script" not in page
        assert EM_DASH not in page

    def test_header_carries_both_ranks_and_measurement_note(self, profile: dict) -> None:
        page = render(profile)
        assert "REAL v1.0 (registered) #2; v1.1 (shadow) #3" in page
        assert "Weight band 2-3" in page
        assert "Rating 1,872, deviation 105: measured from 33 UFC bouts; a one-bout newcomer sits near 290" in page
        assert "Age 34 (born 1991-12-04)" in page
        assert "Height 5 ft 11 in (180 cm)" in page
        assert "99 days since last bout (2026-07-11)" in page
        assert "Last five 3-2" in page and "Streak W1" in page
        assert "Provisional" not in page

    def test_names_are_escaped(self, profile: dict) -> None:
        page = render(profile)
        assert "Test O&#x27;Fighter &lt;Jr.&gt;" in page
        assert "<Jr.>" not in page
        assert "Other &amp; Co" in page

    def test_why_sentence(self, profile: dict) -> None:
        page = render(profile)
        assert "Why he is ranked here" in page
        assert ("Rating 1,872 is the division&#x27;s highest; the ledger stands at +7.4 (+8.4 from quality wins, less 1.0 for "
                "blowout losses; losses count for three years); 17 quality wins in 15 years, 15 over top-10 opponents, "
                "which makes him entrenched; no form penalty (3-2 last five).") in page
        assert "score order put him at #1; the head-to-head rule" in page and "placed him #2" in page
        assert "Shadow board v1.1" in page

    def test_last_bout_rows(self, profile: dict) -> None:
        page = render(profile)
        assert "Last ten bouts" not in page and "All 3 UFC bouts" in page
        row = re.search(r"<tr><td class='nw'>2026-07-11</td>.*?</tr>", page).group(0)
        assert "<a href='some-opponent.html'>Some Opponent</a>" in row
        assert "unranked" in row and "class='up'>W<" in row and "KO/TKO" in row and "1 (1:09)" in row and "88%" in row
        title_row = re.search(r"<tr><td class='nw'>2026-03-07</td>.*?</tr>", page).group(0)
        assert "(title)" in title_row and "#3" in title_row and "class='down'>L<" in title_row
        nc_row = re.search(r"<tr><td class='nw'>2025-07-19</td>.*?</tr>", page).group(0)
        assert "class='band'>NC<" in nc_row and "<td class='num'></td>" in nc_row

    def test_statistics_with_percentiles_and_charts(self, profile: dict) -> None:
        page = render(profile)
        assert "6.92" in page and "(93rd percentile at Lightweight)" in page
        assert "(100th percentile at Lightweight)" in page and "2,457" in page
        assert "1 <span class='band'>(last 2024-10-26, 722 days ago)</span>" in page
        assert "n/a" in page                                   # finish rate missing
        assert "striker <span class='band'>(0.4 takedown attempts per 15 min" in page
        assert page.count("<svg") == 2
        assert "Listed at Featherweight, then Lightweight" in page
        assert "Absent from 1 of 4 snapshots" in page
        assert ">1,865<" in page                              # rating end label

    def test_context_flags(self, profile: dict) -> None:
        page = render(profile)
        assert "Age band: 33 to 35 (age 34)" in page
        assert "64% of bouts when under 30, 59% at 30 to 32, 57% at 33 to 35 and 42 to 46% at 36 and over" in page
        assert "not a forecast for him" in page
        assert "Not raised: no KO/TKO loss in the last 90 days; last bout within 12 months; 33 UFC bouts" in page

    def test_flags_raise_when_warranted(self, profile: dict) -> None:
        profile["division"] = "Women's Strawweight"
        profile["v10"].update(days_since=400, ufc_bouts=2, rd=250.0, injury=True)
        profile["last_ko_loss_days"] = 20.0
        profile["tape"]["age"] = 38.2
        page = render(profile)
        assert "Why she is ranked here" in page
        assert "not a forecast for her" in page
        assert "Provisional: 2 UFC bouts" in page
        assert "Layoff over 12 months: 400 days since the last bout (2026-07-11), documented as an injury." in page
        assert "Recent KO/TKO loss: 20 days ago" in page and "Ringside Physicians" in page
        assert "Age band: 36 and over (age 38)" in page
        assert "Not raised" not in page

    def test_title_holder_and_penalty_wording(self, profile: dict) -> None:
        profile["v10"].update(label="champion", rank=0, champion=True, band=None, placement="title holder",
                              inactivity_penalty=24.0, rating_raw=1896.0, days_since=449)
        profile["v11"] = None
        page = render(profile)
        assert "REAL v1.0 (registered) champion; not on the v1.1 shadow board" in page
        assert "Weight band" not in page
        assert "after an inactivity penalty of 24 points for 449 days without a bout" in page
        assert "he holds the title and sits above the numbered board" in page
        assert "raw 1,896 less inactivity penalty 24" in page

    def test_missing_pieces_do_not_break_the_page(self, profile: dict) -> None:
        profile.update(bouts=[], rank_history=[], rating_history=[], td_rate=None, last_ko_loss_days=None)
        profile["tape"] = {"age": None, "dob": None, "height_in": None, "reach_in": None, "stance": None}
        profile["stats"] = {c: stat(None, None) for c in fp.STAT_COLS}
        page = render(profile)
        assert "No UFC bouts in the data" in page
        assert "No board snapshots include this fighter" in page
        assert "No predictive rating history" in page
        assert "Age unknown" in page and "Height unknown" in page
        assert EM_DASH not in page


class TestIndex:
    def test_index_lists_every_profile_grouped_by_division(self, profile: dict) -> None:
        other = dict(profile, name="Aaron Zed", slug="aaron-zed", division="Heavyweight",
                     v10=board_entry(label="champion", champion=True, rank=0), v11=None)
        third = dict(profile, name="Zoe Abbot", slug="zoe-abbot", division="Lightweight")
        fourth = dict(profile, name="Raul Rosas Jr.", slug="raul-rosas-jr", division="Lightweight")
        page = render_index([profile, other, third, fourth], "2026-10-17")
        assert html.escape(DISCLAIMER) in page
        assert "4 fighters on the registered board" in page
        assert page.index("<h2>Lightweight</h2>") < page.index("<h2>Heavyweight</h2>")      # board order, not alphabetical
        assert "<a href='aaron-zed.html'>Aaron Zed</a> <span class='band'>v1.0 champion · v1.1 not listed</span>" in page
        assert "<a href='test-ofighter-jr.html'>Test O&#x27;Fighter &lt;Jr.&gt;</a> <span class='band'>v1.0 #2 · v1.1 #3</span>" in page
        # sorted by surname inside a division, ignoring a generational suffix: Abbot, O'Fighter, Rosas
        assert page.index("zoe-abbot.html") < page.index("test-ofighter-jr.html") < page.index("raul-rosas-jr.html")
        assert EM_DASH not in page
        assert page.count("<ul") == page.count("</ul>") == 2


def test_module_exposes_the_wiring_surface() -> None:
    assert callable(fp.slug) and callable(fp.main) and callable(fp.build_profiles)
    assert fp.PAGES.name == "fighters" and fp.PAGES.parent == fp.DOCS
