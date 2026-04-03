"""
Algorithme de construction automatique de clusters d'affinité
à partir du graphe des préférences, puis affectation aux groupes.
"""

from collections import defaultdict

EXTE_PREFIX = "Exté : "


class UnionFind:
    def __init__(self, elements):
        self.parent = {e: e for e in elements}
        self.rank   = {e: 0 for e in elements}
        self.sz     = {e: 1 for e in elements}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.sz[ra] += self.sz[rb]
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1
        return True

    def size(self, x):
        return self.sz[self.find(x)]

    def clusters(self):
        groups = defaultdict(list)
        for x in self.parent:
            groups[self.find(x)].append(x)
        return list(groups.values())


def build_people_list(
    participants: list[str],
    edges: list[tuple[str, str]],
    respondents: list[str],
    exte_respondents: list[str],
    node_colors: dict[str, str],
    participant_departments: dict[str, str | None],
) -> list[dict]:
    """Construit la liste complète des personnes à répartir en groupes."""
    participant_set = set(participants)
    respondent_set  = set(respondents)
    exte_resp_set   = set(exte_respondents)

    all_people: dict[str, dict] = {}

    for name in participants:
        ptype = "participant" if name in respondent_set else "non_inscrit"
        all_people[name] = {
            "name":       name,
            "type":       ptype,
            "department": participant_departments.get(name),
            "color":      node_colors.get(name, "#ffffff"),
        }

    for src, dst in edges:
        for n in (src, dst):
            if n not in all_people:
                if n.startswith(EXTE_PREFIX) or n in exte_resp_set:
                    all_people[n] = {
                        "name":       n,
                        "type":       "exte",
                        "department": None,
                        "color":      "#ffffff",
                    }
                elif n not in participant_set:
                    all_people[n] = {
                        "name":       n,
                        "type":       "non_inscrit",
                        "department": None,
                        "color":      "#ffffff",
                    }

    for n in exte_resp_set:
        if n not in all_people:
            all_people[n] = {
                "name":       n,
                "type":       "exte",
                "department": None,
                "color":      "#ffffff",
            }

    return list(all_people.values())


def build_affinity_clusters(
    people: list[dict],
    edges: list[tuple[str, str]],
    max_capacity: int,
) -> list[list[dict]]:
    """
    Regroupe les personnes en clusters d'affinité via Union-Find.
    Respecte max_capacity : ne fusionne jamais au-delà.
    Attache les extés à leurs demandeurs.
    """
    names = {p["name"] for p in people}
    people_map = {p["name"]: p for p in people}

    weights: dict[tuple, int] = defaultdict(int)
    for src, dst in edges:
        if src in names and dst in names:
            key = tuple(sorted([src, dst]))
            weights[key] += 1

    uf = UnionFind(names)

    for (a, b), _w in sorted(weights.items(), key=lambda x: -x[1]):
        if uf.find(a) != uf.find(b):
            if uf.size(a) + uf.size(b) <= max_capacity:
                uf.union(a, b)

    exte_requesters: dict[str, list[str]] = defaultdict(list)
    for src, dst in edges:
        if dst.startswith(EXTE_PREFIX) and dst in names and src in names:
            exte_requesters[dst].append(src)

    for exte_name, requesters in exte_requesters.items():
        if not requesters:
            continue
        best = max(requesters, key=lambda r: uf.size(r))
        uf.union(exte_name, best)

    raw = uf.clusters()
    result = []
    for cid, members in enumerate(raw):
        cluster = []
        for name in sorted(members):
            p = dict(people_map[name])
            p["cluster_id"] = cid
            cluster.append(p)
        result.append(cluster)

    return sorted(result, key=lambda c: -len(c))


def assign_clusters_to_slots(
    clusters: list[list[dict]],
    slot_capacities: list[tuple[int, int]],
) -> dict[int | None, list[dict]]:
    """
    First Fit Decreasing : place chaque cluster dans le premier groupe
    ayant assez de capacité restante.

    slot_capacities : [(slot_id, capacity), ...]
    Retourne {slot_id: [person_dicts], None: [non affectés]}
    """
    remaining = {sid: cap for sid, cap in slot_capacities}
    assignments: dict[int | None, list[dict]] = {sid: [] for sid, _ in slot_capacities}
    assignments[None] = []

    for cluster in clusters:
        size = len(cluster)
        placed = False
        for sid, _ in sorted(slot_capacities, key=lambda x: -remaining[x[0]]):
            if remaining[sid] >= size:
                assignments[sid].extend(cluster)
                remaining[sid] -= size
                placed = True
                break
        if not placed:
            assignments[None].extend(cluster)

    return assignments
