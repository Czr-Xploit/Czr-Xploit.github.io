"""
Dependency-free syntax highlighter.

The approach is a single alternation regex per language, applied left to right
with the highest-priority rules first.  It is a lexer, not a parser: it will
never be as precise as a real grammar, but for code listings in an article it
is fast, predictable and, crucially, has no failure mode worse than "this token
got the wrong colour".

Every emitted token is HTML-escaped.  A language definition can never inject
markup, because the only thing this module ever writes is
``<span class="tok tok-NAME">escaped-text</span>``.

Token classes (kept short; the stylesheet maps them to colours):
    com  comment            kw   keyword           bi   builtin / type
    str  string             num  number            fn   function name
    var  variable / sigil   op   operator          pun  punctuation
    tag  markup tag         atr  attribute         cst  constant
    err  error / deletion   ok   addition          met  meta / preprocessor
    pmt  shell prompt       out  program output
"""

from __future__ import annotations

import html
import re
from typing import Iterable, Sequence

__all__ = ["highlight", "highlight_lines", "resolve_language", "LANGUAGE_ALIASES", "supported_languages"]


# --------------------------------------------------------------------------- #
# Rule tables
# --------------------------------------------------------------------------- #

Rule = tuple[str, str]  # (token class, regex source)


def _kw(words: Iterable[str]) -> str:
    """Word-boundary alternation, longest first so prefixes do not shadow."""
    ordered = sorted({word for word in words}, key=len, reverse=True)
    return r"\b(?:" + "|".join(re.escape(word) for word in ordered) + r")\b"


_COMMON_NUMBER = r"\b(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?)(?:[uUlLfFdD]|[iu](?:8|16|32|64|128|size))?\b"


PYTHON_KEYWORDS = """
False None True and as assert async await break class continue def del elif else except
finally for from global if import in is lambda nonlocal not or pass raise return try while
with yield match case type
""".split()

PYTHON_BUILTINS = """
abs aiter all any anext ascii bin bool breakpoint bytearray bytes callable chr classmethod
compile complex delattr dict dir divmod enumerate eval exec filter float format frozenset
getattr globals hasattr hash help hex id input int isinstance issubclass iter len list locals
map max memoryview min next object oct open ord pow print property range repr reversed round
set setattr slice sorted staticmethod str sum super tuple type vars zip self cls
Exception ValueError TypeError KeyError IndexError RuntimeError OSError IOError NameError
AttributeError ImportError StopIteration NotImplementedError ZeroDivisionError
""".split()

C_KEYWORDS = """
auto break case char const continue default do double else enum extern float for goto if
inline int long register restrict return short signed sizeof static struct switch typedef
union unsigned void volatile while _Bool _Complex _Atomic _Static_assert _Thread_local
alignas alignof asm bool true false nullptr
""".split()

CPP_EXTRA = """
class namespace template typename public private protected virtual override final new delete
this operator friend explicit constexpr consteval constinit noexcept using try catch throw
decltype mutable static_cast dynamic_cast const_cast reinterpret_cast co_await co_return
co_yield concept requires import module export
""".split()

C_TYPES = """
size_t ssize_t ptrdiff_t intptr_t uintptr_t int8_t int16_t int32_t int64_t uint8_t uint16_t
uint32_t uint64_t FILE va_list wchar_t char8_t char16_t char32_t std string vector map set
unordered_map shared_ptr unique_ptr weak_ptr
""".split()

JS_KEYWORDS = """
async await break case catch class const continue debugger default delete do else enum export
extends false finally for function if implements import in instanceof interface let new null
of package private protected public return static super switch this throw true try typeof var
void while with yield as from get set satisfies
""".split()

TS_EXTRA = """
abstract any asserts bigint boolean declare infer is keyof namespace never number object
override readonly string symbol type undefined unique unknown module global
""".split()

JS_BUILTINS = """
Array Boolean Date Error EvalError Function Infinity JSON Math NaN Number Object Promise Proxy
RangeError ReferenceError Reflect RegExp Set String Symbol SyntaxError TypeError URIError
WeakMap WeakSet Map Intl BigInt globalThis console document window navigator location fetch
localStorage sessionStorage history performance crypto URL URLSearchParams TextEncoder
TextDecoder AbortController IntersectionObserver ResizeObserver MutationObserver
requestAnimationFrame cancelAnimationFrame setTimeout setInterval clearTimeout clearInterval
structuredClone queueMicrotask
""".split()

