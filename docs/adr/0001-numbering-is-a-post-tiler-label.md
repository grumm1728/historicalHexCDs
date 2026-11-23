# Numbering is a label-only pass after the tiler

Seats get their real districts through a separate post-pass (`scripts/number_seats.py`,
run after the tiler). It reads the finished seats and each state's saved layout record and
writes a sidecar mapping seats to districts. It never feeds back into allocation or
partition. We chose this over letting real district points steer the partition (#48
listed that as an option) because the partition is fragile and its `warnings: 0`
invariant took a lot of work to reach. A post-pass also iterates in seconds rather than a
20–35 min regen. The cost is that numbering quality is capped by seat shapes that were
drawn without knowing the districts.

## Consequences

- Political data is keyed by district in its own sidecar and joined in the viewer
  (seat → district → political record), so a new source such as election returns never
  touches seat files.
- The numbering sidecar records a hash of the tiler output it was built from, and the
  build fails when they don't match.
- If numbering quality turns out to be unacceptable (the ship gate in #53), the fix is to
  revisit this ADR, not to tune the post-pass further.
