"""
groupe/graph.py
Génération du graphe orienté des préférences de groupes.
Fonctions pures — aucune requête BDD.

Conventions :
  - Les souhaits vers une personne extérieure sont préfixés par EXTE_PREFIX.
  - Les labels affichés n'ont jamais ce préfixe.
  - Les participants inscrits sans aucune arête (ni souhait, ni souhaité) sont affichés
    comme nœuds isolés.

Style des nœuds :
  - fill : couleur du département (blanc par défaut / blanc pour exté)
  - Inscrit·e         : contour noir plein, texte noir normal
  - Non inscrit·e     : contour rouge plein, texte noir normal
                        → flèches vers ce nœud en rouge
  - Exté              : contour noir pointillé, texte noir gras, fill blanc
"""
import subprocess
from collections import defaultdict

EXTE_PREFIX = "Exté : "


def build_graph_data(
    participants: list[str],
    edges: list[tuple[str, str]],
    respondents: list[str] | None = None,
    node_colors: dict[str, str] | None = None,
    exte_respondents: list[str] | None = None,
) -> dict:
    """Construit les données JSON pour D3 force-directed graph."""
    respondent_set = set(respondents or [])
    colors         = node_colors or {}
    exte_resp_set  = set(exte_respondents or [])

    edge_counts: dict[tuple, int] = defaultdict(int)
    for src, dst in edges:
        edge_counts[(src, dst)] += 1

    in_degree:  dict[str, int] = defaultdict(int)
    out_degree: dict[str, int] = defaultdict(int)
    for (src, dst), count in edge_counts.items():
        in_degree[dst]  += count
        out_degree[src] += count

    connected: set[str] = set()
    for src, dst in edge_counts:
        connected.add(src)
        connected.add(dst)

    known = set(participants)
    nodes = []

    for name in participants:
        if name not in connected and name not in respondent_set:
            continue
        nodes.append({
            "id":             name,
            "name":           name,
            "display_name":   name,
            "votes_received": in_degree[name],
            "exte":           False,
            "wished":         in_degree[name] > 0,
            "inscrit":        name in respondent_set,
            "color":          colors.get(name, "#ffffff"),
        })

    # Nœuds exté : ceux souhaitées par quelqu'un ET ceux qui ont soumis le form
    exte_seen: set[str] = set()
    all_exte = (
        {dst for dst in connected if dst.startswith(EXTE_PREFIX) and dst not in known}
        | exte_resp_set
    )
    for name in all_exte:
        if name in exte_seen:
            continue
        exte_seen.add(name)
        nodes.append({
            "id":             name,
            "name":           name,
            "display_name":   name[len(EXTE_PREFIX):],
            "votes_received": in_degree[name],
            "exte":           True,
            "wished":         in_degree[name] > 0,
            "inscrit":        False,
            "color":          "#ffffff",
        })

    links = [
        {"source": src, "target": dst, "weight": count}
        for (src, dst), count in edge_counts.items()
    ]
    return {"nodes": nodes, "links": links}


def generate_dot(
    form_title: str,
    participants: list[str],
    edges: list[tuple[str, str]],
    respondents: list[str] | None = None,
    node_colors: dict[str, str] | None = None,
    exte_respondents: list[str] | None = None,
) -> str:
    """Génère le source DOT (Graphviz) du graphe de préférences."""
    respondent_set = set(respondents or [])
    colors         = node_colors or {}
    exte_resp_set  = set(exte_respondents or [])

    edge_counts: dict[tuple, int] = defaultdict(int)
    for src, dst in edges:
        edge_counts[(src, dst)] += 1

    in_degree: dict[str, int] = defaultdict(int)
    for (_, dst), count in edge_counts.items():
        in_degree[dst] += count

    connected: set[str] = set()
    for src, dst in edge_counts:
        connected.add(src)
        connected.add(dst)

    known = set(participants)

    lines = [
        "digraph groupes {",
        f'    graph [label="Groupes – {_dot_str(form_title)}", fontsize=16, fontname="Helvetica"];',
        '    rankdir=LR;',
        '    node [shape=ellipse, style=filled, fontcolor=black, '
        'fontname="Helvetica", fontsize=12];',
        '    edge [fontname="Helvetica", fontsize=10];',
        "",
    ]

    for name in participants:
        if name not in connected and name not in respondent_set:
            continue
        is_inscrit = name in respondent_set
        border     = "black" if is_inscrit else "#dc3545"
        fill       = colors.get(name, "#ffffff")
        lines.append(
            f'    "{_dot_str(name)}" [fillcolor="{fill}", color="{border}"];'
        )

    all_exte = (
        {dst for (_, dst) in edge_counts if dst.startswith(EXTE_PREFIX) and dst not in known}
        | exte_resp_set
    )
    for name in sorted(all_exte):
        display = _dot_str(name[len(EXTE_PREFIX):])
        node_id = _dot_str(name)
        lines.append(
            f'    "{node_id}" [label="{display}", fillcolor="white", color="black", '
            f'style="filled,dashed", fontname="Helvetica-Bold"];'
        )

    lines.append("")

    for (src, dst), count in sorted(edge_counts.items()):
        penwidth   = 1.0 + count * 0.5
        label_attr = f'label="{count}", ' if count > 1 else ""
        is_exte_dst = dst.startswith(EXTE_PREFIX)
        is_inscrit  = dst in respondent_set
        color = "#333333" if (is_exte_dst or is_inscrit) else "#dc3545"
        lines.append(
            f'    "{_dot_str(src)}" -> "{_dot_str(dst)}" '
            f'[{label_attr}penwidth="{penwidth:.1f}", color="{color}"];'
        )

    lines.append("}")
    return "\n".join(lines)


def generate_png(
    form_title: str,
    participants: list[str],
    edges: list[tuple[str, str]],
    respondents: list[str] | None = None,
    node_colors: dict[str, str] | None = None,
    exte_respondents: list[str] | None = None,
) -> bytes | None:
    """Génère un PNG via `dot` (Graphviz). Retourne None si non installé."""
    dot_src = generate_dot(form_title, participants, edges, respondents, node_colors, exte_respondents)
    try:
        result = subprocess.run(
            ["dot", "-Tpng"],
            input=dot_src.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _dot_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')