RUST_KEYWORDS = """
as async await break const continue crate dyn else enum extern false fn for if impl in let
loop match mod move mut pub ref return self Self static struct super trait true type unsafe
use where while abstract become box do final macro override priv typeof unsized virtual yield
try union
""".split()

RUST_TYPES = """
i8 i16 i32 i64 i128 isize u8 u16 u32 u64 u128 usize f32 f64 bool char str String Vec Option
Result Box Rc Arc RefCell Cell Mutex RwLock HashMap HashSet BTreeMap Some None Ok Err
""".split()

GO_KEYWORDS = """
break case chan const continue default defer else fallthrough for func go goto if import
interface map package range return select struct switch type var
""".split()

GO_TYPES = """
bool byte complex64 complex128 error float32 float64 int int8 int16 int32 int64 rune string
uint uint8 uint16 uint32 uint64 uintptr any nil true false iota make new len cap append copy
delete panic recover print println close
""".split()

JAVA_KEYWORDS = """
abstract assert boolean break byte case catch char class const continue default do double
else enum extends final finally float for goto if implements import instanceof int interface
long native new package private protected public return short static strictfp super switch
synchronized this throw throws transient try void volatile while var record sealed permits
yield true false null
""".split()

PHP_KEYWORDS = """
abstract and array as break callable case catch class clone const continue declare default do
echo else elseif empty enddeclare endfor endforeach endif endswitch endwhile enum extends
final finally fn for foreach function global goto if implements include include_once
instanceof insteadof interface isset list match namespace new or print private protected
public readonly require require_once return static switch throw trait try unset use var while
xor yield true false null
""".split()

RUBY_KEYWORDS = """
BEGIN END alias and begin break case class def defined? do else elsif end ensure false for if
in module next nil not or redo rescue retry return self super then true undef unless until
when while yield attr_accessor attr_reader attr_writer require require_relative puts print
lambda proc raise
""".split()

SQL_KEYWORDS = """
ADD ALL ALTER AND ANY AS ASC BEGIN BETWEEN BY CASE CAST CHECK COLUMN COMMIT CONSTRAINT CREATE
CROSS DATABASE DECLARE DEFAULT DELETE DESC DISTINCT DROP ELSE END EXCEPT EXEC EXISTS FETCH
FOREIGN FROM FULL GRANT GROUP HAVING IF IN INDEX INNER INSERT INTERSECT INTO IS JOIN KEY LEFT
LIKE LIMIT NOT NULL OFFSET ON OR ORDER OUTER PRIMARY PROCEDURE REFERENCES REPLACE RETURNING
REVOKE RIGHT ROLLBACK SELECT SET TABLE THEN TOP TRANSACTION TRUNCATE UNION UNIQUE UPDATE USING
VALUES VIEW WHEN WHERE WITH
""".split()

SQL_FUNCTIONS = """
AVG COUNT MAX MIN SUM COALESCE NULLIF CONCAT SUBSTRING LENGTH LOWER UPPER TRIM NOW CURRENT_DATE
CURRENT_TIMESTAMP ROW_NUMBER RANK DENSE_RANK GROUP_CONCAT JSON_EXTRACT
""".split()

SHELL_KEYWORDS = """
if then else elif fi for while until do done case esac function select in return break
continue local export readonly declare typeset unset shift eval exec trap set source alias
time coproc
""".split()

SHELL_BUILTINS = """
echo printf read cd pwd pushd popd dirs test cat ls grep egrep fgrep sed awk cut sort uniq
head tail tr wc find xargs curl wget chmod chown mkdir rmdir rm cp mv ln touch tar gzip gunzip
zip unzip ssh scp rsync git python python3 pip pip3 sudo su apt apt-get dpkg systemctl service
ps kill killall top htop df du mount umount ip ifconfig netstat ss ping traceroute dig host
nslookup openssl base64 md5sum sha1sum sha256sum jq env which whereis man history exit env
docker kubectl make gcc g++ node npm npx go cargo rustc java javac
""".split()

POWERSHELL_KEYWORDS = """
begin break catch class continue data define do dynamicparam else elseif end enum exit filter
finally for foreach from function hidden if in inlinescript parallel param process return
static switch throw trap try until using var while workflow
""".split()

YAML_CONSTANTS = ["true", "false", "null", "yes", "no", "on", "off", "~", "True", "False", "Null"]

