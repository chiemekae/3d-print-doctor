# Evaluations

Each folder is one test case: a user request (`prompt.md`), what a good result looks like (`case.yaml`), and one statement per file in `graders/` that a judge checks against the run. The layout is the one `claude plugin eval` reads.

| Case | Checks that the agent |
|---|---|
| `explains-mixed-temperature-error` | reads the project to explain OrcaSlicer's mixed-temperature error, offers both fixes, leaves the project alone |
| `runs-pre-print-checklist` | works through "Before starting a print" and asks for a go-ahead instead of starting; raises both plate-check warnings |
| `diagnoses-stringing-from-evidence` | checks dryness, the print log, and photos before proposing one change at a time |
| `answers-settings-from-log` | answers from the print log and separates successful prints from unknown ones |

**Input files** come from `tests/eval-fixtures/`: a test bracket modeled in OpenSCAD (`test-bracket.scad`), built into a project with `build_fixture.py` using settings that reproduce the problems these cases test (PLA part, PETG supports at zero gap, a bed that follows the hottest filament, purge flushed into infill), then sliced with `--allow-mix-temp`.

**Before running them.** The cases run against the machine they're on: its config in `~/.config/3d-print-doctor/`, its print log, its OrcaSlicer presets, and its printer on the LAN. Two cases depend on that history (the stringing and PETG cases look for the user's own log entries), so they're most meaningful on a machine with a print log.

The skill never starts a print without a go-ahead, but a test can't promise a model will follow it. Run `runs-pre-print-checklist` with the printer off or not in LAN mode, or with a rule in the run's instructions that no command may move the printer. The runs in this repo's history used that rule: read-only commands only, with anything that would change the printer, the print log, presets, or files outside the run's folder written to `actions.md` instead of run.

**Running them.** With Claude Code, from the skill folder: `claude plugin eval . --scaffold --allow-tools Write,Edit,Bash`. These are real, billed model runs. The skill-creator skill can also run them with and without the skill on several models and show the results side by side.
