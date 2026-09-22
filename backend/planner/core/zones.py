"""Разбиение точек участка на зоны обслуживания."""

from __future__ import annotations

import numpy as np

REMOTE_FROM_OFFICE_KM = 25.0
SAME_CLUSTER_KM = 20.0
BASE_ZONE = 0


def split_into_zones(distance_m: np.ndarray, office_node: int) -> list[int]:
    """Нулевая зона это окрестность офиса, остальные это удалённые кластеры."""
    from_office_km = distance_m[office_node] / 1000.0
    remote = [node for node, km in enumerate(from_office_km) if km > REMOTE_FROM_OFFICE_KM]
    zones = [BASE_ZONE] * len(from_office_km)
    if not remote:
        return zones

    parent = {node: node for node in remote}

    def root_of(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for position, left in enumerate(remote):
        for right in remote[position + 1 :]:
            if distance_m[left, right] / 1000.0 <= SAME_CLUSTER_KM:
                left_root, right_root = root_of(left), root_of(right)
                if left_root != right_root:
                    parent[left_root] = right_root

    numbers: dict[int, int] = {}
    for node in remote:
        root = root_of(node)
        if root not in numbers:
            numbers[root] = len(numbers) + 1
        zones[node] = numbers[root]
    return zones