CSS_ATRULES = """
media supports keyframes font-face import charset namespace page layer container property
scope starting-style counter-style font-feature-values
""".split()

LUA_KEYWORDS = """
and break do else elseif end false for function goto if in local nil not or repeat return
then true until while self
""".split()

ASM_KEYWORDS = """
mov movzx movsx lea push pop add sub mul imul div idiv inc dec and or xor not neg shl shr sal
sar rol ror cmp test jmp je jne jz jnz jg jge jl jle ja jae jb jbe call ret leave enter nop
int syscall sysenter iret hlt cld std cli sti loop rep repe repne movs stos lods scas cmps
xchg cmpxchg cdq cqo setz setnz sete setne pushad popad pushfd popfd endbr64 endbr32
""".split()

ASM_REGISTERS = """
rax rbx rcx rdx rsi rdi rbp rsp r8 r9 r10 r11 r12 r13 r14 r15 eax ebx ecx edx esi edi ebp esp
r8d r9d r10d r11d r12d r13d r14d r15d ax bx cx dx si di bp sp al bl cl dl ah bh ch dh
r8b r9b r10b r11b r12b r13b r14b r15b rip eip cs ds es fs gs ss xmm0 xmm1 xmm2 xmm3 ymm0 ymm1
""".split()

HTTP_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE", "CONNECT", "PROPFIND", "MKCOL"]


def _string_rules(*, triple: bool = False, backtick: bool = False, single: bool = True) -> list[Rule]:
    rules: list[Rule] = []
    if triple:
        rules.append(("str", r'"""(?:[^\\]|\\.)*?"""|\'\'\'(?:[^\\]|\\.)*?\'\'\''))
    rules.append(("str", r'"(?:[^"\\\n]|\\.)*"'))
    if single:
        rules.append(("str", r"'(?:[^'\\\n]|\\.)*'"))
    if backtick:
        rules.append(("str", r"`(?:[^`\\]|\\.)*`"))
    return rules


