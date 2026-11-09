#!/usr/bin/env python3
"""Check recorded algorithm output against a small, declarative JSON fixture."""

import argparse
from fractions import Fraction
from itertools import islice
import json
from pathlib import Path
import re
import sys


SCHEMA = "code-audit.algorithm-fixture.v1"
MAX_BYTES = 64 * 1024
MAX_REPORT_BYTES = 256 * 1024
MAX_ROWS = 64
MAX_DIMENSIONS = 32
MAX_DEPTH = 24
MAX_KEY_CHARS = 128
MAX_FINDINGS = 64
RATIO = re.compile(r"-?[0-9]{1,64}/[1-9][0-9]{0,63}")
EXPONENT = re.compile(r"[eE]([+-]?[0-9]+)$")
MISSING = object()
VALUE_TYPES = {dict: "object", list: "array", str: "string", int: "integer",
               Fraction: "number", bool: "boolean", type(None): "null"}


def decimal(token):
    exponent = EXPONENT.search(token)
    if len(token) > 96 or (exponent and abs(int(exponent[1])) > 64):
        raise ValueError("JSON number exceeds the fixture precision limit")
    return Fraction(token)


def integer(token):
    if len(token.lstrip("-")) > 64:
        raise ValueError("JSON integer exceeds the fixture precision limit")
    return int(token)


def nonfinite(token):
    raise ValueError(f"{token} is not a finite JSON number")


def unique_fields(pairs):
    fields = {}
    for name, value in pairs:
        if len(name) > MAX_KEY_CHARS:
            raise ValueError(f"JSON field name exceeds the {MAX_KEY_CHARS}-character limit")
        if name in fields:
            raise ValueError(f"duplicate JSON field {name!r}")
        fields[name] = value
    return fields


def numeric(value, name, *, ratios=False):
    if type(value) in (int, Fraction):
        return Fraction(value)
    if ratios and isinstance(value, str) and RATIO.fullmatch(value):
        return Fraction(value)
    allowed = "a number or an exact fraction string" if ratios else "a JSON number"
    raise ValueError(f"{name} must be {allowed}")


def require_fields(value, required, optional=()):
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    missing = set(required) - value.keys()
    extra = value.keys() - (set(required) | set(optional))
    if missing or extra:
        raise ValueError(f"invalid fields: missing {sorted(missing)}, unexpected {sorted(extra)}")


def matrix(values, name, max_columns):
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_ROWS:
        raise ValueError(f"{name} must have between 1 and {MAX_ROWS} rows")
    if not all(isinstance(row, list) and 1 <= len(row) <= max_columns for row in values):
        raise ValueError(f"{name} must have between 1 and {max_columns} columns")
    if any(len(row) != len(values[0]) for row in values):
        raise ValueError(f"{name} must be rectangular")
    return [[numeric(value, name) for value in row] for row in values]


def kmeans_step(spec):
    points = matrix(spec["points"], "points", MAX_DIMENSIONS)
    centroids = matrix(spec["centroids"], "centroids", MAX_DIMENSIONS)
    if len(points[0]) != len(centroids[0]):
        raise ValueError("points and centroids must have the same dimensions")

    groups = [[] for _ in centroids]
    labels = []
    inertia = Fraction(0)
    for point in points:
        distances = [sum((a - b) ** 2 for a, b in zip(point, center)) for center in centroids]
        label = min(range(len(centroids)), key=distances.__getitem__)
        labels.append(label)
        groups[label].append(point)
        inertia += distances[label]

    if any(not group for group in groups):
        raise ValueError("the fixture assigns no points to a centroid; empty-cluster policies differ")
    updated = [[sum(column) / len(group) for column in zip(*group)] for group in groups]
    return {"labels": labels, "centroids": updated, "assignment_inertia": inertia}


def dbscan(spec):
    distances = matrix(spec["distances"], "distances", MAX_ROWS)
    size = len(distances)
    if any(len(row) != size for row in distances):
        raise ValueError("distances must be square")
    if any(distances[i][i] != 0 for i in range(size)):
        raise ValueError("distances must have a zero diagonal")
    if any(distances[i][j] < 0 or distances[i][j] != distances[j][i]
           for i in range(size) for j in range(i)):
        raise ValueError("distances must be symmetric and nonnegative")

    eps = numeric(spec["eps"], "eps")
    min_samples = spec["min_samples"]
    if eps <= 0 or type(min_samples) is not int or min_samples < 1:
        raise ValueError("eps and integer min_samples must be positive")
    neighbors = [[j for j, distance in enumerate(row) if distance <= eps] for row in distances]
    core = [i for i, adjacent in enumerate(neighbors) if len(adjacent) >= min_samples]
    unseen = set(core)
    components = []
    for start in core:
        if start not in unseen:
            continue
        unseen.remove(start)
        component = [start]
        # Traverse edges among core points only. A border point cannot merge components.
        for current in component:
            adjacent = unseen.intersection(neighbors[current])
            unseen.difference_update(adjacent)
            component.extend(adjacent)
        components.append(sorted(component))
    return {"neighbors": neighbors, "core": core, "core_components": components}


