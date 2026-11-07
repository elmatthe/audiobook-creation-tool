"""What the application shows a user, found two ways and held against the one reviewed index in coverage.json (plan section 7.1).

Static discovery reads the application's own source, never running it: every interactive control a file constructs directly, every
standard dialog it raises, every event or window protocol it binds, and every tool the launcher registers. It cannot see a control that a
helper builds or a loop multiplies, so live discovery reads the real widget trees of a running instance (``journeys/inventory.py``) and
names each interactive widget by the attribute path the panel keeps it under. Neither alone is the inventory; together they are what a
new, renamed or removed surface cannot slip past.

Keys are built from what a maintainer recognises and what survives an unrelated edit: file, enclosing class and function, control class,
and its label, variable or command; never a line number. Two identical constructions in one function are numbered in source order. A key
that changes is a surface to review again, which is the point.

Pure functions only: nothing here imports the application.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

#: Classes a user can act on. Frames, labels, separators and scrollbars are layout; they carry no feature of their own.
INTERACTIVE = frozenset({"Button", "Checkbutton", "Radiobutton", "Entry", "Combobox", "Spinbox", "Listbox", "Text", "Treeview", "Scale",
                         "Menubutton", "Notebook", "OptionMenu", "Toplevel", "Menu"})
WIDGET_MODULES = frozenset({"tk", "ttk", "tkinter"})
DIALOG_MODULES = frozenset({"messagebox", "filedialog", "simpledialog", "colorchooser"})
BIND_METHODS = frozenset({"bind", "bind_all", "bind_class", "protocol"})
MENU_METHODS = frozenset({"add_command", "add_checkbutton", "add_radiobutton", "add_cascade"})
KINDS = ("tool", "widget", "dialog", "binding", "menu")
#: The live classes that count as a control, by Tk class name. ``Text`` covers the log panes; ``TNotebook`` its tabs.
LIVE_INTERACTIVE = frozenset({"TButton", "Button", "TCheckbutton", "Checkbutton", "TRadiobutton", "Radiobutton", "TEntry", "Entry", "TCombobox",
                              "TSpinbox", "Spinbox", "Listbox", "Text", "Treeview", "TScale", "Scale", "TMenubutton", "Menubutton",
                              "TNotebook"})
LIVE_TEXT_CLASSES = frozenset({"TButton", "Button", "TCheckbutton", "Checkbutton", "TRadiobutton", "Radiobutton", "TMenubutton", "Menubutton"})
_LABEL_LIMIT = 48


@dataclass(frozen=True)
class Surface:
    key: str
    kind: str
    path: str
    qualname: str
    line: int
    label: str

    def record(self) -> dict:
        return {"key": self.key, "kind": self.kind, "path": self.path, "qualname": self.qualname, "line": self.line, "label": self.label}


def _short(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= _LABEL_LIMIT else text[:_LABEL_LIMIT - 1] + "~"


def _literal(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _shown(node: ast.AST) -> str:
    literal = _literal(node)
    return _short(literal) if literal is not None else _short(ast.unparse(node))


def _keyword(call: ast.Call, name: str) -> ast.AST | None:
    return next((item.value for item in call.keywords if item.arg == name), None)


def _callee(call: ast.Call) -> tuple[str | None, str | None]:
    """(module-ish name, attribute) for ``ttk.Button(...)``; (None, name) for a bare ``Button(...)``."""
    func = call.func
    if isinstance(func, ast.Attribute):
        base = func.value.id if isinstance(func.value, ast.Name) else None
        return base, func.attr
    if isinstance(func, ast.Name):
        return None, func.id
    return None, None


class _Walker(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.stack: list[str] = []
        self.parents: dict[int, ast.AST] = {}
        self.found: list[tuple[str, str, int, str, str]] = []  # kind, qualname, line, detail, label

    def run(self, tree: ast.Module) -> None:
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                self.parents[id(child)] = parent
        self.visit(tree)

    def _scoped(self, node) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_ClassDef = visit_FunctionDef = visit_AsyncFunctionDef = _scoped

    @property
    def qualname(self) -> str:
        return ".".join(self.stack) or "<module>"

    def _assigned_to(self, call: ast.Call) -> str | None:
        parent = self.parents.get(id(call))
        if isinstance(parent, ast.Assign) and parent.value is call and len(parent.targets) == 1:
            return ast.unparse(parent.targets[0])
        if isinstance(parent, ast.AnnAssign) and parent.value is call:
            return ast.unparse(parent.target)
        return None

    def visit_Call(self, call: ast.Call) -> None:
        base, attr = _callee(call)
        if attr in INTERACTIVE and base in WIDGET_MODULES:
            self.found.append(("widget", self.qualname, call.lineno, attr, self._widget_label(call)))
        elif base in DIALOG_MODULES and attr:
            title = _keyword(call, "title")
            if title is None and base == "messagebox" and call.args:
                title = call.args[0]
            self.found.append(("dialog", self.qualname, call.lineno, f"{base}.{attr}", "" if title is None else _shown(title)))
        elif isinstance(call.func, ast.Attribute) and attr in BIND_METHODS and call.args:
            sequence = call.args[0]
            literal = _literal(sequence)
            looks_tk = (literal.startswith("<") or literal.startswith("WM_")) if literal is not None else not isinstance(sequence, ast.Tuple)
            if looks_tk:
                self.found.append(("binding", self.qualname, call.lineno, attr, _shown(sequence)))
        elif isinstance(call.func, ast.Attribute) and attr in MENU_METHODS:
            label = _keyword(call, "label")
            self.found.append(("menu", self.qualname, call.lineno, attr, "" if label is None else _shown(label)))
        elif base is None and attr == "ToolSpec" and call.args and _literal(call.args[0]) is not None:
            self.found.append(("tool", self.qualname, call.lineno, "ToolSpec", _literal(call.args[0])))
        self.generic_visit(call)

    def _widget_label(self, call: ast.Call) -> str:
        text = _keyword(call, "text")
        if text is not None:
            return _shown(text) if _literal(text) is not None else f"text={_shown(text)}"
        for name, prefix in (("textvariable", "var="), ("command", "cmd="), ("variable", "var=")):
            value = _keyword(call, name)
            if value is not None:
                return prefix + _shown(value)
        target = self._assigned_to(call)
        return f"@{_short(target)}" if target else ""


def discover_file(repo_root: Path, path: Path) -> list[Surface]:
    """The surfaces one file declares, keyed and numbered."""
    relative = path.relative_to(repo_root).as_posix()
    walker = _Walker(relative)
    walker.run(ast.parse(path.read_text(encoding="utf-8"), filename=relative))
    surfaces: list[Surface] = []
    seen: dict[str, int] = {}
    for kind, qualname, line, detail, label in walker.found:
        if kind == "tool":
            key = f"tool:{label}"
        else:
            key = f"{kind}:{relative}::{qualname}::{detail}:{label}"
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            key = f"{key}#{seen[key]}"
        surfaces.append(Surface(key, kind, relative, qualname, line, label))
    return surfaces


def discover(repo_root: Path, files: list[Path]) -> dict[str, Surface]:
    found: dict[str, Surface] = {}
    for path in sorted(files):
        for surface in discover_file(repo_root, path):
            if surface.key in found:
                raise ValueError(f"two surfaces share the key {surface.key}")
            found[surface.key] = surface
    return found


def _source_probe(repo_root: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("_act_source_probe", repo_root / "files" / "tests" / "source_probe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def application_files(repo_root: Path) -> list[Path]:
    """The application's source, by the suite's own registry (``files/tests/source_probe.py``), never by walking ``scripts/``."""
    return list(_source_probe(repo_root).application_python_files(repo_root / "scripts"))


def application_packages(repo_root: Path) -> list[str]:
    return list(_source_probe(repo_root).application_packages(repo_root / "scripts"))


# --------------------------------------------------------------------------- #
# Live trees
# --------------------------------------------------------------------------- #
def live_keys(widgets: list[dict]) -> dict[str, dict]:
    """Name each interactive widget of one scanned scope by what the panel calls it.

    ``widgets`` is the channel's ``surfaces`` answer: Tk path, class, text and, where the panel keeps the widget under an attribute, its
    shortest key path. A kept widget is named by that path. Anything else is named by its nearest kept ancestor, class and label, numbered
    in tree order when they repeat: still a stable name, and a control nobody kept is precisely the kind a review should look at.
    """
    by_path = {item["path"]: item for item in widgets}
    named: dict[str, dict] = {}
    repeats: dict[str, int] = {}
    for item in widgets:
        if item.get("class") not in LIVE_INTERACTIVE:
            continue
        key = item.get("key")
        if not key:
            anchor, parent = "panel", item.get("parent")
            while parent:
                holder = by_path.get(parent)
                if holder is None:
                    break
                if holder.get("key"):
                    anchor = holder["key"]
                    break
                parent = holder.get("parent")
            # Text only where the class has a real text option (the channel sends none otherwise): an entry's would be its PY_VARn.
            label = _short(str(item.get("text") or "")) if item["class"] in LIVE_TEXT_CLASSES else ""
            key = f"~{anchor}/{item['class']}:{label}"
            repeats[key] = repeats.get(key, 0) + 1
            if repeats[key] > 1:
                key = f"{key}#{repeats[key]}"
        named.setdefault(key, item)
    return named


def compare_live(index: dict[str, str], seen: dict[str, dict], *, scope: str) -> list[str]:
    """Problems between one scope's reviewed live index and what a running instance showed in every scanned state of that scope."""
    problems = [f"{scope}: a live control nobody has mapped: {key} ({seen[key].get('class')}, {seen[key].get('text')!r})"
                for key in sorted(set(seen) - set(index))]
    problems += [f"{scope}: an indexed control the running application no longer shows: {key} (mapped to {index[key]}); renamed or removed"
                 for key in sorted(set(index) - set(seen))]
    return problems


def compare_static(index: dict[str, str], found: dict[str, Surface]) -> list[str]:
    problems = [f"a static surface nobody has mapped: {key} ({found[key].path}:{found[key].line})" for key in sorted(set(found) - set(index))]
    problems += [f"an indexed static surface the source no longer declares: {key} (mapped to {index[key]}); renamed or removed"
                 for key in sorted(set(index) - set(found))]
    return problems
