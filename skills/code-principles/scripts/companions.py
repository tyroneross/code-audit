#!/usr/bin/env python3
"""Show which measurement and lint companions are available, per language, and how to use them.

`doctor` checks only whether each tool is on PATH (or, for cargo subcommands,
whether the cargo-<name> binary exists). A tool that must be a project
dependency (StrykerJS) is available only when its package resolves from
node_modules at or above --project; npx alone would download it, so it does not
count. It never runs project code, tests, installers or network fetches. Coverage and mutation runs execute the project's tests; run them
only with authorization, on a passing baseline, and keep outputs outside the
reviewed repository. Converters: coverage_convert.py and mutation_report.py.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import complexity  # noqa: E402

COMPANIONS = {
    "rust": {
        "coverage": {"tool": "cargo-llvm-cov", "check": ["cargo-llvm-cov"], "requires": "rustup component add llvm-tools-preview",
                     "install": "cargo install --locked cargo-llvm-cov",
                     "run": "cargo llvm-cov --lcov --output-path <scratch>/lcov.info", "convert": "coverage_convert.py <root> <scratch>/lcov.info --format lcov"},
        "mutation": {"tool": "cargo-mutants", "check": ["cargo-mutants"], "install": "cargo install --locked cargo-mutants",
                     "run": "git diff <base> > <scratch>/change.diff && cargo mutants --in-diff <scratch>/change.diff --output <scratch>",
                     "convert": "mutation_report.py <scratch>/mutants.out/outcomes.json --format cargo-mutants"},
        "lint": {"tool": "Clippy", "check": ["cargo-clippy"], "install": "see https://doc.rust-lang.org/stable/clippy/installation.html",
                 "run": "cargo clippy -- -W clippy::correctness -W clippy::suspicious -W clippy::complexity -W clippy::perf", "convert": None,
                 "gap": "Clippy diagnostics are read as printed; no converter normalizes them into the scorer report",
                 "note": "compiles the project (build scripts and proc macros run): needs the same authorization as its tests. "
                         "Do not enable the whole restriction group. `cargo clippy --fix` implies --all-targets; use it only in an authorized repair."},
    },
    "typescript": {
        "coverage": {"tool": "c8 or the project's Jest/Vitest coverage", "check": ["npx"],
                     "install": "project devDependency (npm i -D c8); npx runs it without a global install",
                     "run": "npx c8 --reporter=lcov --report-dir <scratch> <test command>", "convert": "coverage_convert.py <root> <scratch>/lcov.info --format lcov"},
        "mutation": {"tool": "StrykerJS", "check": ["npx"], "package": "@stryker-mutator/core",
                     "install": "npm i -D @stryker-mutator/core plus the project's test-runner plugin",
                     "run": "npx stryker run --reporters json --mutate <changed files>",
                     "convert": "mutation_report.py reports/mutation/mutation.json --format stryker"},
    },
    "java": {
        "coverage": {"tool": "JaCoCo", "check": ["java"], "install": "jacoco-maven-plugin or the Gradle jacoco plugin in the project build",
                     "run": "mvn test jacoco:report (or gradle test jacocoTestReport)", "convert": "coverage_convert.py <root> target/site/jacoco/jacoco.xml --format jacoco"},
        "mutation": {"tool": "PIT with pitest-mutation-testing-elements-plugin", "check": ["java"],
                     "install": "pitest-maven plus the mutation-testing-elements plugin in the project build",
                     "run": "mvn org.pitest:pitest-maven:mutationCoverage -DoutputFormats=HTML2,JSON", "convert": "mutation_report.py <report>.json --format stryker"},
        "lint": {"tool": "Error Prone", "check": [], "install": None, "run": None, "convert": None,
                 "gap": "Error Prone runs inside the project's Bazel, Maven, Ant or Gradle build and has no standalone command; "
                        "use the project's configured build, see https://errorprone.info/docs/installation"},
    },
    "go": {
        "coverage": {"tool": "go test -coverprofile", "check": ["go"], "install": "Go toolchain (brew install go)",
                     "run": "go test -coverprofile=<scratch>/cover.out ./...", "convert": "coverage_convert.py <root> <scratch>/cover.out --format go"},
        "mutation": {"tool": "no supported normalizer", "check": [], "install": None, "run": None, "convert": None,
                     "gap": "Go mutation tools (for example gremlins) are not normalized; report their raw counts as unverified"},
    },
    "swift": {
        "coverage": {"tool": "swift test --enable-code-coverage + llvm-cov", "check": ["swift", "xcrun"], "install": "Xcode or a Swift toolchain",
                     "run": "swift test --enable-code-coverage && xcrun llvm-cov export -format=lcov -instr-profile <profdata> <test binary> > <scratch>/lcov.info",
                     "convert": "coverage_convert.py <root> <scratch>/lcov.info --format lcov"},
        "mutation": {"tool": "no supported normalizer", "check": [], "install": None, "run": None, "convert": None,
                     "gap": "Swift mutation tools (for example muter) are not normalized; report their raw counts as unverified"},
    },
    "python": {
        "coverage": {"tool": "coverage.py", "check": ["coverage"], "install": "pip install coverage (project environment)",
                     "run": "coverage run -m pytest && coverage lcov -o <scratch>/lcov.info", "convert": "coverage_convert.py <root> <scratch>/lcov.info --format lcov"},
        "mutation": {"tool": "no supported normalizer", "check": [], "install": None, "run": None, "convert": None,
                     "gap": "Python mutation tools (mutmut, Mutator) are not normalized; follow measurement.md and report raw counts as unverified"},
    },
}


def java_runtime():
    """macOS ships /usr/bin/java as a placeholder; require a real JDK home."""
    home = os.environ.get("JAVA_HOME")
    if home and (Path(home) / "bin" / "java").is_file():
        return True
    if sys.platform == "darwin":
        locator = Path("/usr/libexec/java_home")
        if not locator.exists():
            return False
        try:
            return subprocess.run([str(locator)], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    return shutil.which("java") is not None


def available(names):
    if not names:
        return False
    return all(java_runtime() if n == "java" else shutil.which(n) for n in names)


def package_resolves(project, package):
    """Node-style lookup of node_modules/<package>/package.json from project upwards; no network."""
    if project is None:
        return False
    start = Path(project).resolve()
    return any((folder / "node_modules" / package / "package.json").is_file() for folder in [start, *start.parents])


def availability(spec, project):
    """True/False for PATH tools; a project-dependency tool also needs its package to resolve from project."""
    if not available(spec["check"]):
        return {"available": False}
    if "package" not in spec:
        return {"available": True}
    if package_resolves(project, spec["package"]):
        return {"available": True, "resolved_from": str(Path(project).resolve())}
    return {"available": False, "requires_project_dependency": spec["package"],
            "note": "pass --project <dir> where the package is installed; npx would otherwise fetch it from the network"}


def doctor(project=None):
    binary = complexity.native_binary()
    report = {"schema": "code-audit.companions.v1",
              "complexity_analyzer": {"available": binary is not None, "path": str(binary) if binary else None,
                                      "build": complexity.native_build_hint(),
                                      "languages": ["python", "rust", "typescript", "javascript", "java", "go", "swift"]},
              "languages": {}}
    for language, kinds in COMPANIONS.items():
        report["languages"][language] = {kind: {**spec, **availability(spec, project)} for kind, spec in kinds.items()}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["doctor"], help="report companion availability")
    parser.add_argument("--language", choices=sorted(COMPANIONS), help="limit to one language")
    parser.add_argument("--project", help="project directory used to resolve project-dependency tools such as StrykerJS")
    args = parser.parse_args(argv)
    report = doctor(args.project)
    if args.language:
        report["languages"] = {args.language: report["languages"][args.language]}
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
