# Rule: Documentation

- **The design doc is the source of truth.** Read
  `docs/portfolio-signal-system-design.md` before non-trivial changes; update it when
  the design changes.
- **Keep CLAUDE.md current.** No stale claims (e.g. "no suite yet", "blocks first
  backtest"). If you change layout, commands, or state, update CLAUDE.md in the same
  change.
- **Every strategy documents its thesis** in its class docstring (what edge, why it
  should work, key params). A strategy with no stated thesis is not done.
- **Record experiment findings** in `docs/strategy-study.md` — including negative
  results and measurement corrections. Honesty over flattering numbers.
- **These rules are living.** When a convention changes, edit the relevant
  `docs/rules/*.md` rather than letting practice drift from the written rule.