LANGUAGES: dict[str, list[Rule]] = {
    "python": [
        ("com", r"#[^\n]*"),
        ("str", r'(?:[rRbBuUfF]{0,3})(?:"""(?:[^\\]|\\.)*?"""|\'\'\'(?:[^\\]|\\.)*?\'\'\')'),
        ("str", r'(?:[rRbBuUfF]{0,3})(?:"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\')'),
        ("met", r"^\s*@[\w.]+"),
        ("num", _COMMON_NUMBER),
        ("kw", _kw(PYTHON_KEYWORDS)),
        ("bi", _kw(PYTHON_BUILTINS)),
        ("fn", r"\b[A-Za-z_]\w*(?=\s*\()"),
        ("cst", r"\b[A-Z][A-Z0-9_]{2,}\b"),
        ("op", r"[-+*/%=<>!&|^~@]+|:="),
        ("pun", r"[\[\]{}(),;:.]"),
    ],
    "javascript": [
        ("com", r"//[^\n]*|/\*[\s\S]*?\*/"),
        *_string_rules(backtick=True),
        ("str", r"/(?![*/])(?:[^/\\\n\[]|\\.|\[(?:[^\]\\]|\\.)*\])+/[dgimsuvy]*(?=\s*[;,)\].}\n]|$)"),
        ("num", _COMMON_NUMBER + r"|\b\d+n\b"),
        ("kw", _kw(JS_KEYWORDS)),
        ("bi", _kw(JS_BUILTINS)),
        ("fn", r"\b[A-Za-z_$][\w$]*(?=\s*\()"),
        ("cst", r"\b[A-Z][A-Z0-9_]{2,}\b"),
        ("op", r"=>|\?\?=?|\?\.|\.{3}|[-+*/%=<>!&|^~?:]+"),
        ("pun", r"[\[\]{}(),;:.]"),
    ],
    "typescript": [
        ("com", r"//[^\n]*|/\*[\s\S]*?\*/"),
        *_string_rules(backtick=True),
        ("num", _COMMON_NUMBER + r"|\b\d+n\b"),
        ("kw", _kw(JS_KEYWORDS + TS_EXTRA)),
        ("bi", _kw(JS_BUILTINS)),
        ("fn", r"\b[A-Za-z_$][\w$]*(?=\s*[<(])"),
        ("cst", r"\b[A-Z][A-Z0-9_]{2,}\b"),
        ("op", r"=>|\?\?=?|\?\.|\.{3}|[-+*/%=<>!&|^~?:]+"),
        ("pun", r"[\[\]{}(),;:.]"),
    ],
    "c": [
        ("com", r"//[^\n]*|/\*[\s\S]*?\*/"),
        ("met", r"^[ \t]*#\s*\w+(?:[^\n\\]|\\\n)*"),
        *_string_rules(),
        ("num", _COMMON_NUMBER),
        ("kw", _kw(C_KEYWORDS)),
        ("bi", _kw(C_TYPES)),
        ("fn", r"\b[A-Za-z_]\w*(?=\s*\()"),
        ("cst", r"\b[A-Z][A-Z0-9_]{2,}\b"),
        ("op", r"->|\+\+|--|<<=?|>>=?|[-+*/%=<>!&|^~?:]+"),
        ("pun", r"[\[\]{}(),;:.]"),
    ],
    "cpp": [
        ("com", r"//[^\n]*|/\*[\s\S]*?\*/"),
        ("met", r"^[ \t]*#\s*\w+(?:[^\n\\]|\\\n)*"),
        *_string_rules(),
        ("num", _COMMON_NUMBER),
        ("kw", _kw(C_KEYWORDS + CPP_EXTRA)),
        ("bi", _kw(C_TYPES)),
        ("fn", r"\b[A-Za-z_]\w*(?=\s*[<(])"),
        ("cst", r"\b[A-Z][A-Z0-9_]{2,}\b"),
        ("op", r"::|->\*?|\+\+|--|<<=?|>>=?|[-+*/%=<>!&|^~?:]+"),
        ("pun", r"[\[\]{}(),;:.]"),
    ],
    "rust": [
        ("com", r"//[^\n]*|/\*[\s\S]*?\*/"),
        ("met", r"#!?\[[^\]]*\]"),
        ("str", r'r#*"[\s\S]*?"#*|b?"(?:[^"\\\n]|\\.)*"'),
        ("str", r"b?'(?:[^'\\\n]|\\.)'"),
        ("num", _COMMON_NUMBER),
        ("kw", _kw(RUST_KEYWORDS)),
        ("bi", _kw(RUST_TYPES)),
        ("fn", r"\b[a-z_]\w*(?=\s*[<(!])|\b\w+!"),
        ("var", r"'\w+\b"),
        ("cst", r"\b[A-Z][A-Z0-9_]{2,}\b"),
        ("op", r"::|->|=>|\.\.=?|[-+*/%=<>!&|^~?:]+"),
        ("pun", r"[\[\]{}(),;:.#]"),
    ],
    "go": [
        ("com", r"//[^\n]*|/\*[\s\S]*?\*/"),
        *_string_rules(backtick=True),
        ("num", _COMMON_NUMBER),
        ("kw", _kw(GO_KEYWORDS)),
        ("bi", _kw(GO_TYPES)),
        ("fn", r"\b[A-Za-z_]\w*(?=\s*\()"),
        ("op", r":=|<-|\.{3}|[-+*/%=<>!&|^~]+"),
        ("pun", r"[\[\]{}(),;:.]"),
    ],
    "java": [
        ("com", r"//[^\n]*|/\*[\s\S]*?\*/"),
        ("met", r"@\w+"),
        *_string_rules(),
        ("num", _COMMON_NUMBER),
        ("kw", _kw(JAVA_KEYWORDS)),
        ("bi", r"\b(?:String|Integer|Long|Double|Float|Boolean|Character|Byte|Short|Object|List|Map|Set|ArrayList|HashMap|HashSet|Optional|Stream|System|Math|Thread|Exception|RuntimeException)\b"),
        ("fn", r"\b[a-z]\w*(?=\s*\()"),
        ("cst", r"\b[A-Z][A-Z0-9_]{2,}\b"),
        ("op", r"->|::|\+\+|--|[-+*/%=<>!&|^~?:]+"),
        ("pun", r"[\[\]{}(),;:.]"),
    ],
    "php": [
        ("com", r"//[^\n]*|#[^\n]*|/\*[\s\S]*?\*/"),
        ("met", r"<\?php|<\?=|\?>"),
        *_string_rules(),
        ("var", r"\$\w+"),
        ("num", _COMMON_NUMBER),
        ("kw", _kw(PHP_KEYWORDS)),
        ("fn", r"\b[A-Za-z_]\w*(?=\s*\()"),
        ("op", r"=>|->|::|\?\?|[-+*/%=<>!&|^~.?:]+"),
        ("pun", r"[\[\]{}(),;:]"),
    ],
    "ruby": [
        ("com", r"#[^\n]*|^=begin[\s\S]*?^=end"),
        *_string_rules(),
        ("var", r"[@$]{1,2}\w+"),
        ("cst", r":\w+|\b[A-Z]\w*\b"),
        ("num", _COMMON_NUMBER),
        ("kw", _kw(RUBY_KEYWORDS)),
        ("fn", r"\b[a-z_]\w*[?!]?(?=\s*\()"),
        ("op", r"=>|<=>|\|\||&&|[-+*/%=<>!&|^~?:]+"),
        ("pun", r"[\[\]{}(),;:.]"),
    ],
    "sql": [
        ("com", r"--[^\n]*|/\*[\s\S]*?\*/"),
        ("str", r"'(?:[^'\\]|''|\\.)*'"),
        ("str", r'"(?:[^"\\]|""|\\.)*"'),
        ("var", r"`[^`]*`|\[[^\]]*\]"),
        ("num", _COMMON_NUMBER),
        ("kw", r"(?i)" + _kw(SQL_KEYWORDS)),
        ("bi", r"(?i)" + _kw(SQL_FUNCTIONS)),
        ("op", r"[-+*/%=<>!]+|\|\|"),
        ("pun", r"[(),;.]"),
    ],
    "shell": [
        ("com", r"(?<![\\$])#[^\n]*"),
        ("str", r'"(?:[^"\\]|\\.)*"'),
        ("str", r"'[^']*'"),
        ("var", r"\$\{[^}]*\}|\$[\w@*#?$!-]+|\$\((?:[^()]|\([^()]*\))*\)"),
        ("op", r"\|\||&&|>>|<<|[|&;<>]|\b2>&1\b"),
        ("num", r"\b\d+\b"),
        ("met", r"(?<![\w-])--?[A-Za-z][\w-]*"),
        ("kw", _kw(SHELL_KEYWORDS)),
        ("bi", _kw(SHELL_BUILTINS)),
        ("fn", r"^\s*\w+(?=\s*\(\s*\)\s*\{)"),
        ("pun", r"[\[\]{}(),=]"),
    ],
    "powershell": [
        ("com", r"#[^\n]*|<#[\s\S]*?#>"),
        *_string_rules(),
        ("var", r"\$[\w:]+"),
        ("met", r"(?<![\w-])-[A-Za-z]\w*"),
        ("num", _COMMON_NUMBER),
        ("kw", r"(?i)" + _kw(POWERSHELL_KEYWORDS)),
        ("bi", r"(?i)\b(?:Get|Set|New|Remove|Add|Invoke|Start|Stop|Test|Out|Write|Read|Select|Where|ForEach|Import|Export|Convert|ConvertTo|ConvertFrom|Copy|Move|Rename|Enable|Disable)-\w+\b"),
        ("op", r"-(?:eq|ne|gt|ge|lt|le|like|notlike|match|notmatch|contains|in|not|and|or|band|bor|join|split|replace|f)\b|[-+*/%=<>!|&]+"),
        ("pun", r"[\[\]{}(),;:.@]"),
    ],
    "yaml": [
        ("com", r"#[^\n]*"),
        ("met", r"^---$|^\.\.\.$"),
        ("atr", r"^[ \t]*-?[ \t]*[\w.\-/]+(?=\s*:)"),
        *_string_rules(),
        ("cst", _kw(YAML_CONSTANTS)),
        ("num", _COMMON_NUMBER),
        ("var", r"[&*]\w+|<<:"),
        ("op", r"[|>]-?$|[:?-]"),
    ],
    "json": [
        ("atr", r'"(?:[^"\\]|\\.)*"(?=\s*:)'),
        ("str", r'"(?:[^"\\]|\\.)*"'),
        ("cst", r"\b(?:true|false|null)\b"),
        ("num", r"-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b"),
        ("pun", r"[\[\]{},:]"),
    ],
    "toml": [
        ("com", r"#[^\n]*"),
        ("met", r"^\s*\[\[?[^\]]+\]\]?"),
        ("atr", r"^\s*[\w.\-\"']+(?=\s*=)"),
        *_string_rules(triple=True),
        ("cst", r"\b(?:true|false)\b"),
        ("num", _COMMON_NUMBER + r"|\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+Z?)?"),
        ("op", r"="),
        ("pun", r"[\[\]{},.]"),
    ],
    "ini": [
        ("com", r"[;#][^\n]*"),
        ("met", r"^\s*\[[^\]]+\]"),
        ("atr", r"^\s*[\w.\- ]+(?=\s*=)"),
        ("str", r'"(?:[^"\\]|\\.)*"'),
        ("num", _COMMON_NUMBER),
        ("op", r"="),
    ],
    "css": [
        ("com", r"/\*[\s\S]*?\*/"),
        ("met", r"@(?:" + "|".join(CSS_ATRULES) + r")\b"),
        *_string_rules(),
        ("var", r"--[\w-]+"),
        ("fn", r"\b[a-zA-Z-]+(?=\()"),
        ("num", r"#[0-9a-fA-F]{3,8}\b|-?\b\d*\.?\d+(?:px|rem|em|ex|ch|vw|vh|vmin|vmax|%|s|ms|deg|rad|turn|fr|dpi|q|pt|pc|cm|mm|in)?\b"),
        ("atr", r"(?<=[;{\s])[a-zA-Z-]+(?=\s*:)"),
        ("tag", r"(?<![\w-])(?:[.#][\w-]+|::?[a-zA-Z-]+(?:\([^)]*\))?|\*|\b(?:html|body|div|span|a|p|ul|ol|li|h[1-6]|header|footer|nav|main|section|article|aside|button|input|table|tr|td|th|img|svg|pre|code|figure)\b)"),
        ("op", r"[>+~,]"),
        ("pun", r"[{}();:]"),
    ],
    "html": [
        ("com", r"<!--[\s\S]*?-->"),
        ("met", r"<!DOCTYPE[^>]*>"),
        ("tag", r"</?[a-zA-Z][\w:-]*"),
        ("atr", r"\b[a-zA-Z_:@#][\w:.\-]*(?=\s*=)"),
        ("str", r'"(?:[^"]*)"|\'(?:[^\']*)\''),
        ("var", r"&[a-zA-Z]+;|&#\d+;"),
        ("pun", r"/?>|="),
    ],
    "xml": [
        ("com", r"<!--[\s\S]*?-->"),
        ("met", r"<\?[\s\S]*?\?>|<!DOCTYPE[^>]*>|<!\[CDATA\[[\s\S]*?\]\]>"),
        ("tag", r"</?[a-zA-Z][\w:.\-]*"),
        ("atr", r"\b[a-zA-Z_:][\w:.\-]*(?=\s*=)"),
        ("str", r'"(?:[^"]*)"|\'(?:[^\']*)\''),
        ("pun", r"/?>|="),
    ],
    "http": [
        ("kw", r"^(?:" + "|".join(HTTP_METHODS) + r")\b"),
        ("met", r"^HTTP/[\d.]+"),
        ("num", r"(?<=HTTP/[\d.] )\d{3}\b|^\s*\d{3}\b"),
        ("atr", r"^[A-Za-z][A-Za-z0-9-]*(?=:)"),
        ("str", r'"(?:[^"\\]|\\.)*"'),
        ("var", r"\b[A-Za-z0-9_-]+=(?:[^;&\s]*)"),
        ("op", r"[?&=;]"),
    ],
    "diff": [],       # handled line-wise
    "console": [],    # handled line-wise
    "lua": [
        ("com", r"--\[\[[\s\S]*?\]\]|--[^\n]*"),
        ("str", r"\[\[[\s\S]*?\]\]"),
        *_string_rules(),
        ("num", _COMMON_NUMBER),
        ("kw", _kw(LUA_KEYWORDS)),
        ("bi", r"\b(?:print|pairs|ipairs|type|tostring|tonumber|table|string|math|io|os|require|pcall|xpcall|setmetatable|getmetatable|rawget|rawset|select|unpack)\b"),
        ("fn", r"\b[A-Za-z_]\w*(?=\s*\()"),
        ("op", r"\.\.\.?|==|~=|<=|>=|[-+*/%^#=<>]"),
        ("pun", r"[\[\]{}(),;:.]"),
    ],
    "asm": [
        ("com", r"[;#][^\n]*"),
        ("str", r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\''),
        ("met", r"^\s*\.\w+|^\s*[\w.$]+:"),
        ("num", r"\b(?:0[xX][0-9a-fA-F]+|\d+)\b"),
        ("kw", r"(?i)" + _kw(ASM_KEYWORDS)),
        ("var", r"(?i)\b(?:" + "|".join(ASM_REGISTERS) + r")\b"),
        ("bi", r"(?i)\b(?:byte|word|dword|qword|ptr|offset|short|near|far)\b"),
        ("op", r"[-+*/]"),
        ("pun", r"[\[\](),:]"),
    ],
    "dockerfile": [
        ("com", r"#[^\n]*"),
        ("kw", r"(?im)^\s*(?:FROM|RUN|CMD|LABEL|MAINTAINER|EXPOSE|ENV|ADD|COPY|ENTRYPOINT|VOLUME|USER|WORKDIR|ARG|ONBUILD|STOPSIGNAL|HEALTHCHECK|SHELL)\b"),
        ("str", r'"(?:[^"\\]|\\.)*"|\'[^\']*\''),
        ("var", r"\$\{[^}]*\}|\$\w+"),
        ("met", r"(?<![\w-])--[A-Za-z][\w-]*"),
        ("num", r"\b\d+\b"),
        ("pun", r"[\[\](),=]"),
    ],
    "makefile": [
        ("com", r"#[^\n]*"),
        ("fn", r"^[\w.%$()/ -]+(?=:(?!=))"),
        ("var", r"\$[({][^)}]*[)}]|\$\w"),
        ("kw", r"(?m)^\s*(?:ifeq|ifneq|ifdef|ifndef|else|endif|include|-include|define|endef|export|unexport|override|vpath|\.PHONY|\.DEFAULT)\b"),
        ("str", r'"(?:[^"\\]|\\.)*"|\'[^\']*\''),
        ("op", r":?=|\+=|\?="),
    ],
    "text": [],
}


