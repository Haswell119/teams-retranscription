from __future__ import annotations

from collections.abc import Sequence

from scipy.optimize import linear_sum_assignment


def minimum_cost_assignment(costs: Sequence[Sequence[float]]) -> tuple[tuple[int, int], ...]:
    return _assign(costs, maximize=False)


def maximum_gain_assignment(gains: Sequence[Sequence[float]]) -> tuple[tuple[int, int], ...]:
    return _assign(gains, maximize=True)


def _assign(matrix: Sequence[Sequence[float]], *, maximize: bool) -> tuple[tuple[int, int], ...]:
    if not matrix or not matrix[0]:
        return ()
    rows, columns = linear_sum_assignment(matrix, maximize=maximize)
    return tuple((int(row), int(column)) for row, column in zip(rows, columns, strict=True))
