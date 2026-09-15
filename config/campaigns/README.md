# Histogram campaign defaults

For future campaigns, split systematic families into separate jobs instead of
using `SYSTEMATICS=(Central all)`. This limits the work and memory per job,
especially for DY. Use the existing campaign runner with:

```bash
SYSTEMATICS=(
  Central
  JEReta0pt0 JEReta1pt0 JEReta2pt0 JEReta2pt1 JEReta3pt0 JEReta3pt1
  JES_Total Muon PDF PU QCDScale ScaRe
)
```

Each family gets its own output directory and submission. Up/down variations
within a family stay together. `submit` retains missing-only behavior.
Extend this list explicitly when a campaign needs additional systematic sources.

The Sep03 H, Z and Signal campaigns follow this convention, including their
DY-only configurations. New submissions write to the individual family
directories, not `all/`. The `hadd` and `merge-syst` actions use the configured
family directories. Existing `all/` and `all_hadded/` outputs are not migrated.