LANGUAGE_ALIASES: dict[str, str] = {
    "py": "python", "python3": "python", "py3": "python",
    "js": "javascript", "mjs": "javascript", "cjs": "javascript", "node": "javascript", "jsx": "javascript",
    "ts": "typescript", "tsx": "typescript",
    "c++": "cpp", "cc": "cpp", "cxx": "cpp", "hpp": "cpp", "h": "c",
    "rs": "rust",
    "golang": "go",
    "sh": "shell", "bash": "shell", "zsh": "shell", "fish": "shell", "ksh": "shell", "console": "console",
    "shell-session": "console", "terminal": "console", "session": "console", "cmd": "console",
    "ps1": "powershell", "pwsh": "powershell",
    "yml": "yaml",
    "jsonc": "json", "json5": "json",
    "htm": "html", "vue": "html", "svelte": "html",
    "scss": "css", "sass": "css", "less": "css",
    "postgres": "sql", "postgresql": "sql", "mysql": "sql", "sqlite": "sql", "plsql": "sql", "tsql": "sql",
    "rb": "ruby",
    "patch": "diff",
    "nasm": "asm", "x86": "asm", "x86asm": "asm", "gas": "asm", "armasm": "asm", "assembly": "asm",
    "docker": "dockerfile",
    "make": "makefile", "mk": "makefile",
    "conf": "ini", "cfg": "ini", "properties": "ini", "editorconfig": "ini",
    "plaintext": "text", "txt": "text", "": "text", "none": "text", "output": "text", "log": "text",
    "req": "http", "request": "http", "response": "http", "raw": "http",
}


