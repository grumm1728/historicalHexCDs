Voteview member data (#53), used for the party / DW-NOMINATE political layer.

  file               used for   URL
  H119_members.csv   C119       https://voteview.com/static/data/out/members/H119_members.csv

Retrieved 2026-11-23. No account or key needed.

Source: Lewis, Jeffrey B., Keith Poole, Howard Rosenthal, Adam Boche, Aaron Rudkin, and
Luke Sonnet (2026). Voteview: Congressional Roll-Call Votes Database. https://voteview.com/
Voteview asks users to cite it as above.

Notes for the join (measured on C119):
- At-large seats have district_code 1 in Voteview, but "00" in the Census CD files.
- A district can have several rows in one Congress: mid-term replacements, and a member who
  switches party gets a second row under the same icpsr (C119 CA-3, R -> 328 Independent).
  The file has no service dates. In all 11 C119 cases the first row in file order is the
  member seated at the start of the Congress (the "primary member" in CONTEXT.md). Re-check
  this before relying on file order for older Congresses.
- party_code: 100 Democrat, 200 Republican, 328 Independent.
