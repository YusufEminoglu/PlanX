# -*- coding: utf-8 -*-
"""QGIS-independent catalog gates for the PlanX Processing provider.

Run with any Python 3 (no NumPy, no QGIS needed):
    py -3 tests/smoke_provider_catalog.py

Also collected by pytest, so the monorepo's pure gate runs it via
plugins.toml tests_pure. The module defines run_all() and __main__ so it works
both ways, exactly like tests/test_engine.py.

What this file is for: every gate here exists because the corresponding claim
was false at least once in a released version. The plugin looked documented
while all 69 Help buttons returned 404, and nothing noticed - because nothing
was checking. These are the checks that notice.
"""
from __future__ import annotations

import ast
import hashlib
import re
import struct
import sys
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
PROVIDER = ROOT / "provider.py"
BASE = ROOT / "algorithms" / "base.py"
ALGORITHMS = ROOT / "algorithms"
ICONS = ROOT / "icons"
METADATA = ROOT / "metadata.txt"
README = ROOT / "README.md"
STUDIO_DOCK = ROOT / "studio_dock.py"
MANUAL = ROOT / "docs" / "PLANX_REFERENCE_MANUAL.html"

#: The count may only go up. A drop means algorithms were dropped by accident.
MIN_EXPECTED_ALGORITHM_COUNT = 72

#: GROUP_* slugs in the order algorithms/base.py declares them. The manual
#: numbers its group sections 1..N in this same order, so a reorder here
#: silently renumbers the published navigation - this is the lock for that.
EXPECTED_GROUP_IDS = (
    "network",
    "centrality",
    "morphology",
    "accessibility",
    "microclimate",
    "standards",
    "reporting",
    "optimization",
    "equity",
    "walkability",
    "transit",
    "visibility",
    "population",
    "green",
    "growth",
    "cycling",
    "hazard",
    "demand",
    "seismic",
)

#: Tool icons ship at 256x256; the plugin icon is 512x512. The gate asserts the
#: tool size so an icon exported at the wrong scale is caught rather than
#: shipped. Change this constant only alongside a deliberate re-export.
EXPECTED_TOOL_ICON_SIZE = (256, 256)

MANUAL_VOID_TAGS = {
    "meta", "input", "br", "img", "link", "hr", "source", "area", "col",
    "embed", "track", "wbr",
}


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def _module_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _returned_string(function: ast.FunctionDef) -> str:
    """First string a method returns, unwrapping self.tr(...).

    name() returns a bare literal; displayName()/shortHelpString() wrap theirs
    in self.tr(). Adjacent literals are already merged into one Constant by the
    parser, so a multi-line help string arrives here whole.
    """
    for node in ast.walk(function):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        if isinstance(value, ast.Call):
            for arg in value.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    return arg.value
    return ""


def _provider_imported_algorithm_classes() -> set[str]:
    imported = set()
    for node in ast.walk(_module_tree(PROVIDER)):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level != 1 or not node.module or not node.module.startswith("algorithms."):
            continue
        for alias in node.names:
            imported.add(alias.asname or alias.name)
    return imported


def _provider_registered_algorithm_classes() -> list[str]:
    registered = []
    for node in ast.walk(_module_tree(PROVIDER)):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "addAlgorithm":
            continue
        if not node.args:
            continue
        call = node.args[0]
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
            registered.append(call.func.id)
    return registered


def _group_constants() -> list[tuple[str, str]]:
    """[(constant name, group id)] in the order base.py declares them."""
    groups = []
    tree = _module_tree(BASE)
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.startswith("GROUP_"):
            continue
        value = node.value
        if isinstance(value, ast.Tuple) and len(value.elts) == 2:
            label, group_id = value.elts
            if (isinstance(label, ast.Constant) and isinstance(group_id, ast.Constant)
                    and isinstance(label.value, str) and isinstance(group_id.value, str)):
                groups.append((target.id, group_id.value))
    return groups


def _algorithm_catalog() -> dict[str, dict[str, str]]:
    catalog = {}
    for path in sorted(ALGORITHMS.glob("alg_*.py")):
        tree = _module_tree(path)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or not node.name.endswith("Algorithm"):
                continue
            methods = {}
            group_const = ""
            icon = ""
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name in {"name", "displayName", "shortHelpString"}:
                    methods[child.name] = _returned_string(child)
                if isinstance(child, ast.Assign) and len(child.targets) == 1:
                    target = child.targets[0]
                    if not isinstance(target, ast.Name):
                        continue
                    if target.id == "GROUP" and isinstance(child.value, ast.Name):
                        group_const = child.value.id
                    if target.id == "ICON" and isinstance(child.value, ast.Constant):
                        icon = child.value.value
            catalog[node.name] = {
                "file": path.name,
                "name": methods.get("name", ""),
                "display_name": methods.get("displayName", ""),
                "help": methods.get("shortHelpString", ""),
                "group_const": group_const,
                "icon": icon,
            }
    return catalog


