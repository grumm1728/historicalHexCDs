MEDSL U.S. House returns (#59), used for the vote-share waffle in the district view.

  file                                 used for        source
  1976-2024-house.tab                  C95 onward      Harvard Dataverse doi:10.7910/DVN/IG0UN2, v15
  codebook-us-house-1976–2024.md       column notes    same dataset

Retrieved 2026-11-24. Dataverse asks for a guestbook form before the download, so the
file was downloaded by hand (dataverse_files.zip, not committed) and unzipped here.
Despite the .tab name it is comma-separated.

Source: MIT Election Data and Science Lab, 2017, "U.S. House 1976–2024",
https://doi.org/10.7910/DVN/IG0UN2, Harvard Dataverse. Licence: CC0 1.0.

Notes for the join (measured on the 2024 rows, scripts/medsl_returns.py):
- district is 0 for at-large seats (Census uses "00").
- Fusion states (NY, CT, NJ, SC) give one row per ballot line; votes are summed by candidate.
- Florida (and OK-03 in 2024) prints no count for an unopposed candidate; MEDSL codes it as
  1 vote. The parser sets votes_reported = false for those races.
- Some states report non-votes as candidates (BLANKS, BLANK VOTES, OVER VOTES, UNDER VOTES);
  the parser drops them. WRITEIN, SCATTERING and ALL OTHERS are kept as party "other".
- Names can carry escaped quotes (\"); the parser unescapes them.
- All 435 C119 districts have a 2024 general-election result, and every winner's party
  matches Voteview's primary member.
