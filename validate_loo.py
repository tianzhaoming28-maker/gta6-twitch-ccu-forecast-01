#!/usr/bin/env python3
"""Leave-one-out validation of main.py's forecast on the practice data.

The competition's scorer is server-side, so this is the local check.
It takes one practice case file (the kit's input/p00.in is a good
choice: its 38 comparables are the reference launches) and treats each
usable comparable in turn as if it were the target launch:

  * the synthetic case's `known` is that launch's real hour-1 count,
  * its `comparables` are the other launches, as raw case data,
  * main.forecast_case produces the forecast, and
  * the forecast is scored against the launch's real hours 2..24 with
    the contest's own score: mean pinball loss on the log scale.

The house baseline (flat persistence, 0.15 * sqrt(h - 1) normal log
spread) is scored the same way for comparison.

Usage: python3 validate_loo.py <path-to-practice-case.in>
"""

import json
import math
import sys

import main as entry

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]


def pinball(y, q, tau):
    d = math.log(max(y, 1.0)) - math.log(q)
    return 2.0 * max(tau * d, (tau - 1.0) * d)


def score_rows(rows, curve):
    total, n = 0.0, 0
    for row in rows:
        h = row["hour"]
        if h in curve:
            for tau, q in zip(LEVELS, row["q"]):
                total += pinball(curve[h], q, tau)
                n += 1
    return total / n if n else None


def baseline_rows(p1):
    return [
        {"hour": h, "q": [p1 * math.exp(z * 0.15 * math.sqrt(h - 1)) for z in Z]}
        for h in range(2, 25)
    ]


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    with open(sys.argv[1], encoding="utf-8") as fh:
        case = json.load(fh)
    comps = case.get("comparables") or []
    targets = []
    for comp in comps:
        curve = entry.release_day_curve(comp)
        if curve.get(1, 0) > 0 and len(curve) >= 20:
            targets.append((comp, curve))
    print(f"{len(targets)} usable launches as leave-one-out targets")

    subsets = {
        "all targets": lambda c: True,
        "hour-1 >= 100k": lambda c: c[1] >= 100_000,
        "rolling (h1/peak >= 0.25)": lambda c: c[1] / max(c.values()) >= 0.25,
    }
    results = {name: {"model": [], "baseline": []} for name in subsets}
    for comp, curve in targets:
        others = [c for c in comps if c is not comp]
        synth = {
            "levels": LEVELS,
            "known": [{"hour": 1, "viewers": curve[1]}],
            "comparables": others,
        }
        model_loss = score_rows(entry.forecast_case(synth), curve)
        base_loss = score_rows(baseline_rows(curve[1]), curve)
        for name, keep in subsets.items():
            if keep(curve):
                results[name]["model"].append(model_loss)
                results[name]["baseline"].append(base_loss)
    for name, res in results.items():
        m, b = res["model"], res["baseline"]
        if m:
            print(f"{name:28s} n={len(m):2d}  model {sum(m) / len(m):.4f}   "
                  f"baseline {sum(b) / len(b):.4f}")


if __name__ == "__main__":
    main()
