from hansard.domain.matching import maximum_weight_assignment, minimum_cost_assignment


def test_square_matrix_finds_optimum():
    cost = [[4, 1, 3], [2, 0, 5], [3, 2, 2]]
    pairs = minimum_cost_assignment(cost)
    assert sum(cost[row][column] for row, column in pairs) == 5
    assert len({row for row, _ in pairs}) == 3
    assert len({column for _, column in pairs}) == 3


def test_wide_matrix_assigns_every_row():
    cost = [[4, 1, 3, 9], [2, 0, 5, 7]]
    pairs = minimum_cost_assignment(cost)
    assert len(pairs) == 2
    assert sum(cost[row][column] for row, column in pairs) == 3


def test_tall_matrix_assigns_every_column():
    cost = [[4, 1], [2, 0], [3, 2]]
    pairs = minimum_cost_assignment(cost)
    assert len(pairs) == 2
    assert sum(cost[row][column] for row, column in pairs) == 3


def test_maximum_weight_is_dual_of_minimum_cost():
    weight = [[10, 2], [3, 8]]
    pairs = maximum_weight_assignment(weight)
    assert sum(weight[row][column] for row, column in pairs) == 18


def test_empty_matrix_returns_no_pairs():
    assert minimum_cost_assignment([]) == []