def _doc_base_url() -> str:
    tree = _module_tree(BASE)
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "DOC_BASE_URL":
            assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
            return node.value.value
    raise AssertionError("DOC_BASE_URL not found in algorithms/base.py")


def _metadata_value(key: str) -> str:
    for line in METADATA.read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    raise AssertionError(f"metadata.txt must define {key}")


def _manual_text() -> str:
    return MANUAL.read_text(encoding="utf-8")


def _manual_sections() -> list[tuple[str, str]]:
    """[(anchor id, markup from this <h2> up to the next <h2>)] in document order."""
    text = _manual_text()
    starts = [(m.start(), m.group(1)) for m in re.finditer(r'<h2[^>]*id="([^"]+)"', text)]
    sections = []
    for index, (position, anchor) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(text)
        sections.append((anchor, text[position:end]))
    return sections


def _manual_processing_ids() -> dict[str, str]:
    """anchor id -> the Processing id its own section declares.

    Each tool section opens <h2 id="X"> and follows it with
    <p><strong>Processing ID:</strong> <code>planx:X</code></p>. That second
    line is the manual stating which algorithm the section documents, so the
    two must agree - an anchor that no longer has a matching Processing id is
    a dead Help target even though the card still renders.
    """
    found = {}
    for anchor, body in _manual_sections():
        match = re.search(r"Processing ID:\s*</strong>\s*<code>planx:([^<]+)</code>", body)
        if match:
            found[anchor] = match.group(1).strip()
    return found


def _png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:33]
    return struct.unpack(">II", header[16:24])


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #
def test_provider_imports_every_registered_algorithm() -> None:
    imported = _provider_imported_algorithm_classes()
    registered = _provider_registered_algorithm_classes()
    assert registered, "Provider should register at least one algorithm"
    assert len(registered) == len(set(registered)), "Provider should not register duplicate algorithm classes"
    missing = sorted(set(registered) - imported)
    assert not missing, f"Registered classes are not imported: {missing}"


def test_every_algorithm_file_is_registered_once() -> None:
    catalog = _algorithm_catalog()
    registered = _provider_registered_algorithm_classes()
    assert len(registered) >= MIN_EXPECTED_ALGORITHM_COUNT, (
        f"Provider registers {len(registered)} algorithms, below the expected floor of "
        f"{MIN_EXPECTED_ALGORITHM_COUNT} - algorithms may have been dropped by accident"
    )
    unregistered = sorted(set(catalog) - set(registered))
    unknown = sorted(set(registered) - set(catalog))
    assert not unregistered, f"Algorithm classes missing from provider: {unregistered}"
    assert not unknown, f"Provider registers unknown algorithm classes: {unknown}"


def test_algorithm_catalog_has_stable_ids_and_groups() -> None:
    catalog = _algorithm_catalog()
    ids = [meta["name"] for meta in catalog.values()]
    assert all(ids), "Every algorithm needs a non-empty Processing id"
    assert len(ids) == len(set(ids)), "Processing ids must be unique"
    assert all(value == value.lower() for value in ids), "Processing ids should stay lowercase"
    assert all(" " not in value and "-" not in value for value in ids), "Processing ids should be import-safe"

    display_names = [meta["display_name"] for meta in catalog.values()]
    assert all(display_names), "Every algorithm needs a display name"
    assert len(display_names) == len(set(display_names)), "Display names must be unique"

    declared = {name for name, _ in _group_constants()}
    bad_group = {cls: meta["group_const"] for cls, meta in catalog.items()
                 if meta["group_const"] not in declared}
    assert not bad_group, f"Algorithms whose GROUP is not a base.py GROUP_* constant: {bad_group}"


