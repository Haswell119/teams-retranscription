from __future__ import annotations

INFINITY = float("inf")


def _solve_rectangular(cost: list[list[float]]) -> list[int]:
    rows = len(cost)
    columns = len(cost[0])
    potentials_row = [0.0] * (rows + 1)
    potentials_column = [0.0] * (columns + 1)
    matched_row_of_column = [0] * (columns + 1)
    predecessor = [0] * (columns + 1)
    for row in range(1, rows + 1):
        matched_row_of_column[0] = row
        current_column = 0
        slack = [INFINITY] * (columns + 1)
        visited = [False] * (columns + 1)
        while True:
            visited[current_column] = True
            current_row = matched_row_of_column[current_column]
            delta = INFINITY
            next_column = 0
            for column in range(1, columns + 1):
                if visited[column]:
                    continue
                reduced = (
                    cost[current_row - 1][column - 1]
                    - potentials_row[current_row]
                    - potentials_column[column]
                )
                if reduced < slack[column]:
                    slack[column] = reduced
                    predecessor[column] = current_column
                if slack[column] < delta:
                    delta = slack[column]
                    next_column = column
            for column in range(columns + 1):
                if visited[column]:
                    potentials_row[matched_row_of_column[column]] += delta
                    potentials_column[column] -= delta
                else:
                    slack[column] -= delta
            current_column = next_column
            if matched_row_of_column[current_column] == 0:
                break
        while current_column:
            previous = predecessor[current_column]
            matched_row_of_column[current_column] = matched_row_of_column[previous]
            current_column = previous
    assignment = [-1] * rows
    for column in range(1, columns + 1):
        if matched_row_of_column[column] > 0:
            assignment[matched_row_of_column[column] - 1] = column - 1
    return assignment


def minimum_cost_assignment(cost: list[list[float]]) -> list[tuple[int, int]]:
    if not cost or not cost[0]:
        return []
    rows = len(cost)
    columns = len(cost[0])
    if rows <= columns:
        return [(row, column) for row, column in enumerate(_solve_rectangular(cost)) if column >= 0]
    transposed = [[cost[row][column] for row in range(rows)] for column in range(columns)]
    return [(row, column) for column, row in enumerate(_solve_rectangular(transposed)) if row >= 0]


def maximum_weight_assignment(weight: list[list[float]]) -> list[tuple[int, int]]:
    return minimum_cost_assignment([[-value for value in row] for row in weight])
