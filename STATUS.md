# Status and handoff

Last updated: 29 October 2026. Read with `CLAUDE.md` (how the code works) and `plan.md` (original roadmap).

## What is live

| | |
|---|---|
| Live app | https://cost-benefit-analysis-zc69vmcrcp6ouyi5hzzmz5.streamlit.app |
| Deploys from | `lamv-23/Cost-Benefit-Analysis`, branch `claude/complete-cba-dashboard-hBs4G`, main file `app.py` |
| Cloud Python | **3.12** — set in the app's settings at share.streamlit.io. Streamlit Cloud ignores `runtime.txt`; on 3.14 the build tries to compile numpy 2.0.2 / pandas 2.3.1 and fails |
| Streamlit | 1.50.0 (`requirements.txt`) — the last release that also runs on the local Python 3.9 |
| Parameters | TfNSW Economic Parameter Values 2026.1 (July 2026), **June 2026 prices** |
| Tests | `python3 -m pytest tests -q` — 82 pass on Streamlit 1.50.0 |

Reference result — the built-in sample (urban, 5%, default settings): **BCR 2.79, NPV about $622M**; BCR without reliability 2.38. If these move, a calculation changed.

## What changed in October 2026 (PRs #14–#21, all merged)

- **UI** (#14, #15): Inputs → Results → Cashflow → Sensitivity → Parameters → About; Setup / Traffic / Costs sub-tabs; options shown as "Option N" (keys stay `project_N`); one NPV waterfall; sentence case throughout.
- **Review fixes** (#16): opening a project clears earlier parameter changes; outturn shown exactly as entered.
- **Method** (#17): net recurrent costs (a saving is a benefit, TfNSW CBA Guide §6.8); NSW Carbon Values for the core BCR plus a National-values BCR; road damage savings; reliability as a switch; zero growth after the last modelling year by default; residual value discounted from the end of the final year; BCR "–" when PV costs ≤ 0; per-case safety rates; input warnings.
- **EPV 2026.1** (#18): all parameters re-based to EPV 2026.1 and June 2026 prices — travel time per vehicle-hour, TfNSW depreciation-adjusted VOC (urban stop-start or freeway), own bus rates, EPV carbon schedules and externalities, safety = crash rate × cost per crash by road type and funding basis. June 2024 project files open with a CPI indexing option.
- **Follow-ups** (#19): VOC from stops (off by default), former-car-user savings for active transport, EPV asset lives; generic sample; Streamlit 1.50.0.
- **Text** (#20, #21): About benefit categories restructured; `$` amounts escaped so Markdown doesn't render them as maths; "option" wording.

## Decisions made (keep unless the owner changes them)

- Net recurrent costs; a net saving is a benefit (§6.8), a net increase a cost.
- Core BCR at NSW Carbon Values (central); National central BCR reported alongside.
- Reliability proxy kept (TTS × ratio 1.0 × share 0.3), switchable, BCR without it always shown.
- Start-of-year discounting, stated in About, the summary and the CSV.
- June 2026 price base; rural VOC uses the freeway model (flagged); safety by road type × funding basis.

## Open follow-ups (in priority order)

1. **Check the live app runs on Python 3.12** and shows the sample at BCR 2.79 with "Option 1" labels.
2. **Capital cost indexing** for June 2024 files uses CPI Sydney; construction costs usually rise faster — consider TfNSW road and rail cost escalation indices for capital rows.
3. **Reliability share (0.3)** has no verified source; it is about 15% of the sample's benefits. Replace with a travel-time-variability method or a sourced share.
4. **Rural VOC** is an approximation (freeway model). A faithful version needs the REVS equations (only its parameters are in the EPV).
5. **VSL test** uses a 36% fatal share (tool assumption). EPV Tables 5.2, 5.3 and 5.6 could replace it and make use of the crash counts entered on Traffic → Crashes (currently reference only).
6. **Annualisation default** (6.29 × 336) is generic; EPV Table 2.2 hours by period could give a sourced starting point.
7. **Wider economic benefits** sensitivity uses tool-defined percentages, not EPV values.
8. **Streamlit beyond 1.50** needs Python 3.10+ locally (then `st.plotly_chart` can also move to `width="stretch"`).
9. `PRODUCTION-TODO.md` (internal Azure VM hosting plan) is untouched and still open.

## Housekeeping

Merged branches still to delete (the session's permissions blocked it):

```bash
git push origin --delete worktree-minimal-ui-tabs worktree-ui-review-2 \
  fix/review-15 cba-method-fixes epv-2026 followups about-benefit-text option-wording handoff-status
# old local worktree from a finished session — check it has no uncommitted work first
git worktree remove --force .claude/worktrees/minimal-ui-tabs
git branch -D worktree-minimal-ui-tabs
```

Update a local checkout: `git pull && pip install -r requirements.txt`, then `python3 -m streamlit run app.py`.