def test_group_declaration_order_matches_the_manual_numbering() -> None:
    """The manual numbers its group sections 1..N in base.py's declaration
    order, so reordering the constants renumbers the published sidebar without
    touching the manual. Labels are deliberately not compared: the manual
    writes "Centrality & Space Syntax" where QGIS shows "Centrality and Space
    Syntax", which is cosmetic, while the *order* is navigational."""
    groups = _group_constants()
    ids = tuple(group_id for _, group_id in groups)
    assert ids == EXPECTED_GROUP_IDS, (
        f"base.py GROUP_* declaration order changed.\n  expected: {EXPECTED_GROUP_IDS}\n  found:    {ids}\n"
        "If this is deliberate, renumber the manual's group1..groupN sections to match."
    )
    manual_groups = sorted(int(m.group(1)) for m in re.finditer(r'<h2[^>]*id="group(\d+)"', _manual_text()))
    assert manual_groups == list(range(1, len(groups) + 1)), (
        f"Manual should have group1..group{len(groups)} and nothing else, found: {manual_groups}"
    )


def test_every_algorithm_has_a_unique_icon_at_the_expected_size() -> None:
    """A duplicate icon means a copied algorithm kept its neighbour's picture,
    which reads as a bug in the toolbox. The size check catches an icon
    exported at the wrong scale - QGIS renders it, so nothing else notices."""
    catalog = _algorithm_catalog()
    problems = []
    digests = {}
    for cls, meta in sorted(catalog.items()):
        icon_name = meta["icon"]
        if not icon_name:
            problems.append(f"{cls} ({meta['file']}) declares no ICON")
            continue
        path = ICONS / icon_name
        if not path.exists():
            problems.append(f"{cls} ICON {icon_name!r} does not exist under icons/")
            continue
        size = _png_size(path)
        if size != EXPECTED_TOOL_ICON_SIZE:
            problems.append(f"{icon_name} is {size[0]}x{size[1]}, expected "
                            f"{EXPECTED_TOOL_ICON_SIZE[0]}x{EXPECTED_TOOL_ICON_SIZE[1]}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        digests.setdefault(digest, []).append(icon_name)
    assert not problems, f"Icon problems: {problems}"
    duplicated = {d: names for d, names in digests.items() if len(names) > 1}
    assert not duplicated, f"Algorithms sharing one icon image: {list(duplicated.values())}"


def test_algorithm_ids_match_manual_anchors_one_to_one() -> None:
    """helpUrl() is DOC_BASE_URL + '#' + name(), so the manual must carry an
    anchor named exactly like every Processing id - in both directions. A
    missing anchor sends the user to the top of a 1 MB page with no error; an
    orphan card documents a tool that no longer exists."""
    catalog = _algorithm_catalog()
    algorithm_ids = {meta["name"] for meta in catalog.values()}
    anchors = {anchor for anchor, _ in _manual_sections()}
    # .values(), not the dict: the declared Processing ids are what must exist
    # as algorithms. Taking the dict itself yields its keys - the anchors - and
    # then this half of the gate compares the anchor set against itself and can
    # never fail.
    documented = set(_manual_processing_ids().values())

    no_anchor = sorted(algorithm_ids - anchors)
    assert not no_anchor, f"Algorithms whose Help anchor is missing from the manual: {no_anchor}"

    no_algorithm = sorted(documented - algorithm_ids)
    assert not no_algorithm, (
        f"Manual documents Processing ids that no algorithm registers: {no_algorithm}"
    )


def test_manual_processing_id_lines_match_their_anchor() -> None:
    """Each card names the tool it documents twice: the <h2 id="X"> a Help
    button jumps to, and the 'Processing ID: planx:Y' line a reader copies into
    the toolbox. Eight of these disagreed on the first run - seven written from
    the class name (morphologicaltessellation for tessellation) and one a plain
    misspelling (multiamentiyaccess for accessscore). None of the eight existed
    as a Processing id, so those cards pointed at tools that cannot be found
    while the Help button beside them worked."""
    catalog = _algorithm_catalog()
    algorithm_ids = {meta["name"] for meta in catalog.values()}
    found = _manual_processing_ids()

    undocumented = sorted(algorithm_ids - set(found))
    assert not undocumented, f"Manual cards carrying no Processing ID line: {undocumented}"

    mismatches = [f"id={anchor!r} declares 'planx:{declared}'"
                  for anchor, declared in sorted(found.items())
                  if anchor != declared]
    assert not mismatches, (
        "Manual cards whose Processing ID line disagrees with their own anchor: "
        f"{mismatches}"
    )


def test_manual_has_balanced_div_tags() -> None:
    """A browser silently repairs unbalanced nesting, so a broken card renders
    "almost right" and hides indefinitely. Checked for the whole document and
    for each tool section separately: one section absorbing a neighbour's
    unclosed <div> keeps the document total balanced while still breaking both
    sections' layout."""
    text = _manual_text()
    opened = len(re.findall(r"<div\b", text))
    closed = text.count("</div>")
    assert opened == closed, f"Manual <div> nesting is unbalanced overall: {opened} opened, {closed} closed"

    unbalanced = []
    for anchor, body in _manual_sections():
        body_opened = len(re.findall(r"<div\b", body))
        body_closed = body.count("</div>")
        if body_opened != body_closed:
            unbalanced.append(f"{anchor} ({body_opened} <div> vs {body_closed} </div>)")
    assert not unbalanced, f"Manual sections with unbalanced <div> nesting: {unbalanced}"


def test_manual_has_no_angle_brackets_the_parser_would_read_as_tags() -> None:
    """A bare '<' followed by a letter is read as the start of a tag. Inside
    LaTeX that silently destroys the formula, because MathJax never receives
    the source: '\\sigma_{<i}' becomes '\\sigma_{' plus an <i> element.

    The predicate is data-driven rather than a fixed list of tag names: a '<'
    is flagged only when the name after it is not a tag this document actually
    uses (plus HTML void elements, which are never closed and so have no
    </...> to discover them by). A '<' followed by anything else - a space, a
    digit, punctuation, as in \\(p < 0.05\\) - is literal text to the parser
    and is correctly left alone."""
    text = _manual_text()
    vocabulary = {match.group(1).lower() for match in re.finditer(r"</([A-Za-z][A-Za-z0-9]*)>", text)}
    vocabulary |= MANUAL_VOID_TAGS

    offenders = []
    for match in re.finditer(r"<([A-Za-z][A-Za-z0-9]*)", text):
        if match.group(1).lower() in vocabulary:
            continue
        line = text.count("\n", 0, match.start()) + 1
        context = text[max(0, match.start() - 45):match.start() + 25].replace("\n", " ")
        offenders.append(f"line {line}: {match.group(0)!r} in ...{context}...")
    assert not offenders, (
        "Bare '<' that the HTML parser reads as a tag - write &lt; instead, which decodes "
        f"back to '<' before MathJax reads the text: {offenders}"
    )


def test_manual_version_matches_plugin_version() -> None:
    """The manual advertised the previous release in three places (title,
    sidebar, footer), so it read as one version behind for the whole life of
    that release. Every version literal in the manual must be the version
    metadata.txt declares."""
    version = _metadata_value("version")
    found = set(re.findall(r"v\d+\.\d+\.\d+", _manual_text()))
    assert found == {f"v{version}"}, (
        f"Manual should advertise exactly v{version} (from metadata.txt), found: {sorted(found)}"
    )


def test_help_url_host_matches_metadata_homepage() -> None:
    """Every algorithm's Help button resolves through DOC_BASE_URL, so if that
    constant names a host other than the one metadata.txt advertises, all 69
    deep links are dead while the plugin still looks properly documented. That
    is exactly what happened when the public manual moved off
    yusufeminoglu.github.io and only metadata.txt was updated: metadata.txt
    resolved, every Help button returned 404."""
    documented = _doc_base_url()
    homepage = _metadata_value("homepage")
    assert documented.startswith("https://"), "Documentation URL must use https"
    assert urlsplit(documented).netloc == urlsplit(homepage).netloc, (
        f"algorithms/base.py DOC_BASE_URL ({documented}) and metadata.txt homepage "
        f"({homepage}) must share a host - every algorithm's Help button resolves "
        "through DOC_BASE_URL."
    )


def test_manual_links_the_repository_metadata_declares() -> None:
    """The manual's footer tells the reader where the source lives. It named
    gitlab.com/yusufeminoglu/planx - the pre-rename path, which still 301s to
    the right repository - while metadata.txt declares geophilo1/planx to the
    Hub. Same failure shape as DOC_BASE_URL: the link the user is told to visit
    is not the one the plugin actually advertises. (The manual's GitHub mirror
    link is deliberately kept by the maintainer and currently 404s; that is a
    standing decision, not a gate failure, so only the declared repository is
    asserted here.)"""
    repository = _metadata_value("repository")
    assert repository in _manual_text(), (
        f"The manual should link the repository that metadata.txt declares ({repository}); "
        "a link to any other path may be stale."
    )


def test_documentation_url_is_defined_once() -> None:
    """DOC_BASE_URL was defined twice - once in algorithms/base.py for the
    Processing Help buttons and once in studio_dock.py for the Studio dock's
    Docs and Help actions. Two copies of the same host is how the manual and
    the code drifted apart in the first place: fixing one leaves the other
    pointing at a 404. The dock must import it, not repeat it."""
    assignments = []
    for node in ast.walk(_module_tree(STUDIO_DOCK)):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "DOC_BASE_URL":
                    assignments.append(node.lineno)
    assert not assignments, (
        f"studio_dock.py redefines DOC_BASE_URL at line(s) {assignments}; it must "
        "import it from algorithms.base so the host has exactly one definition"
    )
    imported = False
    for node in ast.walk(_module_tree(STUDIO_DOCK)):
        if isinstance(node, ast.ImportFrom) and node.module == "algorithms.base":
            if any(alias.name == "DOC_BASE_URL" for alias in node.names):
                imported = True
    assert imported, "studio_dock.py should import DOC_BASE_URL from algorithms.base"


def test_readme_counts_match_the_manual() -> None:
    """README quoted "285 numbered display equations" and "~600 citations".
    The manual has 289 numbered equations and 377 reference entries, and "~600"
    was hedged into unfalsifiability. A count in the marketing copy that no
    gate checks will always drift."""
    text = _manual_text()
    equations = len(re.findall(r"\\tag\{", text))
    ref_blocks = re.findall(r'<p class="ref">.*?</p>', text, re.S)
    references = len(ref_blocks)
    # Entries that carry a DOI, not DOI links: counting occurrences let one
    # reference listing two DOIs pay for one listing none, so the README's
    # "with DOIs" figure read one higher than the manual supports.
    dois = sum("doi.org" in block for block in ref_blocks)

    readme = README.read_text(encoding="utf-8")
    claimed_equations = re.search(r"\((\d+) numbered display equations\)", readme)
    assert claimed_equations, "README should state its numbered-equation count in the form '(N numbered display equations)'"
    assert int(claimed_equations.group(1)) == equations, (
        f"README claims {claimed_equations.group(1)} numbered display equations; the manual has {equations}"
    )

    claimed_refs = re.search(r"\((\d+) entries, (\d+) with DOIs\)", readme)
    assert claimed_refs, (
        "README should state its reference count in the form '(N entries, M with DOIs)' "
        "so the claim is countable"
    )
    assert int(claimed_refs.group(1)) == references, (
        f"README claims {claimed_refs.group(1)} reference entries; the manual has {references}"
    )
    assert int(claimed_refs.group(2)) == dois, (
        f"README claims {claimed_refs.group(2)} entries with DOIs; the manual has {dois}"
    )


def test_algorithm_help_strings_have_the_required_sections() -> None:
    """Every algorithm's help must end with a 'How to read the results' section
    followed by a 'Using the results' passage. A tool that computes correctly
    but does not say how to read its own output is not finished: the numbers
    reach the user with no interpretation attached."""
    catalog = _algorithm_catalog()
    missing = {}
    for cls, meta in sorted(catalog.items()):
        gaps = []
        if "How to read the results" not in meta["help"]:
            gaps.append("How to read the results")
        if "Using the results" not in meta["help"]:
            gaps.append("Using the results")
        if not meta["help"]:
            gaps.append("shortHelpString not found")
        if gaps:
            missing[cls] = gaps
    assert not missing, f"Algorithms whose help is missing a required section: {missing}"


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #
GATES = (
    test_provider_imports_every_registered_algorithm,
    test_every_algorithm_file_is_registered_once,
    test_algorithm_catalog_has_stable_ids_and_groups,
    test_group_declaration_order_matches_the_manual_numbering,
    test_every_algorithm_has_a_unique_icon_at_the_expected_size,
    test_algorithm_ids_match_manual_anchors_one_to_one,
    test_manual_processing_id_lines_match_their_anchor,
    test_manual_has_balanced_div_tags,
    test_manual_has_no_angle_brackets_the_parser_would_read_as_tags,
    test_manual_version_matches_plugin_version,
    test_help_url_host_matches_metadata_homepage,
    test_manual_links_the_repository_metadata_declares,
    test_documentation_url_is_defined_once,
    test_readme_counts_match_the_manual,
    test_algorithm_help_strings_have_the_required_sections,
)


def main() -> None:
    failures = []
    for gate in GATES:
        try:
            gate()
        except AssertionError as error:
            failures.append((gate.__name__, error))
        except Exception as error:  # noqa: BLE001 - a crashing gate is a failure too
            failures.append((gate.__name__, f"{type(error).__name__}: {error}"))
    passed = len(GATES) - len(failures)
    print(f"\n{passed}/{len(GATES)} catalog gates passed")
    if failures:
        print("FAILED:", *(f"{name}: {error}" for name, error in failures), sep="\n  - ")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
