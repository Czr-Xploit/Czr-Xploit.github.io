"""
Minimal, safe, dependency-free template engine.

Design constraints
------------------
* Standard library only.
* No ``eval``/``exec`` of template-supplied text.  Expressions are parsed into
  an AST by a hand written recursive descent parser and evaluated by walking
  that AST.  There is deliberately **no call syntax** in the expression
  grammar, so a template can never invoke arbitrary Python.
* Autoescaping is on by default.  Getting raw output requires explicit,
  greppable syntax (``{{{ x }}}`` or the ``| safe`` filter).

Syntax
------
``{{ expr }}``                escaped interpolation
``{{{ expr }}}``              raw interpolation (no escaping)
``{{ expr | filter:arg }}``   filters, chainable
``{# comment #}``             comment, produces nothing
``{% if e %}``/``{% elif e %}``/``{% else %}``/``{% endif %}``
``{% for x in e %}``/``{% empty %}``/``{% endfor %}``
``{% set name = e %}``
``{% include "path.html" %}``
``{% extends "base.html" %}`` + ``{% block name %}``/``{% endblock %}``
``{% raw %}``/``{% endraw %}``

Inside a ``for`` body the ``loop`` variable exposes ``index`` (1-based),
``index0``, ``first``, ``last``, ``length`` and ``parent``.
"""

from __future__ import annotations

import html
import json
import os
import re
import unicodedata
from datetime import date, datetime
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Sequence

__all__ = ["TemplateEngine", "TemplateError", "TemplateSyntaxError", "Markup", "escape"]


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #

class TemplateError(Exception):
    """Base class for every template failure."""


class TemplateSyntaxError(TemplateError):
    def __init__(self, message: str, *, template: str = "<string>", line: int = 0) -> None:
        self.template = template
        self.line = line
        super().__init__(f"{template}:{line}: {message}")


class TemplateRuntimeError(TemplateError):
    pass


# --------------------------------------------------------------------------- #
# Markup / escaping
# --------------------------------------------------------------------------- #

class Markup(str):
    """A string that is already safe HTML and must not be escaped again."""

    __slots__ = ()

    def __html__(self) -> str:  # pragma: no cover - trivial
        return str(self)


def escape(value: Any) -> str:
    """HTML-escape ``value`` unless it declares itself safe.

    Quotes are escaped too, so the result is safe in a double- or
    single-quoted attribute as well as in text position.
    """
    if value is None:
        return ""
    if isinstance(value, Markup):
        return str(value)
    if hasattr(value, "__html__"):
        return str(value.__html__())
    if value is True:
        return "true"
    if value is False:
        return "false"
    return html.escape(str(value), quote=True).replace("'", "&#x27;")


# --------------------------------------------------------------------------- #
# Expression AST
# --------------------------------------------------------------------------- #

class _Node:
    __slots__ = ()


class _Const(_Node):
    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value


class _Name(_Node):
    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name


class _Attr(_Node):
    __slots__ = ("obj", "attr")

    def __init__(self, obj: _Node, attr: str) -> None:
        self.obj = obj
        self.attr = attr


class _Item(_Node):
    __slots__ = ("obj", "key")

    def __init__(self, obj: _Node, key: _Node) -> None:
        self.obj = obj
        self.key = key


class _Unary(_Node):
    __slots__ = ("op", "operand")

    def __init__(self, op: str, operand: _Node) -> None:
        self.op = op
        self.operand = operand


class _Binary(_Node):
    __slots__ = ("op", "left", "right")

    def __init__(self, op: str, left: _Node, right: _Node) -> None:
        self.op = op
        self.left = left
        self.right = right


class _ListLit(_Node):
    __slots__ = ("items",)

    def __init__(self, items: list[_Node]) -> None:
        self.items = items


class _FilterCall(_Node):
    __slots__ = ("source", "name", "args")

    def __init__(self, source: _Node, name: str, args: list[_Node]) -> None:
        self.source = source
        self.name = name
        self.args = args


# --------------------------------------------------------------------------- #
# Expression lexer
# --------------------------------------------------------------------------- #

