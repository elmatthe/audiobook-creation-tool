"""Structural assertions about production code, stated as AST rather than text.

**Why this exists.** A guard written as ``source[source.index("def f("):
source.index("def g(")]`` is not a statement about ``f``; it is a statement
about the order two ``def`` lines happen to appear in the file. Move a function,
rename its neighbour, or mention its name in a docstring, and the slice silently
starts describing something else — usually while still passing, which is worse
than failing. This repository has been bitten by both halves of that: a Phase-5
reordering left one such test slicing an unrelated function, and another failed
only because a *comment* mentioned the symbol it forbade.

So the standing rule is **AST, never substring slicing**, and the helpers a
structural test actually needs live here once instead of being re-invented, half
right, in each module.

Every function here takes a parsed module and answers a question about the code
itself: what a function calls, in what order, with what literal arguments, and
what is reachable from where.
"""

from __future__ import annotations

import ast
import functools
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"


@functools.lru_cache(maxsize=None)
def module(relative: str) -> ast.Module:
    """Parse a module under ``scripts/Universal`` once per session."""
    return ast.parse((UNIVERSAL / relative).read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def functions(relative: str) -> dict[str, ast.AST]:
    """Every top-level and nested function in the module, by name."""
    tree = module(relative)
    return {node.name: node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def function(relative: str, name: str):
    """One function definition. Raises rather than silently matching nothing."""
    found = functions(relative).get(name)
    if found is None:
        raise AssertionError(f"{relative} has no function named {name!r}")
    return found


def _callee(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def calls(fn) -> set[str]:
    """The names of everything ``fn`` calls, attribute calls by final segment."""
    return {name for name in (_callee(node) for node in ast.walk(fn)
                              if isinstance(node, ast.Call))
            if name is not None}


def call_order(fn, wanted) -> list[str]:
    """The wanted callees in the order they appear in ``fn``'s source.

    Source order, not execution order — which is the right question for "the
    package manager is tried before the repo-local fallback", where the two are
    sequential statements in one function.
    """
    wanted = set(wanted)
    found = [(node.lineno, _callee(node)) for node in ast.walk(fn)
             if isinstance(node, ast.Call) and _callee(node) in wanted]
    return [name for _, name in sorted(found)]


def literal_lists(fn) -> list[list]:
    """Every list literal in ``fn`` whose elements are all constants.

    This is how an argv is asserted on: ``["winget", "install", …]`` is a list
    of constants, and reading it from the tree says what the command *is*
    rather than what the file happens to contain.
    """
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.List) and node.elts and all(
                isinstance(element, ast.Constant) for element in node.elts):
            out.append([element.value for element in node.elts])
    return out


def string_constants(fn) -> set[str]:
    """Every string literal in ``fn`` — docstring included, so filter if needed."""
    return {node.value for node in ast.walk(fn)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def code_strings(fn) -> set[str]:
    """String literals excluding docstrings.

    A docstring may legitimately *name* a symbol the code must not use — this
    repository has a comment explaining why ``_ffmpeg_on_path()`` was removed
    sitting inside the very function forbidden to call it. Prose is not code.
    """
    docstrings = set()
    for node in ast.walk(fn):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(doc)
    return string_constants(fn) - docstrings


def reaches(relative: str, entry: str, target: str) -> bool:
    """Whether ``target`` is reachable from ``entry`` in the module's call graph.

    A conservative name-based walk: it follows calls to functions defined in the
    same module and matches attribute calls by their final segment, which is what
    lets ``ffmpeg_portable.acquire`` be named as ``acquire``. Conservative in the
    direction that matters — it will not miss an edge that exists.
    """
    table = functions(relative)
    seen: set[str] = set()

    def walk(name: str) -> bool:
        if name in seen:
            return False
        seen.add(name)
        fn = table.get(name)
        if fn is None:
            return False
        called = calls(fn)
        if target in called:
            return True
        return any(walk(other) for other in called)

    return walk(entry)


def assigned_names(fn, callee: str) -> list[str]:
    """Names assigned from a call to ``callee``, e.g. ``x = ensure_ready()``."""
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) \
                and _callee(node.value) == callee:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out.append(target.id)
    return out
