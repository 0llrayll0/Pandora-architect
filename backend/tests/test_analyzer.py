"""Testes do analisador Python (``ast``) — nunca executa código-alvo."""

from __future__ import annotations

from app.analysis.python_analyzer import analyze_python_source, line_stats

# ---------------------------------------------------------------------------
# Símbolos, assinatura e complexidade
# ---------------------------------------------------------------------------

SOURCE_FN = '''\
def f(a, b=1, *args, flag=False, **kwargs):
    """Doc."""
    if a and b:
        for x in range(3):
            pass
    while flag:
        pass
    return [y for y in range(2)]
'''


def test_analyze_function_signature_and_complexity() -> None:
    analysis = analyze_python_source(SOURCE_FN, path="mod.py")

    assert analysis.parse_ok is True
    fn = next(s for s in analysis.symbols if s.kind == "function")
    assert fn.name == "f"
    assert fn.qualified_name == "mod.f"
    assert fn.signature == "def f(a, b=1, *args, flag=False, **kwargs)"
    assert fn.params_count == 5
    # 1 + if + boolop(and) + for + while + comprehension
    assert fn.complexity == 6
    assert fn.docstring == "Doc."
    assert fn.calls == ["range"]
    assert fn.is_async is False
    assert fn.is_public is True


def test_analyze_module_symbol() -> None:
    analysis = analyze_python_source(SOURCE_FN, path="pkg/mod.py")
    module = next(s for s in analysis.symbols if s.kind == "module")
    assert module.name == "mod"
    assert module.qualified_name == "pkg.mod"
    assert module.lineno == 1


def test_analyze_init_package_module_name() -> None:
    analysis = analyze_python_source('"""Pacote."""\n', path="pkg_a/__init__.py")
    module = next(s for s in analysis.symbols if s.kind == "module")
    assert module.qualified_name == "pkg_a"
    assert module.name == "pkg_a"
    assert module.docstring == "Pacote."


def test_analyze_class_methods_and_nested() -> None:
    source = '''\
class Base:
    pass


@deco
class C(Base):
    """Doc da classe."""

    def meth(self, x):
        return x

    class Inner:
        pass
'''
    analysis = analyze_python_source(source, path="mod.py")
    by_qname = {s.qualified_name: s for s in analysis.symbols}

    cls = by_qname["mod.C"]
    assert cls.kind == "class"
    assert cls.signature == "class C(Base)"
    assert cls.bases == ["Base"]
    assert cls.decorators == ["deco"]
    assert cls.docstring == "Doc da classe."

    method = by_qname["mod.C.meth"]
    assert method.kind == "method"
    assert method.signature == "def meth(self, x)"
    assert method.params_count == 2

    assert "mod.C.Inner" in by_qname  # classe aninhada vira símbolo
    assert "mod.Base" in by_qname


def test_analyze_async_function() -> None:
    analysis = analyze_python_source("async def go(a):\n    return a\n", path="m.py")
    fn = next(s for s in analysis.symbols if s.kind == "function")
    assert fn.is_async is True
    assert fn.signature == "async def go(a)"


def test_analyze_private_symbol_flagged() -> None:
    analysis = analyze_python_source("def _oculta():\n    pass\n", path="m.py")
    fn = next(s for s in analysis.symbols if s.kind == "function")
    assert fn.is_public is False


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


def test_analyze_collects_imports() -> None:
    source = """\
import os
import a.b as ab
from x import y
from x import *
from . import m
from ..pkg import n
"""
    analysis = analyze_python_source(source, path="pkg/sub/mod.py")
    records = analysis.imports
    assert len(records) == 6

    os_rec = records[0]
    assert (os_rec.module, os_rec.level, os_rec.names) == ("os", 0, ["os"])
    assert os_rec.raw == "import os"

    alias_rec = records[1]
    assert (alias_rec.module, alias_rec.names) == ("a.b", ["ab"])
    assert alias_rec.raw == "import a.b as ab"

    from_rec = records[2]
    assert (from_rec.module, from_rec.names, from_rec.is_star) == ("x", ["y"], False)

    star_rec = records[3]
    assert star_rec.is_star is True
    assert star_rec.names == ["*"]

    rel_rec = records[4]
    assert (rel_rec.module, rel_rec.level, rel_rec.names) == ("", 1, ["m"])
    assert rel_rec.raw == "from . import m"

    deep_rec = records[5]
    assert (deep_rec.module, deep_rec.level, deep_rec.names) == ("pkg", 2, ["n"])
    assert deep_rec.is_relative is True


# ---------------------------------------------------------------------------
# Erro de sintaxe / contagem de linhas / casos vazios
# ---------------------------------------------------------------------------


def test_analyze_broken_syntax_does_not_raise() -> None:
    analysis = analyze_python_source("def quebrado(:\n    return 1\n", path="broken.py")
    assert analysis.parse_ok is False
    assert "SyntaxError" in analysis.parse_error
    assert "linha" in analysis.parse_error
    assert analysis.symbols == []
    assert analysis.imports == []
    assert analysis.lines.total == 2  # contagens de linha preservadas


def test_analyze_empty_source() -> None:
    analysis = analyze_python_source("", path="vazio.py")
    assert analysis.parse_ok is True
    assert len(analysis.symbols) == 1  # apenas o símbolo de módulo
    assert analysis.symbols[0].kind == "module"
    assert analysis.symbols[0].qualified_name == "vazio"
    assert analysis.lines.total == 0


def test_line_stats_counts() -> None:
    stats = line_stats("import os\n\n# c\nx = 1\n")
    assert stats.total == 4
    assert stats.code == 2
    assert stats.comment == 1
    assert stats.blank == 1


def test_line_stats_fallback_on_invalid_syntax() -> None:
    stats = line_stats("def x(:\n# c\n\ny = 1\n")
    assert stats.total == 4
    assert stats.code == 2
    assert stats.comment == 1
    assert stats.blank == 1


def test_line_stats_empty() -> None:
    stats = line_stats("")
    assert (stats.total, stats.code, stats.comment, stats.blank) == (0, 0, 0, 0)
