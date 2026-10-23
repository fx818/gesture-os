# P1.11 — Point A calibration

**Date:** 2026-09-18 · **Point A rev:** 1 · **Corpus:** 113 rows
(`fixtures/calibration/app_context.tsv` — 10 harvested live from this desktop, 103 authored)

## Headline

| run | accuracy | note |
|---|---|---|
| rules only, offline | 113/113 | **not meaningful** — see caveat |
| live Jev, original labels | 109/113 (96.5%) | the informative run |
| live Jev, corrected labels | 113/113 | partly circular — see caveat |

**The number to trust is 96.5%, and even that understates it:** three of the four disagreements
were *my labels* being wrong, not the model's answers.

## What actually matters: confidence separates

From the original (uncorrected) run:

```
confidence      n    correct   accuracy
0.95 - 1.00    89        87      97.8%
0.85 - 0.95    15        15     100.0%
0.70 - 0.85     7         7     100.0%
0.50 - 0.70     1         0        0%
0.00 - 0.50     1         0        0%
                             ≥0.85: 102/104 = 98.1%
```

Both errors in the ≥0.85 band were mislabels on my side. Both genuinely ambiguous rows —
`htop / htop` and a portal file picker — landed **below 0.7**, which is the model correctly
declining rather than guessing.

That is the property the whole architecture is built on, and it holds.

**Decision: `act_threshold` stays at 0.85** in `config/judgment/points.yaml`. The data would
support 0.90; 0.85 is kept because the 0.85–0.95 band was clean and raising it only buys caution
at the cost of more fallbacks.

## Two caveats, stated plainly

**The rules-only 113/113 is close to meaningless.** I wrote the corpus and the rules table in the
same session, so it tests a lookup table against its own keys. It shows coverage of this corpus,
not generalization. Its real value was diagnostic — see below.

**The corrected-label 113/113 is partly circular.** Four rows were relabelled *after* seeing the
model disagree. Each change is annotated in the TSV with a reason, and in each case the model's
answer is the more useful one for gesture remapping, which is what the label is for: JupyterLab is
where you edit code; an ssh session and `htop` are terminal contexts; a portal file picker is file
browsing. But a corpus edited in response to results cannot also be an independent measure of them.

**What would make this trustworthy:** titles harvested from real usage over days, labelled before
running anything. The harness reads a TSV, so that is a drop-in replacement.

## The offline baseline earned its keep anyway

Running rules-only first found a real bug that the live run would have masked. The original table
matched one combined "app name + title" haystack, first rule wins, code_editor first. So:

- `alacritty` running `nvim ~/src/main.rs` → **code_editor at 0.80**
- Chrome showing `GitHub - anthropics/claude-code` → **code_editor at 0.80**

Confidently wrong, which is worse than unknown — 0.80 clears most act thresholds. Fixed by matching
the **application name first at full confidence**, falling back to the title at a 0.65 discount,
and normalizing punctuation so `sublime_text`, `code-oss` and `org.gnome.TextEditor` match the
patterns they obviously should.

## Latency (confirms ADR-0004)

```
p50  390 ms
p95  648 ms
max 1040 ms   (first call of a session)
```

Point A is unaffected — it fires on focus change and caches per window. Point C (radial menu,
400–500 ms dwell) is confirmed unworkable as a blocking call: a p95 of 648 ms exceeds the entire
dwell. ADR-0004's inversion stands.

## `is_text_entry` is fixed

The P1.1 spike had it clustered at 0.41–0.63 — saying nothing. After rewording it against concrete
situations rather than a degree, it spans 0.00–1.00 with a median of 0.09. It separates. Keep it.