_compiled: dict[str, re.Pattern[str]] = {}


def supported_languages() -> list[str]:
    """Every canonical language name this module can highlight."""
    return sorted(LANGUAGES)


def resolve_language(name: str | None) -> str:
    """Map a fence info string to a canonical language name."""
    if not name:
        return "text"
    key = name.strip().lower().split()[0] if name.strip() else "text"
    key = LANGUAGE_ALIASES.get(key, key)
    return key if key in LANGUAGES else "text"


def _pattern_for(language: str) -> re.Pattern[str] | None:
    if language in _compiled:
        return _compiled[language]
    rules = LANGUAGES.get(language) or []
    if not rules:
        _compiled[language] = None  # type: ignore[assignment]
        return None
    parts: list[str] = []
    for index, (token_class, source) in enumerate(rules):
        # A rule may ask for case-insensitivity with a leading `(?i)`. That is a
        # *global* flag, and Python refuses it anywhere but the very start of a
        # pattern -- which it never is once the rules are joined into one
        # alternation. Rewrite it as a scoped group so the flag applies to that
        # branch alone, which is what the rule meant in the first place.
        flags = re.match(r"^\(\?([aimsux]+)\)", source)
        if flags:
            source = f"(?{flags.group(1)}:{source[flags.end():]})"
        parts.append(f"(?P<g{index}_{token_class}>{source})")
    pattern = re.compile("|".join(parts), re.MULTILINE)
    _compiled[language] = pattern
    return pattern


