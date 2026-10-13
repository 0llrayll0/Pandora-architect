"""Analisador Python baseado em ``ast`` (parse apenas — nunca executa).

O módulo ``ast`` apenas interpreta a árvore sintática; nenhum ``import`` do
código-alvo é disparado e nenhuma função do repositório é chamada.

O resultado usa modelos intermediários (``FileAnalysis``/``SymbolRecord``/
``ImportRecord``) independentes do parser — a Fase 2 pode trocar ``ast`` por
Tree-sitter sem tocar nos routers nem no banco.
"""

from __future__ import annotations

import ast
import io
import token as token_mod
import tokenize
from dataclasses import dataclass, field

# Nós que aumentam a complexidade ciclomática (aproximação clássica).
_BRANCH_NODES: tuple[type[ast.AST], ...] = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.IfExp,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncWith,
    ast.Assert,
    ast.comprehension,
    ast.Match,
)


@dataclass(slots=True)
class ImportRecord:
    """Um import encontrado no módulo (absoluto ou relativo)."""

    module: str  # módulo referenciado ('' para `import .x` vazio)
    level: int  # 0 = absoluto; >0 = relativo (número de pontos)
    names: list[str] = field(default_factory=list)  # nomes importados
    raw: str = ""  # texto original aproximado
    is_star: bool = False
    lineno: int = 0

    @property
    def is_relative(self) -> bool:
        return self.level > 0


@dataclass(slots=True)
class SymbolRecord:
    """Símbolo extraído (módulo, classe, função ou método)."""

    name: str
    qualified_name: str
    kind: str  # module | class | function | method
    lineno: int = 0
    end_lineno: int = 0
    signature: str = ""
    docstring: str = ""
    decorators: list[str] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    params_count: int = 0
    complexity: int = 1
    is_async: bool = False
    is_public: bool = True


@dataclass(slots=True)
class LineStats:
    """Contagem de linhas do arquivo."""

    total: int = 0
    code: int = 0
    comment: int = 0
    blank: int = 0


@dataclass(slots=True)
class FileAnalysis:
    """Modelo intermediário comum de um arquivo analisado."""

    path: str  # relativo à raiz do projeto
    language: str
    size_bytes: int = 0
    lines: LineStats = field(default_factory=LineStats)
    symbols: list[SymbolRecord] = field(default_factory=list)
    imports: list[ImportRecord] = field(default_factory=list)
    parse_ok: bool = True
    parse_error: str = ""
    sha256: str = ""


def _doc(node: ast.AST) -> str:
    """Docstring do nó ou string vazia (nunca levanta)."""
    try:
        value = ast.get_docstring(node)  # type: ignore[arg-type]
    except TypeError:  # pragma: no cover
        return ""
    if not value:
        return ""
    return " ".join(value.split())[:2000]


