# Method: forecasting GTA VI's launch-day Twitch viewers

## What is being forecast

For each hour h = 2..24 of 2026-11-19 (UTC), five quantiles (5%, 25%,
50%, 75%, 95%) of the concurrent-viewer count of Twitch's "Grand Theft
Auto VI" category (Twitch game id 1867279146), where an hour's count is
the mean of that hour's per-minute directory reads. The score is the
mean pinball loss on the natural-log scale over all hours and levels,
so what matters is the *shape* of the day relative to hour 1 and an
honest spread — a 20% miss costs the same at 10k viewers as at 1M.

## The model (main.py)

The case file itself carries the training data: `comparables`, 42 past
big launches with hourly Twitch counts (SullyGnome hourly category
averages) from 14 days before to 3 days after each release day. The
program:

1. Rebuilds each comparable's release-day curve — hours 1..24 of its
   own UTC release day, located from its `day_start` — and expresses
   every hour as a ratio to that launch's hour-1 count. Comparables
   without a usable release day (fewer than 20 of 24 hours, or no
   hour-1 count) are dropped; in the practice data that removes only
   the GTA VI category's own pre-release history, which has no release
   day yet.
2. Weights each remaining comparable by how similar its *scale* is to
   the target: a Gaussian kernel on the log of its hour-1 count,
   centred on the target's hour-1 print, bandwidth 1.0, blended with
   15% uniform weight so no single launch can dominate.
3. Forecasts hour h as the target's hour-1 print times the weighted
   empirical quantiles of the comparables' log-ratios at hour h.

Why scale weighting: the pooled ratio distribution mixes two different
animals. Simultaneous worldwide unlocks (Black Myth: Wukong, Hollow
Knight: Silksong, Baldur's Gate 3) sit near zero at 00:00 UTC and spike
10–100x at their unlock hour; rolling midnight-local console launches
are already large at hour 1 and move within a much narrower band.
GTA VI is the second kind — it unlocks at midnight local time country
by country (New Zealand first, 2026-11-18T11:00Z; central Europe
23:00Z; UK 00:00Z; US East 05:00Z; US West 08:00Z) — and it is huge, so
its best analogues are the launches that also opened huge. Weighting
by hour-1 scale selects exactly those, without any hand-coded list.

Fallback: if a case ships no usable comparable, the program emits the
persistence shape (every hour at hour 1's count, normal log spread
0.15·sqrt(h−1)) — the house baseline's shape.

## Validation

The contest's scorer is server-side (`grade-local` refuses this
competition), so the local check is leave-one-out over the practice
comparables, run through the shipped code path (`validate_loo.py`,
needs a practice case file, e.g. the kit's `input/p00.in`): each of
the 37 usable launches in turn is treated as the target — its real
hour-1 count as `known`, the other launches as `comparables` — and the
forecast is scored against its real hours 2..24.

| targets | this model | house baseline shape |
| --- | --- | --- |
| all 37 launches | **0.412** | 0.930 |
| hour-1 ≥ 100k (16 launches) | **0.215** | 0.261 |
| rolling launches, hour-1/peak ≥ 0.25 (24) | **0.209** | 0.265 |

(Mean log pinball loss, lower is better. The baseline's 0.93 here is
not comparable to the ~0.387 the rules quote for it on the four
practice cases: the LOO pool includes the simultaneous-unlock launches
whose hour-1 counts are near zero, which persistence forecasts
catastrophically; on big rolling launches — GTA VI's class — the
baseline earns its ~0.26.)

## What the forecast looks like at GTA VI's scale

Hour 1's print is only known when the final case is cut
(2026-11-19T01:00Z), but the shape the model produces for a large
rolling launch is stable. Illustrative medians from the practice
comparable set (38 launches; the final set adds the four practice
launches, including Red Dead Redemption 2, Rockstar's own previous
launch):

| hour-1 print | median peak | peak hour (UTC) | hour-24 median |
| --- | --- | --- | --- |
| 300,000 | ≈377,000 | 19 | ≈341,000 |
| 600,000 | ≈719,000 | 21 | ≈565,000 |
| 900,000 | ≈1,065,000 | 21 | ≈806,000 |

The shape: a dip through the UTC morning (Europe asleep, the US not
yet unlocked), a climb from the US East unlock (05:00Z) through the US
day, and a peak in the 19:00–22:00Z window when European prime time
overlaps the US afternoon/evening. The 90% band at the peak hour is
wide — roughly 0.6x to 2x the median — which the reference class
supports: even among similar launches, day-1 trajectories diverge a
lot (Elden Ring and Elden Ring Nightreign peaked *in* hour 1 and faded;
Diablo IV kept climbing to hour 18).

## External anchors (context, not model inputs)

These published figures motivated the reference-class choice; the
model itself uses only the case's own data.

- GTA VI releases 2026-11-19 on PlayStation 5 and Xbox Series X|S,
  single-player, no PC version at launch (competition rules; Take-Two
  / Rockstar announcements). Console-only rolling-midnight launches
  are the right reference class.
- GTA VI Trailer 1 drew over 93 million YouTube views in its first 24
  hours, a record for a non-music video debut (YouTube's official
  blog, 2023-12-05; Guinness World Records counts 90.4M). Trailer 2
  drew 475 million views across platforms in 24 hours (Rockstar via
  The Hollywood Reporter, May 2025). Demand-side interest is far
  beyond any comparable launch.
- The largest single-player launch-day Twitch audience on record at
  its time was Cyberpunk 2077's: about 1.14 million peak concurrent
  viewers on 2020-12-10 (Twitch Tracker figures reported by The
  Loadout and Dexerto). Cyberpunk 2077 is one of the model's
  comparables and, at an 852k hour-1, one of the most heavily weighted
  for a GTA-scale target.
- Red Dead Redemption 2 (Rockstar's previous game, console-only,
  rolling midnight local) opened at 116,550 viewers in its UTC hour 1
  on 2018-10-26 — the practice case p01's own `known` figure, from
  SullyGnome data in the competition kit. Twitch's audience has grown
  substantially since 2018; the model works in ratios to hour 1, so
  platform growth is absorbed by hour 1's print rather than assumed.

## Limitations

- Comparables' hourly figures are SullyGnome's hourly averages; the
  final's prints are means of per-minute reads. Close, not identical
  (the rules say the same).
- The model assumes GTA VI's day behaves like a weighted blend of past
  big launches. A launch-day outage, a review embargo surprise, or a
  streamer event with no precedent in the reference set would land in
  the tails — the quantiles are honestly wide for that reason.
- All point figures above that are not in the competition kit are
  labelled with their source; the scenario table is the model's own
  output on practice data, not a promise about 2026-11-19.