def _span(token_class: str, text: str) -> str:
    return f'<span class="tok tok-{token_class}">{html.escape(text, quote=False)}</span>'


# --------------------------------------------------------------------------- #
# Line-oriented languages
# --------------------------------------------------------------------------- #

_PROMPT_RE = re.compile(
    r"^(?P<prompt>"
    r"(?:\(\w[\w.\- ]*\)\s*)?"                     # (venv) prefix
    r"(?:[\w.\-]+@[\w.\-]+)?"                      # user@host
    r"(?:[:\s][~/][^\s#$]*)?"                      # cwd
    r"\s*(?:[#$»❯➜λ>]|PS [A-Za-z]:[^>]*>)\s)"
    r"(?P<command>.*)$"
)


def _highlight_console(code: str) -> str:
    """Shell session: prompt + command highlighted, output left plain."""
    out: list[str] = []
    shell_pattern = _pattern_for("shell")
    for line in code.split("\n"):
        match = _PROMPT_RE.match(line)
        if match:
            prompt = _span("pmt", match.group("prompt"))
            command = _highlight_with(shell_pattern, match.group("command"))
            out.append(prompt + command)
        else:
            out.append(_span("out", line) if line.strip() else line)
    return "\n".join(out)


def _highlight_diff(code: str) -> str:
    out: list[str] = []
    for line in code.split("\n"):
        if line.startswith(("+++", "---")):
            out.append(_span("met", line))
        elif line.startswith("@@"):
            out.append(_span("fn", line))
        elif line.startswith("+"):
            out.append(_span("ok", line))
        elif line.startswith("-"):
            out.append(_span("err", line))
        elif line.startswith(("diff ", "index ", "similarity ", "rename ", "new file", "deleted file", "old mode", "new mode")):
            out.append(_span("com", line))
        else:
            out.append(html.escape(line, quote=False))
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Core
# --------------------------------------------------------------------------- #