_TOKEN_RE = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<number>\d+\.\d+|\d+)
    | (?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
    | (?P<name>[A-Za-z_][A-Za-z_0-9]*)
    | (?P<op><=|>=|==|!=|\|\||&&|[-+*/%<>.,:()\[\]|!])
    """,
    re.VERBOSE,
)

_KEYWORDS = {"and", "or", "not", "in", "is", "true", "false", "none", "null", "True", "False", "None"}


class _Token:
    __slots__ = ("kind", "value", "pos")

    def __init__(self, kind: str, value: str, pos: int) -> None:
        self.kind = kind
        self.value = value
        self.pos = pos

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Token {self.kind} {self.value!r}>"


def _lex_expression(source: str) -> list[_Token]:
    tokens: list[_Token] = []
    pos = 0
    length = len(source)
    while pos < length:
        match = _TOKEN_RE.match(source, pos)
        if match is None:
            raise TemplateSyntaxError(f"unexpected character {source[pos]!r} in expression {source!r}")
        pos = match.end()
        kind = match.lastgroup or ""
        if kind == "ws":
            continue
        value = match.group()
        if kind == "name" and value in _KEYWORDS:
            kind = "keyword"
        tokens.append(_Token(kind, value, match.start()))
    tokens.append(_Token("end", "", length))
    return tokens


# --------------------------------------------------------------------------- #
# Expression parser (recursive descent, precedence climbing)
# --------------------------------------------------------------------------- #

class _ExpressionParser:
    """Parses the expression mini-language into a ``_Node`` tree.

    Deliberately omits call syntax; the only way to invoke behaviour is a
    registered filter, and the filter registry is controlled by the host
    application rather than by the template.
    """

    def __init__(self, source: str) -> None:
        self.source = source
        self.tokens = _lex_expression(source)
        self.index = 0

    # -- token helpers ---------------------------------------------------- #

    @property
    def current(self) -> _Token:
        return self.tokens[self.index]

    def advance(self) -> _Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def accept(self, kind: str, value: str | None = None) -> _Token | None:
        token = self.current
        if token.kind != kind:
            return None
        if value is not None and token.value != value:
            return None
        return self.advance()

    def expect(self, kind: str, value: str | None = None) -> _Token:
        token = self.accept(kind, value)
        if token is None:
            want = value or kind
            raise TemplateSyntaxError(
                f"expected {want!r} but found {self.current.value!r} in expression {self.source!r}"
            )
        return token

    # -- grammar ---------------------------------------------------------- #

    def parse(self) -> _Node:
        node = self.parse_filters()
        if self.current.kind != "end":
            raise TemplateSyntaxError(
                f"unexpected {self.current.value!r} at end of expression {self.source!r}"
            )
        return node

    def parse_filters(self) -> _Node:
        node = self.parse_or()
        while self.accept("op", "|"):
            name = self.expect("name").value
            args: list[_Node] = []
            if self.accept("op", ":"):
                args.append(self.parse_or())
                while self.accept("op", ","):
                    args.append(self.parse_or())
            node = _FilterCall(node, name, args)
        return node

    def parse_or(self) -> _Node:
        node = self.parse_and()
        while self.accept("keyword", "or") or self.accept("op", "||"):
            node = _Binary("or", node, self.parse_and())
        return node

    def parse_and(self) -> _Node:
        node = self.parse_not()
        while self.accept("keyword", "and") or self.accept("op", "&&"):
            node = _Binary("and", node, self.parse_not())
        return node

    def parse_not(self) -> _Node:
        if self.accept("keyword", "not") or self.accept("op", "!"):
            return _Unary("not", self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self) -> _Node:
        node = self.parse_additive()
        while True:
            if self.accept("keyword", "not"):
                self.expect("keyword", "in")
                node = _Unary("not", _Binary("in", node, self.parse_additive()))
                continue
            if self.accept("keyword", "in"):
                node = _Binary("in", node, self.parse_additive())
                continue
            if self.accept("keyword", "is"):
                negate = self.accept("keyword", "not") is not None
                right = self.parse_additive()
                node = _Binary("is", node, right)
                if negate:
                    node = _Unary("not", node)
                continue
            token = self.current
            if token.kind == "op" and token.value in ("==", "!=", "<", "<=", ">", ">="):
                self.advance()
                node = _Binary(token.value, node, self.parse_additive())
                continue
            return node

    def parse_additive(self) -> _Node:
        node = self.parse_multiplicative()
        while True:
            token = self.current
            if token.kind == "op" and token.value in ("+", "-"):
                self.advance()
                node = _Binary(token.value, node, self.parse_multiplicative())
                continue
            return node

    def parse_multiplicative(self) -> _Node:
        node = self.parse_unary()
        while True:
            token = self.current
            if token.kind == "op" and token.value in ("*", "/", "%"):
                self.advance()
                node = _Binary(token.value, node, self.parse_unary())
                continue
            return node

    def parse_unary(self) -> _Node:
        if self.accept("op", "-"):
            return _Unary("-", self.parse_unary())
        if self.accept("op", "+"):
            return self.parse_unary()
        return self.parse_postfix()

    def parse_postfix(self) -> _Node:
        node = self.parse_primary()
        while True:
            if self.accept("op", "."):
                token = self.current
                if token.kind in ("name", "keyword"):
                    self.advance()
                    node = _Attr(node, token.value)
                elif token.kind == "number":
                    self.advance()
                    node = _Item(node, _Const(int(token.value)))
                else:
                    raise TemplateSyntaxError(
                        f"expected an attribute name after '.' in {self.source!r}"
                    )
                continue
            if self.accept("op", "["):
                key = self.parse_or()
                self.expect("op", "]")
                node = _Item(node, key)
                continue
            return node

    def parse_primary(self) -> _Node:
        token = self.current
        if token.kind == "number":
            self.advance()
            return _Const(float(token.value) if "." in token.value else int(token.value))
        if token.kind == "string":
            self.advance()
            return _Const(_unquote(token.value))
        if token.kind == "keyword":
            self.advance()
            if token.value in ("true", "True"):
                return _Const(True)
            if token.value in ("false", "False"):
                return _Const(False)
            if token.value in ("none", "null", "None"):
                return _Const(None)
            raise TemplateSyntaxError(f"unexpected keyword {token.value!r} in {self.source!r}")
        if token.kind == "name":
            self.advance()
            return _Name(token.value)
        if self.accept("op", "("):
            node = self.parse_filters()
            self.expect("op", ")")
            return node
        if self.accept("op", "["):
            items: list[_Node] = []
            if not self.accept("op", "]"):
                items.append(self.parse_or())
                while self.accept("op", ","):
                    items.append(self.parse_or())
                self.expect("op", "]")
            return _ListLit(items)
        raise TemplateSyntaxError(f"unexpected {token.value!r} in expression {self.source!r}")


def _unquote(literal: str) -> str:
    body = literal[1:-1]
    out: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\" and index + 1 < len(body):
            nxt = body[index + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'"}.get(nxt, nxt))
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


# --------------------------------------------------------------------------- #
# Expression evaluation
# --------------------------------------------------------------------------- #

_UNSAFE_ATTR = re.compile(r"^__|^func_|^im_|^gi_|^cr_|^tb_")

_SAFE_STR_METHODS = {
    "upper", "lower", "title", "strip", "lstrip", "rstrip", "capitalize",
    "split", "splitlines", "startswith", "endswith", "count", "replace",
}


def _resolve(obj: Any, attr: str) -> Any:
    """Look ``attr`` up on ``obj`` with mapping-first semantics.

    Dunder and internal attributes are refused outright so that a template
    cannot walk from any object to ``__class__``/``__globals__`` and out into
    the interpreter.
    """
    if _UNSAFE_ATTR.match(attr):
        raise TemplateRuntimeError(f"access to {attr!r} is not permitted in templates")
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        if attr in obj:
            return obj[attr]
        return _Undefined(attr)
    if isinstance(obj, (list, tuple)) and attr.isdigit():
        index = int(attr)
        return obj[index] if index < len(obj) else _Undefined(attr)
    if isinstance(obj, str) and attr in _SAFE_STR_METHODS:
        return getattr(obj, attr)
    try:
        value = getattr(obj, attr)
    except AttributeError:
        return _Undefined(attr)
    if callable(value) and not isinstance(value, type) and getattr(value, "_template_safe", False) is not True:
        # Bare callables are not auto-invoked; expose data, not behaviour.
        return _Undefined(attr)
    return value


class _Undefined:
    """A missing value that is falsy, renders empty and chains silently."""

    __slots__ = ("name",)

    def __init__(self, name: str = "") -> None:
        self.name = name

    def __bool__(self) -> bool:
        return False

    def __str__(self) -> str:
        return ""

    def __len__(self) -> int:
        return 0

    def __iter__(self):
        return iter(())

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Undefined) or other is None

    def __hash__(self) -> int:
        return hash(None)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<undefined {self.name!r}>"


def _evaluate(node: _Node, context: Mapping[str, Any], filters: Mapping[str, Callable[..., Any]]) -> Any:
    if isinstance(node, _Const):
        return node.value
    if isinstance(node, _Name):
        if node.name in context:
            return context[node.name]
        return _Undefined(node.name)
    if isinstance(node, _Attr):
        return _resolve(_evaluate(node.obj, context, filters), node.attr)
    if isinstance(node, _Item):
        obj = _evaluate(node.obj, context, filters)
        key = _evaluate(node.key, context, filters)
        if obj is None or isinstance(obj, _Undefined):
            return _Undefined()
        try:
            if isinstance(obj, Mapping):
                return obj[key] if key in obj else _Undefined(str(key))
            if isinstance(obj, (list, tuple, str)):
                return obj[int(key)]
            return _resolve(obj, str(key))
        except (KeyError, IndexError, TypeError, ValueError):
            return _Undefined(str(key))
    if isinstance(node, _ListLit):
        return [_evaluate(item, context, filters) for item in node.items]
    if isinstance(node, _Unary):
        value = _evaluate(node.operand, context, filters)
        if node.op == "not":
            return not _truthy(value)
        if node.op == "-":
            return -_number(value)
        raise TemplateRuntimeError(f"unknown unary operator {node.op!r}")
    if isinstance(node, _Binary):
        return _evaluate_binary(node, context, filters)
    if isinstance(node, _FilterCall):
        function = filters.get(node.name)
        if function is None:
            raise TemplateRuntimeError(f"unknown filter {node.name!r}")
        value = _evaluate(node.source, context, filters)
        args = [_evaluate(argument, context, filters) for argument in node.args]
        return function(value, *args)
    raise TemplateRuntimeError(f"cannot evaluate node {node!r}")


def _evaluate_binary(node: _Binary, context: Mapping[str, Any], filters: Mapping[str, Callable[..., Any]]) -> Any:
    op = node.op
    if op == "and":
        left = _evaluate(node.left, context, filters)
        return _evaluate(node.right, context, filters) if _truthy(left) else left
    if op == "or":
        left = _evaluate(node.left, context, filters)
        return left if _truthy(left) else _evaluate(node.right, context, filters)

    left = _evaluate(node.left, context, filters)
    right = _evaluate(node.right, context, filters)

    if op == "in":
        try:
            if isinstance(right, (str,)):
                return str(left) in right
            return left in right  # type: ignore[operator]
        except TypeError:
            return False
    if op == "is":
        return left is right or (isinstance(left, _Undefined) and right is None)
    if op == "==":
        return _compare_equal(left, right)
    if op == "!=":
        return not _compare_equal(left, right)
    if op in ("<", "<=", ">", ">="):
        try:
            if op == "<":
                return left < right  # type: ignore[operator]
            if op == "<=":
                return left <= right  # type: ignore[operator]
            if op == ">":
                return left > right  # type: ignore[operator]
            return left >= right  # type: ignore[operator]
        except TypeError:
            return False
    if op == "+":
        if isinstance(left, str) or isinstance(right, str):
            return _stringify(left) + _stringify(right)
        if isinstance(left, list) and isinstance(right, list):
            return left + right
        return _number(left) + _number(right)
    if op == "-":
        return _number(left) - _number(right)
    if op == "*":
        if isinstance(left, str) and isinstance(right, (int, float)):
            return left * int(right)
        return _number(left) * _number(right)
    if op == "/":
        divisor = _number(right)
        return 0 if divisor == 0 else _number(left) / divisor
    if op == "%":
        divisor = _number(right)
        return 0 if divisor == 0 else _number(left) % divisor
    raise TemplateRuntimeError(f"unknown operator {op!r}")


def _compare_equal(left: Any, right: Any) -> bool:
    if isinstance(left, _Undefined) or isinstance(right, _Undefined):
        return bool(left) == bool(right) and not left and not right
    return bool(left == right)


def _truthy(value: Any) -> bool:
    if isinstance(value, _Undefined):
        return False
    return bool(value)


def _number(value: Any) -> float | int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value) if "." in value else int(value)
        except ValueError:
            return 0
    return 0


def _stringify(value: Any) -> str:
    if value is None or isinstance(value, _Undefined):
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


# --------------------------------------------------------------------------- #
# Template nodes
# --------------------------------------------------------------------------- #

class _Text:
    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text


class _Output:
    __slots__ = ("expression", "raw")

    def __init__(self, expression: _Node, raw: bool) -> None:
        self.expression = expression
        self.raw = raw


class _If:
    __slots__ = ("branches", "otherwise")

    def __init__(self, branches: list[tuple[_Node, list[Any]]], otherwise: list[Any] | None) -> None:
        self.branches = branches
        self.otherwise = otherwise


class _For:
    __slots__ = ("target", "iterable", "body", "empty")

    def __init__(self, target: list[str], iterable: _Node, body: list[Any], empty: list[Any] | None) -> None:
        self.target = target
        self.iterable = iterable
        self.body = body
        self.empty = empty


class _Set:
    __slots__ = ("name", "expression")

    def __init__(self, name: str, expression: _Node) -> None:
        self.name = name
        self.expression = expression


class _Include:
    __slots__ = ("name", "expression")

    def __init__(self, name: str | None, expression: _Node | None) -> None:
        self.name = name
        self.expression = expression


class _Block:
    __slots__ = ("name", "body")

    def __init__(self, name: str, body: list[Any]) -> None:
        self.name = name
        self.body = body


class _CompiledTemplate:
    __slots__ = ("name", "nodes", "parent", "blocks")

    def __init__(self, name: str, nodes: list[Any], parent: str | None, blocks: dict[str, list[Any]]) -> None:
        self.name = name
        self.nodes = nodes
        self.parent = parent
        self.blocks = blocks


# --------------------------------------------------------------------------- #
# Template parser
# --------------------------------------------------------------------------- #

_TAG_RE = re.compile(
    r"""
      \{\#(?P<comment>.*?)\#\}
    | \{\{\{(?P<raw>.*?)\}\}\}
    | \{\{(?P<var>.*?)\}\}
    | \{%(?P<tag>.*?)%\}
    """,
    re.VERBOSE | re.DOTALL,
)

_BLOCK_TRIM_RE = re.compile(r"\n[ \t]*$")


class _TemplateParser:
    def __init__(self, source: str, name: str) -> None:
        self.source = source
        self.name = name
        self.position = 0
        self.line = 1
        self.parent: str | None = None
        self.blocks: dict[str, list[Any]] = {}

    def fail(self, message: str) -> "TemplateSyntaxError":
        return TemplateSyntaxError(message, template=self.name, line=self.line)

    def parse(self) -> _CompiledTemplate:
        nodes = self.parse_nodes(set())
        return _CompiledTemplate(self.name, nodes, self.parent, self.blocks)

    def parse_nodes(self, stop: set[str]) -> list[Any]:
        nodes: list[Any] = []
        while True:
            match = _TAG_RE.search(self.source, self.position)
            if match is None:
                tail = self.source[self.position:]
                if tail:
                    nodes.append(_Text(tail))
                self.position = len(self.source)
                if stop:
                    raise self.fail(f"unclosed block, expected one of {sorted(stop)}")
                return nodes

            leading = self.source[self.position:match.start()]
            self.line += leading.count("\n")
            self.position = match.end()

            if match.lastgroup == "comment" or match.group("comment") is not None:
                if leading:
                    nodes.append(_Text(leading))
                self.line += match.group(0).count("\n")
                continue

            raw_expression = match.group("raw")
            var_expression = match.group("var")
            tag_source = match.group("tag")

            if raw_expression is not None or var_expression is not None:
                if leading:
                    nodes.append(_Text(leading))
                text = (raw_expression if raw_expression is not None else var_expression) or ""
                nodes.append(_Output(_parse_expression(text.strip()), raw_expression is not None))
                self.line += match.group(0).count("\n")
                continue

            assert tag_source is not None
            statement = tag_source.strip()
            keyword, _, rest = statement.partition(" ")
            keyword = keyword.strip()
            rest = rest.strip()

            if keyword in stop:
                # Trim the newline+indent that precedes a standalone block tag so
                # that control flow does not litter the output with blank lines.
                if leading:
                    nodes.append(_Text(_BLOCK_TRIM_RE.sub("\n", leading)))
                self.pending = (keyword, rest)
                return nodes

            if leading:
                nodes.append(_Text(_BLOCK_TRIM_RE.sub("\n", leading)))
            self.line += match.group(0).count("\n")
            nodes.append(self.parse_statement(keyword, rest))

    def parse_statement(self, keyword: str, rest: str) -> Any:
        if keyword == "if":
            return self.parse_if(rest)
        if keyword == "for":
            return self.parse_for(rest)
        if keyword == "set":
            name, _, expression = rest.partition("=")
            name = name.strip()
            if not name.isidentifier():
                raise self.fail(f"invalid variable name {name!r} in set")
            return _Set(name, _parse_expression(expression.strip()))
        if keyword == "include":
            return self.parse_include(rest)
        if keyword == "extends":
            if self.parent is not None:
                raise self.fail("a template may only extend one parent")
            self.parent = _literal_name(rest, self)
            return _Text("")
        if keyword == "block":
            return self.parse_block(rest)
        if keyword == "raw":
            return self.parse_raw()
        raise self.fail(f"unknown tag {keyword!r}")

    def parse_if(self, condition: str) -> _If:
        branches: list[tuple[_Node, list[Any]]] = []
        otherwise: list[Any] | None = None
        current_condition = _parse_expression(condition)
        while True:
            body = self.parse_nodes({"elif", "else", "endif"})
            keyword, rest = self.pending
            branches.append((current_condition, body))
            if keyword == "elif":
                current_condition = _parse_expression(rest)
                continue
            if keyword == "else":
                otherwise = self.parse_nodes({"endif"})
                break
            break
        return _If(branches, otherwise)

    def parse_for(self, rest: str) -> _For:
        match = re.match(r"^(?P<target>[A-Za-z_][A-Za-z_0-9]*(?:\s*,\s*[A-Za-z_][A-Za-z_0-9]*)*)\s+in\s+(?P<iterable>.+)$", rest)
        if match is None:
            raise self.fail(f"malformed for tag: {rest!r}")
        target = [part.strip() for part in match.group("target").split(",")]
        iterable = _parse_expression(match.group("iterable").strip())
        body = self.parse_nodes({"empty", "endfor"})
        empty: list[Any] | None = None
        if self.pending[0] == "empty":
            empty = self.parse_nodes({"endfor"})
        return _For(target, iterable, body, empty)

    def parse_include(self, rest: str) -> _Include:
        rest = rest.strip()
        if rest.startswith(("'", '"')):
            return _Include(_literal_name(rest, self), None)
        return _Include(None, _parse_expression(rest))

    def parse_block(self, rest: str) -> _Block:
        name = rest.strip().strip("'\"")
        if not name:
            raise self.fail("block requires a name")
        body = self.parse_nodes({"endblock"})
        self.blocks[name] = body
        return _Block(name, body)

    def parse_raw(self) -> _Text:
        end = self.source.find("{% endraw %}", self.position)
        if end == -1:
            raise self.fail("unclosed raw block")
        text = self.source[self.position:end]
        self.position = end + len("{% endraw %}")
        self.line += text.count("\n")
        return _Text(text)


def _literal_name(rest: str, parser: _TemplateParser) -> str:
    value = rest.strip()
    if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]:
        return value[1:-1]
    raise parser.fail(f"expected a quoted template name, got {rest!r}")


_expression_cache: dict[str, _Node] = {}


def _parse_expression(source: str) -> _Node:
    node = _expression_cache.get(source)
    if node is None:
        node = _ExpressionParser(source).parse()
        _expression_cache[source] = node
    return node


# --------------------------------------------------------------------------- #
# Built-in filters
# --------------------------------------------------------------------------- #

def _filter_default(value: Any, fallback: Any = "") -> Any:
    if isinstance(value, _Undefined) or value is None or value == "":
        return fallback
    return value


def _filter_date(value: Any, fmt: str = "%d %b %Y") -> str:
    if isinstance(value, (datetime, date)):
        return value.strftime(fmt)
    if isinstance(value, str) and value:
        for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value[:len(pattern) + 4], pattern).strftime(fmt)
            except ValueError:
                continue
    return _stringify(value)


def _filter_truncate(value: Any, length: int = 160, suffix: str = "…") -> str:
    text = _stringify(value)
    if len(text) <= length:
        return text
    cut = text[:length].rsplit(" ", 1)[0]
    return cut + suffix


def _filter_json(value: Any) -> Markup:
    """Serialise for embedding inside a ``<script type="application/json">``.

    ``<``, ``>`` and ``&`` are escaped so the payload can never terminate the
    surrounding element or open a new tag, and U+2028/U+2029 are escaped
    because they are line terminators in JavaScript string literals.
    """
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_json_default)
    text = (
        text.replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
            .replace(" ", "\\u2028")
            .replace(" ", "\\u2029")
    )
    return Markup(text)


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, _Undefined):
        return None
    if hasattr(value, "as_dict"):
        return value.as_dict()
    return str(value)


def _filter_slugify(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _stringify(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return re.sub(r"-{2,}", "-", text)


def _filter_join(value: Any, separator: str = ", ") -> str:
    if isinstance(value, (list, tuple)):
        return separator.join(_stringify(item) for item in value)
    return _stringify(value)


def _filter_length(value: Any) -> int:
    try:
        return len(value)
    except TypeError:
        return 0


def _filter_first(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and value:
        return value[0]
    return _Undefined()


def _filter_last(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and value:
        return value[-1]
    return _Undefined()


def _filter_slice(value: Any, start: int = 0, stop: int | None = None) -> Any:
    if not isinstance(value, (list, tuple, str)):
        return value
    return value[int(start):int(stop)] if stop is not None else value[int(start):]


def _filter_reverse(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return list(reversed(value))
    return _stringify(value)[::-1]


def _filter_sort(value: Any, key: str = "") -> Any:
    if not isinstance(value, (list, tuple)):
        return value
    if key:
        return sorted(value, key=lambda item: _stringify(_resolve(item, key)))
    return sorted(value, key=_stringify)


def _filter_attr(value: Any, name: str) -> Any:
    return _resolve(value, name)


def _filter_map(value: Any, name: str) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        return []
    return [_resolve(item, name) for item in value]


def _filter_where(value: Any, name: str, expected: Any = True) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if _compare_equal(_resolve(item, name), expected)]


def _filter_striptags(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", _stringify(value))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _filter_urlencode(value: Any) -> str:
    from urllib.parse import quote

    return quote(_stringify(value), safe="/")


def _filter_attrescape(value: Any) -> str:
    return escape(value)


def _filter_number(value: Any) -> str:
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return _stringify(value)


def _filter_pluralize(value: Any, singular: str = "", plural: str = "s") -> str:
    try:
        return singular if int(value) == 1 else plural
    except (TypeError, ValueError):
        return plural


BUILTIN_FILTERS: dict[str, Callable[..., Any]] = {
    "safe": lambda value: Markup(_stringify(value)),
    "escape": lambda value: Markup(escape(value)),
    "e": lambda value: Markup(escape(value)),
    "upper": lambda value: _stringify(value).upper(),
    "lower": lambda value: _stringify(value).lower(),
    "capitalize": lambda value: _stringify(value).capitalize(),
    "title": lambda value: _stringify(value).title(),
    "trim": lambda value: _stringify(value).strip(),
    "default": _filter_default,
    "date": _filter_date,
    "truncate": _filter_truncate,
    "json": _filter_json,
    "slugify": _filter_slugify,
    "join": _filter_join,
    "length": _filter_length,
    "count": _filter_length,
    "first": _filter_first,
    "last": _filter_last,
    "slice": _filter_slice,
    "reverse": _filter_reverse,
    "sort": _filter_sort,
    "attr": _filter_attr,
    "map": _filter_map,
    "where": _filter_where,
    "striptags": _filter_striptags,
    "urlencode": _filter_urlencode,
    "attrescape": _filter_attrescape,
    "number": _filter_number,
    "pluralize": _filter_pluralize,
    "int": lambda value: int(_number(value)),
    "abs": lambda value: abs(_number(value)),
    "round": lambda value, digits=0: round(_number(value), int(digits)),
}


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #

class TemplateEngine:
    """Loads, caches and renders templates from one or more directories."""

    def __init__(self, search_paths: Sequence[str], *, cache: bool = True) -> None:
        self.search_paths = [os.path.abspath(path) for path in search_paths]
        self.cache_enabled = cache
        self._cache: dict[str, _CompiledTemplate] = {}
        self.filters: MutableMapping[str, Callable[..., Any]] = dict(BUILTIN_FILTERS)
        self.globals: MutableMapping[str, Any] = {}

    # -- loading ---------------------------------------------------------- #

    def resolve_path(self, name: str) -> str:
        """Map a template name to a real file, refusing directory traversal."""
        normalized = os.path.normpath(name).replace("\\", "/")
        if normalized.startswith("..") or os.path.isabs(normalized):
            raise TemplateError(f"illegal template name {name!r}")
        for root in self.search_paths:
            candidate = os.path.join(root, normalized)
            real = os.path.realpath(candidate)
            if not real.startswith(os.path.realpath(root) + os.sep) and real != os.path.realpath(root):
                continue
            if os.path.isfile(real):
                return real
        raise TemplateError(f"template {name!r} not found in {self.search_paths}")

    def load(self, name: str) -> _CompiledTemplate:
        if self.cache_enabled and name in self._cache:
            return self._cache[name]
        path = self.resolve_path(name)
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        compiled = _TemplateParser(source, name).parse()
        if self.cache_enabled:
            self._cache[name] = compiled
        return compiled

    def clear_cache(self) -> None:
        self._cache.clear()

    # -- rendering -------------------------------------------------------- #

    def render(self, name: str, context: Mapping[str, Any] | None = None) -> str:
        scope: dict[str, Any] = dict(self.globals)
        if context:
            scope.update(context)
        return self._render_template(name, scope, depth=0)

    def render_string(self, source: str, context: Mapping[str, Any] | None = None, *, name: str = "<string>") -> str:
        compiled = _TemplateParser(source, name).parse()
        scope: dict[str, Any] = dict(self.globals)
        if context:
            scope.update(context)
        buffer: list[str] = []
        self._execute(compiled.nodes, scope, buffer, {}, depth=0)
        return "".join(buffer)

    def _render_template(self, name: str, scope: dict[str, Any], *, depth: int) -> str:
        if depth > 24:
            raise TemplateRuntimeError(f"template inheritance/include depth exceeded at {name!r}")

        chain: list[_CompiledTemplate] = []
        current = self.load(name)
        chain.append(current)
        seen = {name}
        while current.parent:
            if current.parent in seen:
                raise TemplateRuntimeError(f"circular template inheritance involving {current.parent!r}")
            seen.add(current.parent)
            current = self.load(current.parent)
            chain.append(current)

        # Child blocks win; walk from the outermost ancestor inward so that the
        # nearest descendant definition is the one that survives.
        blocks: dict[str, list[Any]] = {}
        for compiled in reversed(chain):
            blocks.update(compiled.blocks)

        root = chain[-1]
        buffer: list[str] = []
        self._execute(root.nodes, scope, buffer, blocks, depth=depth)
        return "".join(buffer)

    def _execute(
        self,
        nodes: Iterable[Any],
        scope: dict[str, Any],
        buffer: list[str],
        blocks: dict[str, list[Any]],
        *,
        depth: int,
    ) -> None:
        for node in nodes:
            if isinstance(node, _Text):
                buffer.append(node.text)
                continue
            if isinstance(node, _Output):
                value = _evaluate(node.expression, scope, self.filters)
                buffer.append(_stringify(value) if node.raw else escape(value))
                continue
            if isinstance(node, _If):
                for condition, body in node.branches:
                    if _truthy(_evaluate(condition, scope, self.filters)):
                        self._execute(body, scope, buffer, blocks, depth=depth)
                        break
                else:
                    if node.otherwise is not None:
                        self._execute(node.otherwise, scope, buffer, blocks, depth=depth)
                continue
            if isinstance(node, _For):
                self._execute_for(node, scope, buffer, blocks, depth=depth)
                continue
            if isinstance(node, _Set):
                scope[node.name] = _evaluate(node.expression, scope, self.filters)
                continue
            if isinstance(node, _Include):
                if node.name is not None:
                    included = node.name
                else:
                    assert node.expression is not None
                    included = _stringify(_evaluate(node.expression, scope, self.filters))
                buffer.append(self._render_template(included, dict(scope), depth=depth + 1))
                continue
            if isinstance(node, _Block):
                body = blocks.get(node.name, node.body)
                self._execute(body, scope, buffer, blocks, depth=depth)
                continue
            raise TemplateRuntimeError(f"unknown template node {node!r}")

    def _execute_for(
        self,
        node: _For,
        scope: dict[str, Any],
        buffer: list[str],
        blocks: dict[str, list[Any]],
        *,
        depth: int,
    ) -> None:
        iterable = _evaluate(node.iterable, scope, self.filters)
        if isinstance(iterable, Mapping):
            items: list[Any] = list(iterable.items())
        elif isinstance(iterable, (list, tuple)):
            items = list(iterable)
        elif isinstance(iterable, (str, bytes)) or isinstance(iterable, _Undefined) or iterable is None:
            items = [] if not isinstance(iterable, str) else list(iterable)
        else:
            try:
                items = list(iterable)
            except TypeError:
                items = []

        if not items:
            if node.empty is not None:
                self._execute(node.empty, scope, buffer, blocks, depth=depth)
            return

        total = len(items)
        parent_loop = scope.get("loop")
        saved = {name: scope.get(name) for name in node.target}

        for index, item in enumerate(items):
            if len(node.target) == 1:
                scope[node.target[0]] = item
            else:
                values = list(item) if isinstance(item, (list, tuple)) else [item]
                for offset, name in enumerate(node.target):
                    scope[name] = values[offset] if offset < len(values) else _Undefined(name)
            scope["loop"] = {
                "index": index + 1,
                "index0": index,
                "revindex": total - index,
                "first": index == 0,
                "last": index == total - 1,
                "length": total,
                "even": index % 2 == 1,
                "odd": index % 2 == 0,
                "parent": parent_loop,
            }
            self._execute(node.body, scope, buffer, blocks, depth=depth)

        if parent_loop is None:
            scope.pop("loop", None)
        else:
            scope["loop"] = parent_loop
        for name, value in saved.items():
            if value is None:
                scope.pop(name, None)
            else:
                scope[name] = value