def pointer(path, key):
    escaped = str(key).replace("~", "~0").replace("/", "~1")
    return f"{path}/{escaped}"


def differences(expected, observed, tolerance, path=""):
    if isinstance(expected, dict) and isinstance(observed, dict):
        for key in sorted(expected.keys() | observed.keys()):
            yield from differences(expected.get(key, MISSING), observed.get(key, MISSING),
                                   tolerance, pointer(path, key))
        return
    if isinstance(expected, list) and isinstance(observed, list) and len(expected) == len(observed):
        for i, (want, got) in enumerate(zip(expected, observed)):
            yield from differences(want, got, tolerance, pointer(path, i))
        return

    if isinstance(expected, Fraction):
        try:
            actual = numeric(observed, "observation", ratios=True)
        except ValueError:
            pass
        else:
            absolute, relative = tolerance
            if abs(actual - expected) <= absolute + relative * abs(expected):
                return
    elif type(expected) is type(observed) and expected == observed:
        return

    finding = {"path": path}
    if expected is not MISSING:
        finding["expected"] = expected
    if observed is not MISSING:
        finding["observed"] = observed
    if expected is not MISSING and observed is not MISSING and type(expected) is not type(observed):
        finding["expected_type"] = VALUE_TYPES[type(expected)]
        finding["observed_type"] = VALUE_TYPES[type(observed)]
    yield finding


def compare(spec):
    required = {
        "kmeans_step": ("points", "centroids", "observed"),
        "dbscan": ("distances", "eps", "min_samples", "observed"),
        "observations": ("expected", "observed"),
    }
    kind = spec.get("kind") if isinstance(spec, dict) else None
    if not isinstance(kind, str) or kind not in required:
        raise ValueError("kind must be kmeans_step, dbscan, or observations")
    require_fields(spec, ("kind", *required[kind]), ("tolerance",))
    if not isinstance(spec["observed"], dict):
        raise ValueError("observed must be a JSON object")

    tolerances = spec.get("tolerance", {})
    require_fields(tolerances, (), ("abs", "rel"))
    tolerance = tuple(numeric(tolerances.get(key, 0), f"tolerance.{key}") for key in ("abs", "rel"))
    if any(value < 0 for value in tolerance):
        raise ValueError("tolerances must be nonnegative")

    if kind == "kmeans_step":
        expected = kmeans_step(spec)
    elif kind == "dbscan":
        expected = dbscan(spec)
    else:
        expected = spec["expected"]
        if not isinstance(expected, dict) or not expected:
            raise ValueError("expected must contain named observations")

    findings = list(islice(differences(expected, spec["observed"], tolerance), MAX_FINDINGS + 1))
    return {"kind": kind, "status": "fail" if findings else "pass",
            "expected": expected, "findings": findings[:MAX_FINDINGS],
            "findings_truncated": len(findings) > MAX_FINDINGS}


def encoded(value):
    if isinstance(value, Fraction):
        return value.numerator if value.denominator == 1 else str(value)
    raise TypeError(f"unsupported fixture result: {type(value).__name__}")


def check_depth(value, depth=0):
    if depth > MAX_DEPTH:
        raise ValueError("fixture exceeds the nesting limit")
    if isinstance(value, dict):
        for child in value.values():
            check_depth(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            check_depth(child, depth + 1)


def load(stream):
    raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError(f"fixture exceeds the {MAX_BYTES}-byte limit")
    spec = json.loads(raw, parse_int=integer, parse_float=decimal,
                      parse_constant=nonfinite, object_pairs_hook=unique_fields)
    check_depth(spec)
    return spec


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", help="JSON fixture path, or - for stdin")
    args = parser.parse_args(argv)
    try:
        if args.fixture == "-":
            spec = load(sys.stdin.buffer)
        else:
            with Path(args.fixture).open("rb") as stream:
                spec = load(stream)
        result = compare(spec)
        report = json.dumps({"schema": SCHEMA, **result}, default=encoded)
        if len(report) + 1 > MAX_REPORT_BYTES:
            raise ValueError(f"fixture receipt exceeds the {MAX_REPORT_BYTES}-byte limit")
    except (OSError, ValueError, RecursionError) as error:
        print(json.dumps({"schema": SCHEMA, "status": "invalid", "error": str(error)}))
        return 2
    print(report)
    return int(result["status"] == "fail")


if __name__ == "__main__":
    sys.exit(main())