def _highlight_with(pattern: re.Pattern[str] | None, code: str) -> str:
    if pattern is None:
        return html.escape(code, quote=False)
    out: list[str] = []
    position = 0
    for match in pattern.finditer(code):
        start, end = match.span()
        if start > position:
            out.append(html.escape(code[position:start], quote=False))
        group_name = match.lastgroup or ""
        token_class = group_name.split("_", 1)[1] if "_" in group_name else "txt"
        out.append(_span(token_class, match.group()))
        position = end
    if position < len(code):
        out.append(html.escape(code[position:], quote=False))
    return "".join(out)


def highlight(code: str, language: str | None = None) -> str:
    """Return ``code`` as HTML with token spans. Always escapes."""
    canonical = resolve_language(language)
    if canonical == "console":
        return _highlight_console(code)
    if canonical == "diff":
        return _highlight_diff(code)
    return _highlight_with(_pattern_for(canonical), code)


def highlight_lines(
    code: str,
    language: str | None = None,
    *,
    emphasise: Sequence[int] = (),
    start_number: int = 1,
    show_numbers: bool = False,
) -> str:
    """Highlight and wrap each source line in its own element.

    Per-line wrapping is what makes line numbers, line emphasis and
    "copy without the numbers" all work at the same time: the number lives in a
    ``::before`` pseudo-element driven by a CSS counter, so it is never part of
    the text the browser copies.
    """
    rendered = highlight(code, language)
    highlighted = set(emphasise)
    lines = rendered.split("\n")
    out: list[str] = []
    for offset, line in enumerate(lines):
        number = start_number + offset
        classes = ["ln"]
        if number in highlighted:
            classes.append("ln-hl")
        out.append(f'<span class="{" ".join(classes)}">{line or "&#8203;"}</span>')
    body = "\n".join(out)
    wrapper_class = "code-lines" + (" with-numbers" if show_numbers else "")
    return f'<span class="{wrapper_class}">{body}</span>'
