#!/usr/bin/env python3
"""Forecast a game launch day's Twitch viewers, hour by hour.

Written for make.fun's "Forecast GTA VI's launch-day Twitch viewers hour
by hour" bounty (gta6-twitch-ccu-forecast-01). The program is run once per
case: it reads the case file(s) in $MAKEFUN_INPUT_DIR (else /input) and
writes one forecast per case to $MAKEFUN_OUTPUT_DIR (else /output).

Method (see METHOD.md for the full write-up and validation):

  A launch day's shape is forecast from the launches the case itself
  ships as `comparables` -- past big releases with hourly Twitch counts
  from 14 days before to 3 days after their release day. For every
  comparable we rebuild its release-day curve (hours 1..24 of its UTC
  release day, from its own `day_start`) and express each hour as a
  ratio to that launch's hour-1 count. The forecast for an hour is the
  target's hour-1 print times a quantile of those ratios.

  Launches are not exchangeable: a launch that opens to 800k viewers in
  hour 1 behaves differently from one that opens to 800. Each comparable
  is therefore weighted by a Gaussian kernel on the log of its hour-1
  count, centred on the target's hour-1 count (bandwidth 1.0 in natural
  log, with a 15% uniform blend so no single launch can dominate), and
  the quantiles are weighted empirical quantiles of the log-ratios. Leave-one-out validation over the 37 usable comparables
  in the practice data scores this at a mean log pinball loss of about
  0.41 across all launches and about 0.21 on launches that opened at
  100k+ viewers (GTA VI's reference class), against about 0.93 / 0.26
  for the house baseline's flat persistence forecast.

  If a case ships no usable comparable, the program falls back to the
  persistence shape: every hour at hour 1's count, with a normal log
  spread widening as 0.15 * sqrt(h - 1).

Standard library only, no network, no randomness: two runs of the same
case produce the same bytes.
"""

import json
import math
import os
from datetime import datetime, timezone

LEVELS_DEFAULT = [0.05, 0.25, 0.5, 0.75, 0.95]

# Gaussian kernel bandwidth on the natural log of hour-1 viewers.
BANDWIDTH = 1.0
# Share of each comparable's weight that is uniform rather than kernel:
# insurance for a target whose hour-1 count lands far outside every
# comparable's, where the kernel alone would rest on one or two launches.
UNIFORM_BLEND = 0.15
# A comparable needs at least this many release-day hours to be used.
MIN_DAY_POINTS = 20
# Fallback persistence spread (natural-log units per sqrt hour).
FALLBACK_SIGMA = 0.15


def parse_ts(text):
    """Parse an ISO 8601 UTC timestamp like 2026-11-19T00:00:00Z."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def release_day_curve(comp):
    """A comparable's release-day curve: {hour 1..24: viewers}.

    Hours are taken from the comparable's own `day_start`; points that
    do not fall exactly on an hour of that UTC day are ignored.
    """
    try:
        start = parse_ts(comp["day_start"])
    except (KeyError, TypeError, ValueError):
        return {}
    curve = {}
    for point in comp.get("hourly") or []:
        viewers = point.get("viewers")
        if viewers is None:
            continue
        try:
            delta = (parse_ts(point["from"]) - start).total_seconds()
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= delta < 24 * 3600 and delta % 3600 == 0:
            curve[int(delta // 3600) + 1] = float(viewers)
    return curve


def weighted_quantile(pairs, level):
    """The `level` quantile of weighted samples [(value, weight)].

    Linear interpolation on the cumulative weight, the weighted
    analogue of the usual type-7 sample quantile.
    """
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    if total <= 0:
        return ordered[len(ordered) // 2][0]
    target = level * total
    cum = 0.0
    prev_x, prev_cum = ordered[0][0], 0.0
    for x, w in ordered:
        cum += w
        if cum >= target:
            if cum == w:
                return x
            return prev_x + (target - prev_cum) / w * (x - prev_x)
        prev_x, prev_cum = x, cum
    return ordered[-1][0]


def norm_ppf(p):
    """Inverse standard normal CDF (Acklam's rational approximation)."""
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285984469534e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
        (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def round2(x):
    """Round to 2 decimals, half up (values here are always positive)."""
    return math.floor(x * 100 + 0.5) / 100


def forecast_case(case):
    """The 23 forecast rows (hours 2..24) for one case."""
    levels = case.get("levels") or LEVELS_DEFAULT
    known = {row.get("hour"): row for row in case.get("known") or []}
    first = known.get(1) or {}
    p1 = max(1.0, float(first.get("viewers") or 0))

    curves = []
    for comp in case.get("comparables") or []:
        curve = release_day_curve(comp)
        if curve.get(1, 0) > 0 and len(curve) >= MIN_DAY_POINTS:
            curves.append(curve)

    rows = []
    if curves:
        log_p1 = math.log(p1)
        uniform = UNIFORM_BLEND / len(curves)
        weights = [
            (1 - UNIFORM_BLEND)
            * math.exp(-((math.log(c[1]) - log_p1) ** 2) / (2 * BANDWIDTH ** 2))
            + uniform
            for c in curves
        ]
        for hour in range(2, 25):
            pairs = [
                (math.log(c[hour] / c[1]), w)
                for c, w in zip(curves, weights)
                if hour in c and c[hour] > 0
            ]
            if pairs:
                qs = [p1 * math.exp(weighted_quantile(pairs, t)) for t in levels]
            else:
                qs = [p1] * len(levels)
            rows.append((hour, qs))
    else:
        # No usable comparable: persistence with a widening normal spread.
        for hour in range(2, 25):
            spread = FALLBACK_SIGMA * math.sqrt(hour - 1)
            qs = [p1 * math.exp(norm_ppf(t) * spread) for t in levels]
            rows.append((hour, qs))

    out = []
    for hour, qs in rows:
        # Quantiles must be non-decreasing, finite and within (0, 1e9].
        clean = sorted(min(max(q, 0.01), 1_000_000_000.0) for q in qs)
        out.append({"hour": hour, "q": [round2(q) for q in clean]})
    return out


def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(output_dir, exist_ok=True)
    names = sorted(f for f in os.listdir(input_dir) if f.endswith(".in"))
    for name in names:
        with open(os.path.join(input_dir, name), encoding="utf-8") as fh:
            case = json.load(fh)
        hours = forecast_case(case)
        stem = name[: -len(".in")]
        with open(os.path.join(output_dir, stem + ".out"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"hours": hours}) + "\n")


if __name__ == "__main__":
    main()