def _dotted(node: ast.AST) -> str:
    """Representação pontilhada de Name/Attribute/Constant."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Subscript):
        return _dotted(node.value)
    if isinstance(node, ast.Call):
        return _dotted(node.func)
    return ""


def _format_arg(arg: ast.arg, default: ast.AST | None = None) -> str:
    text = arg.arg
    if arg.annotation is not None:
        text += f": {_dotted(arg.annotation)}"
    if default is not None:
        # _dotted só renderiza nomes; literais (1, False, "x") exigem unparse
        text += f"={ast.unparse(default)}"
    return text


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, int]:
    """Assinatura textual + contagem de parâmetros (inclui *args/**kwargs)."""
    args = node.args
    parts: list[str] = []

    positional = list(args.posonlyargs) + list(args.args)
    defaults = list(args.defaults)
    # defaults alinham com o fim da lista posicional
    default_offset = len(positional) - len(defaults)

    for index, arg in enumerate(positional):
        default = defaults[index - default_offset] if index >= default_offset else None
        text = _format_arg(arg, default)
        if args.posonlyargs and index == len(args.posonlyargs):
            parts.append("/")
        parts.append(text)

    if args.vararg is not None:
        parts.append("*" + _format_arg(args.vararg))
    elif args.kwonlyargs:
        parts.append("*")

    for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=False):
        parts.append(_format_arg(arg, default))

    if args.kwarg is not None:
        parts.append("**" + _format_arg(args.kwarg))

    params_count = (
        len(positional)
        + len(args.kwonlyargs)
        + (1 if args.vararg else 0)
        + (1 if args.kwarg else 0)
    )
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    return f"{prefix}{node.name}({', '.join(parts)})", params_count


def _complexity(node: ast.AST) -> int:
    """Complexidade ciclomática aproximada (1 + ramificações)."""
    score = 1
    for child in ast.walk(node):
        if isinstance(child, _BRANCH_NODES):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += max(1, len(child.values) - 1)
    return score


def _calls_in(node: ast.AST) -> list[str]:
    """Nomes de chamadas detectáveis (Name e Attribute) sob o nó."""
    found: list[str] = []
    seen: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        name = _dotted(child.func)
        if name and name not in seen:
            seen.add(name)
            found.append(name)
    return sorted(found)


def _decorator_names(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> list[str]:
    names: list[str] = []
    for dec in node.decorator_list:
        text = _dotted(dec)
        names.append(text or "<decorator>")
    return names


def _base_names(node: ast.ClassDef) -> list[str]:
    names: list[str] = []
    for base in node.bases:
        text = _dotted(base)
        if text:
            names.append(text)
    return names


def line_stats(text: str) -> LineStats:
    """Contagem de linhas totais/em branco/comentário/código.

    Usa ``tokenize`` quando o arquivo é válido; cai para uma heurística
    linha-a-linha quando há erro de sintaxe.
    """
    lines = text.splitlines()
    total = len(lines)
    if not text:
        return LineStats(0, 0, 0, 0)

    code_rows: set[int] = set()
    comment_rows: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type in {token_mod.NL, tokenize.NEWLINE, token_mod.ENDMARKER}:
                continue
            first, last = tok.start[0], tok.end[0]
            if tok.type == token_mod.COMMENT:
                comment_rows.update(range(first, last + 1))
            else:
                # strings multilinha cobrem todas as linhas que ocupam
                code_rows.update(range(first, last + 1))
        code = len(code_rows)
        comment = len(comment_rows - code_rows)
        blank = max(0, total - code - comment)
    except (tokenize.TokenError, IndentationError, SyntaxError, UnicodeDecodeError):
        # fallback heurístico para arquivos sintaticamente inválidos
        code = comment = blank = 0
        for line in lines:
            stripped = line.strip()
            if not stripped:
                blank += 1
            elif stripped.startswith("#"):
                comment += 1
            else:
                code += 1

    return LineStats(total=total, code=code, comment=comment, blank=blank)


def _collect_imports(tree: ast.Module) -> list[ImportRecord]:
    records: list[ImportRecord] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                records.append(
                    ImportRecord(
                        module=alias.name,
                        level=0,
                        names=[alias.asname or alias.name.split(".")[0]],
                        raw=f"import {alias.name}"
                        + (f" as {alias.asname}" if alias.asname else ""),
                        lineno=node.lineno,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names: list[str] = []
            is_star = False
            for alias in node.names:
                if alias.name == "*":
                    is_star = True
                    names.append("*")
                else:
                    names.append(alias.asname or alias.name)
            dots = "." * node.level
            raw = f"from {dots}{module} import {', '.join(a.name for a in node.names)}"
            records.append(
                ImportRecord(
                    module=module,
                    level=node.level,
                    names=names,
                    raw=raw,
                    is_star=is_star,
                    lineno=node.lineno,
                )
            )
    return records


def _function_symbol(
    node: ast.FunctionDef | ast.AsyncFunctionDef, qual_prefix: str
) -> SymbolRecord:
    signature, params_count = _signature(node)
    return SymbolRecord(
        name=node.name,
        qualified_name=f"{qual_prefix}.{node.name}" if qual_prefix else node.name,
        kind="function",
        lineno=node.lineno,
        end_lineno=getattr(node, "end_lineno", node.lineno) or node.lineno,
        signature=signature,
        docstring=_doc(node),
        decorators=_decorator_names(node),
        calls=_calls_in(node),
        params_count=params_count,
        complexity=_complexity(node),
        is_async=isinstance(node, ast.AsyncFunctionDef),
        is_public=not node.name.startswith("_"),
    )


def _class_symbol(
    node: ast.ClassDef, qual_prefix: str
) -> tuple[SymbolRecord, list[SymbolRecord]]:
    """Extrai a classe e seus métodos."""
    qual = f"{qual_prefix}.{node.name}" if qual_prefix else node.name
    class_rec = SymbolRecord(
        name=node.name,
        qualified_name=qual,
        kind="class",
        lineno=node.lineno,
        end_lineno=getattr(node, "end_lineno", node.lineno) or node.lineno,
        signature=f"class {node.name}({', '.join(_base_names(node))})"
        if _base_names(node)
        else f"class {node.name}",
        docstring=_doc(node),
        decorators=_decorator_names(node),
        bases=_base_names(node),
        calls=_calls_in(node),
        params_count=0,
        complexity=_complexity(node),
        is_public=not node.name.startswith("_"),
    )
    methods: list[SymbolRecord] = []
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            method = _function_symbol(child, qual)
            method.kind = "method"
            methods.append(method)
        elif isinstance(child, ast.ClassDef):  # classe aninhada
            nested, nested_methods = _class_symbol(child, qual)
            methods.append(nested)
            methods.extend(nested_methods)
    return class_rec, methods


def analyze_python_source(
    source: str,
    *,
    path: str,
    size_bytes: int = 0,
    sha256: str = "",
) -> FileAnalysis:
    """Analisa uma fonte Python com ``ast``. Nunca executa o código.

    Arquivo sintaticamente inválido → ``parse_ok=False`` + mensagem de erro,
    com contagens de linha preservadas. A análise do projeto não aborta.
    """
    stats = line_stats(source)
    analysis = FileAnalysis(
        path=path,
        language="python",
        size_bytes=size_bytes,
        lines=stats,
        sha256=sha256,
    )
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        analysis.parse_ok = False
        loc = f"linha {exc.lineno}" if exc.lineno else "posição desconhecida"
        analysis.parse_error = f"SyntaxError: {exc.msg} ({loc})"
        return analysis
    except ValueError as exc:  # nul byte / encoding
        analysis.parse_ok = False
        analysis.parse_error = f"ValueError: {exc}"
        return analysis

    module_name = path[:-3].replace("/", ".") if path.endswith(".py") else path
    if module_name.endswith(".__init__"):
        module_name = module_name[: -len(".__init__")]

    analysis.imports = _collect_imports(tree)
    module_symbol = SymbolRecord(
        name=module_name.split(".")[-1] or path,
        qualified_name=module_name,
        kind="module",
        lineno=1,
        end_lineno=stats.total,
        docstring=_doc(tree),
        calls=_calls_in(tree),
        complexity=_complexity(tree),
        is_public=not module_name.split(".")[-1].startswith("_"),
    )
    analysis.symbols.append(module_symbol)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            analysis.symbols.append(_function_symbol(node, module_name))
        elif isinstance(node, ast.ClassDef):
            class_rec, methods = _class_symbol(node, module_name)
            analysis.symbols.append(class_rec)
            analysis.symbols.extend(methods)

    return analysis
