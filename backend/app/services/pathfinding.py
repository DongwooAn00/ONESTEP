from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from app.services.cost_grid import CostCell, CostGrid, ProjectedPoint


@dataclass(frozen=True)
class PathResult:
    cells: list[CostCell]
    total_grid_cost: float


NEIGHBORS = (
    (-1, -1, math.sqrt(2)),
    (-1, 0, 1.0),
    (-1, 1, math.sqrt(2)),
    (0, -1, 1.0),
    (0, 1, 1.0),
    (1, -1, math.sqrt(2)),
    (1, 0, 1.0),
    (1, 1, math.sqrt(2)),
)


def _heuristic(row: int, col: int, goal: tuple[int, int]) -> float:
    return math.hypot(goal[0] - row, goal[1] - col)


def find_least_cost_path(grid: CostGrid, start: ProjectedPoint, end: ProjectedPoint) -> PathResult:
    start_index = grid.nearest_index(start)
    goal_index = grid.nearest_index(end)

    frontier: list[tuple[float, int, tuple[int, int]]] = [(0.0, 0, start_index)]
    came_from: dict[tuple[int, int], tuple[int, int] | None] = {start_index: None}
    cost_so_far: dict[tuple[int, int], float] = {start_index: 0.0}
    sequence = 1

    while frontier:
        _, _, current = heapq.heappop(frontier)
        if current == goal_index:
            return PathResult(
                cells=_reconstruct_path(grid, came_from, current),
                total_grid_cost=round(cost_so_far[current], 3),
            )

        current_cell = grid.cell(*current)
        for drow, dcol, distance_weight in NEIGHBORS:
            next_index = (current[0] + drow, current[1] + dcol)
            if not grid.in_bounds(*next_index):
                continue

            next_cell = grid.cell(*next_index)
            if not math.isfinite(next_cell.cost) or next_cell.protected:
                continue

            movement_cost = ((current_cell.cost + next_cell.cost) / 2.0) * distance_weight
            new_cost = cost_so_far[current] + movement_cost
            if next_index not in cost_so_far or new_cost < cost_so_far[next_index]:
                cost_so_far[next_index] = new_cost
                priority = new_cost + _heuristic(*next_index, goal_index)
                heapq.heappush(frontier, (priority, sequence, next_index))
                sequence += 1
                came_from[next_index] = current

    raise ValueError("비용지도에서 시작점과 종료점을 잇는 경로를 찾지 못했습니다.")


def _reconstruct_path(
    grid: CostGrid,
    came_from: dict[tuple[int, int], tuple[int, int] | None],
    current: tuple[int, int],
) -> list[CostCell]:
    path = [grid.cell(*current)]
    while came_from[current] is not None:
        current = came_from[current]
        path.append(grid.cell(*current))
    path.reverse()
    return path
