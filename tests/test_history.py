"""Unit tests for the pure helpers in mmalab.history: wilson() and board_position()."""
from __future__ import annotations

import pandas as pd
import pytest

from mmalab.history import board_position, wilson

Z = 1.96


class TestWilson:
    def test_empty_sample_has_no_interval(self) -> None:
        assert wilson(0, 0) is None

    @pytest.mark.parametrize("n", [1, 5, 30, 1000])
    def test_zero_successes(self, n: int) -> None:
        lo, hi = wilson(0, n)
        assert lo == 0.0
        assert hi == pytest.approx(Z * Z / (n + Z * Z), abs=5e-4)

    @pytest.mark.parametrize("n", [1, 5, 30, 1000])
    def test_all_successes(self, n: int) -> None:
        lo, hi = wilson(n, n)
        assert hi == 1.0
        assert lo == pytest.approx(n / (n + Z * Z), abs=5e-4)

    @pytest.mark.parametrize("k, n", [(3, 10), (17, 40), (250, 400), (1, 2)])
    def test_mirror_symmetry(self, k: int, n: int) -> None:
        lo, hi = wilson(k, n)
        lo2, hi2 = wilson(n - k, n)
        assert lo2 == pytest.approx(1 - hi, abs=1.5e-3)      # both ends are rounded to 3 decimals
        assert hi2 == pytest.approx(1 - lo, abs=1.5e-3)

    def test_even_split_is_centred_and_narrows_with_n(self) -> None:
        lo, hi = wilson(5, 10)
        assert lo == pytest.approx(1 - hi, abs=1.5e-3)
        assert lo < 0.5 < hi
        widths = [hi - lo for lo, hi in (wilson(n // 2, n) for n in (10, 100, 1000))]
        assert widths == sorted(widths, reverse=True)

    @pytest.mark.parametrize("k, n", [(0, 7), (7, 7), (2, 9), (60, 100)])
    def test_bounds_contain_the_point_estimate_inside_unit_interval(self, k: int, n: int) -> None:
        lo, hi = wilson(k, n)
        assert 0.0 <= lo <= k / n + 1e-3
        assert k / n - 1e-3 <= hi <= 1.0

    def test_wider_z_gives_wider_interval(self) -> None:
        lo95, hi95 = wilson(30, 50)
        lo99, hi99 = wilson(30, 50, z=2.576)
        assert lo99 < lo95 and hi99 > hi95


class TestBoardPosition:
    def test_champion_is_zero(self) -> None:
        assert board_position({"champion": True, "interim": False, "reserved": False, "rank": 0}) == 0

    def test_interim_and_reserved_sit_with_the_title_holder(self) -> None:
        assert board_position({"champion": False, "interim": True, "reserved": False, "rank": 0}) == 0
        assert board_position({"champion": False, "interim": False, "reserved": True, "rank": 0}) == 0

    def test_contender_keeps_its_rank(self) -> None:
        assert board_position({"champion": False, "interim": False, "reserved": False, "rank": 7}) == 7
        assert board_position({"champion": False, "rank": 12.0}) == 12     # optional keys may be absent

    def test_works_row_wise_on_a_board_frame(self) -> None:
        board = pd.DataFrame({
            "fighter": ["Champ", "Interim", "One", "Two"],
            "champion": [True, False, False, False],
            "interim": [False, True, False, False],
            "reserved": [False] * 4,
            "rank": [0, 0, 1, 2],
        })
        assert board.apply(board_position, axis=1).tolist() == [0, 0, 1, 2]
