#!/usr/bin/env python3
"""
CzrXplo1t static site generator -- entry point.

    python3 build.py                 build into dist/
    python3 build.py --drafts        include draft: true documents
    python3 build.py --serve         build, then serve dist/ with live rebuild
    python3 build.py --check         build, then run the full verification pass
    python3 build.py --no-minify     keep CSS readable for debugging
    python3 build.py --clean         remove dist/ and exit

Requires nothing but a Python 3.11+ standard library.  If this script ever
needs a `pip install`, something has gone wrong and should be reverted.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

MINIMUM_PYTHON = (3, 11)


class Colour:
    """ANSI helpers that disable themselves when the output is not a terminal."""

    enabled = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

    @classmethod
    def _wrap(cls, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if cls.enabled else text

    @classmethod
    def green(cls, text: str) -> str:
        return cls._wrap("38;5;46", text)

    @classmethod
    def red(cls, text: str) -> str:
        return cls._wrap("38;5;196", text)

    @classmethod
    def yellow(cls, text: str) -> str:
        return cls._wrap("38;5;220", text)

    @classmethod
    def dim(cls, text: str) -> str:
        return cls._wrap("2", text)

    @classmethod
    def bold(cls, text: str) -> str:
        return cls._wrap("1", text)


BANNER = r"""
   ___          __  __      _       _ _
  / __|_______ _\ \/ /_ __ | | ___ / / |_
 | (__|_ /  _| |>  <| '_ \| |/ _ \_  _|
  \___/__|_|  |_/_/\_\ .__/|_|\___/ |_|
                     |_|      static site generator
"""


def _check_python() -> None:
    if sys.version_info < MINIMUM_PYTHON:
        have = ".".join(str(part) for part in sys.version_info[:3])
        want = ".".join(str(part) for part in MINIMUM_PYTHON)
        print(Colour.red(f"error: Python {want}+ required, running {have}"), file=sys.stderr)
        raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    _check_python()

    parser = argparse.ArgumentParser(
        prog="build.py",
        description="Build the CzrXplo1t site. Zero third-party dependencies.",
    )
    parser.add_argument("--config", default=os.path.join(REPO_ROOT, "site.json"), help="path to site.json")
    parser.add_argument("--drafts", action="store_true", help="include documents marked draft: true")
    parser.add_argument("--no-minify", action="store_true", help="skip CSS minification")
    parser.add_argument("--base-url", default=None, help="override base_url (useful for previews)")
    parser.add_argument("--check", action="store_true", help="run verification after building")
    parser.add_argument("--strict", action="store_true", help="treat warnings and budget overruns as failures")
    parser.add_argument("--serve", action="store_true", help="serve dist/ after building")
    parser.add_argument("--port", type=int, default=8000, help="port for --serve (default 8000)")
    parser.add_argument("--host", default="127.0.0.1", help="bind address for --serve")
    parser.add_argument("--clean", action="store_true", help="delete the output directory and exit")
    parser.add_argument("--quiet", action="store_true", help="only print errors")
    args = parser.parse_args(argv)

    from tools.ssg.builder import Builder
    from tools.ssg.config import ConfigError, load_config

    try:
        config = load_config(args.config)
    except ConfigError as error:
        print(Colour.red(f"config error: {error}"), file=sys.stderr)
        return 2

    if args.clean:
        import shutil

        if os.path.isdir(config.output_path):
            shutil.rmtree(config.output_path)
            print(f"removed {config.output_path}")
        else:
            print(f"nothing to remove at {config.output_path}")
        return 0

    if not args.quiet:
        print(Colour.green(BANNER))

    builder = Builder(
        config,
        include_drafts=args.drafts,
        minify=not args.no_minify,
        base_url_override=args.base_url,
    )

    try:
        result = builder.build()
    except Exception as error:  # noqa: BLE001 - the CLI is the top of the stack
        print(Colour.red(f"\nbuild failed: {error}\n"), file=sys.stderr)
        if os.environ.get("SSG_TRACEBACK"):
            traceback.print_exc()
        else:
            print(Colour.dim("  set SSG_TRACEBACK=1 for the full traceback"), file=sys.stderr)
        return 1

    if not args.quiet:
        builder.report()

    exit_code = 0

    if result.budget_problems:
        for problem in result.budget_problems:
            print(Colour.yellow(f"  budget: {problem}"))
        if args.strict:
            exit_code = 1

    if args.check:
        from tools.ssg.check import run_checks

        findings = run_checks(config, builder)
        blockers = [finding for finding in findings if finding.severity == "BLOCKER"]
        for finding in findings:
            colour = Colour.red if finding.severity in ("BLOCKER", "HIGH") else Colour.yellow
            print(colour(f"  [{finding.severity}] {finding.check}: {finding.message}"))
            if finding.location:
                print(Colour.dim(f"           {finding.location}"))
        if not findings:
            print(Colour.green("  verificación: sin hallazgos"))
        print("")
        if blockers or (findings and args.strict):
            exit_code = 1

    if exit_code == 0 and not args.quiet:
        print(Colour.green(f"  OK  {config.output_path}"))
        print("")

    if args.serve:
        from tools.ssg.serve import serve

        serve(config, host=args.host, port=args.port, rebuild=lambda: _rebuild(config, args))

    return exit_code


def _rebuild(config, args) -> str | None:
    """Rebuild callback used by the dev server. Returns an error string or None."""
    from tools.ssg.builder import Builder

    try:
        builder = Builder(
            config,
            include_drafts=args.drafts,
            minify=not args.no_minify,
            base_url_override=args.base_url,
        )
        builder.build()
        return None
    except Exception as error:  # noqa: BLE001
        return f"{type(error).__name__}: {error}"


if __name__ == "__main__":
    raise SystemExit(main())
