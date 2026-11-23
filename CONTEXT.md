# Historical HexCDs

A cartogram of every U.S. Congress (C1–C119) in which each House seat is a pentahex and
each state's area is proportional to its delegation.

## Language

**Seat**:
One pentahex tile, one unit of a state's House apportionment in one Congress. Every seat
exists whether or not it has a district.
_Avoid_: tile (fine for geometry, but not for identity), CD, district

**District**:
A real, numbered geographic constituency in one Congress (e.g. OH-07 in C45). Holds one
or more seats. Numbers are reused across redistrictings, so a district never carries over
between Congresses.
_Avoid_: CD (ambiguous with seat), cd_index

**At-large seat**:
A seat with no district geography: a sole-seat state, a general-ticket state, or a seat
elected statewide alongside districts. It makes no claim about position.
_Avoid_: district 0

**Member**:
The person who holds a seat. The only identity that carries across Congresses.
_Avoid_: representative (fine in prose), incumbent

**Primary member**:
The member a seat is drawn for: the first member seated in that Congress. Other members
of the same seat in that Congress count as member changes.

**Numbering**:
The assignment of districts to seats within a state for one Congress. It is a labelling
of finished seats and never changes their geometry.
_Avoid_: matching, cd_index

**Metro district**:
A district with at least half its population in one national metro. Classified from
real geography, independently of which seats carry metro labels.

**Metro mismatch**:
A seat whose metro label disagrees with the metro district numbered onto it, because the
real map and the seat-count rule put a different number of districts in a metro.

**Political record**:
What a source says about one district in one Congress: its primary member, party,
ideology, and later its election result. It is keyed by district, never by seat.

## Relationships

- A **State** has **Seats** in each Congress; seats per state = its apportionment.
- A **District** holds one or more **Seats**; an **At-large seat** belongs to no district.
- **Numbering** maps each **District** onto as many **Seats** as it has.
- A **Seat** has one **Primary member** and zero or more member changes per Congress.
- A seat is coloured by following **Seat → District (Numbering) → Political record**.

## Example dialogue

> **Dev:** "Does OH-07 in C45 have the same seat as OH-07 in C90?"
> **Domain expert:** "No. Districts don't carry over, and seats re-partition at every
> reapportionment. Only the member carries over: follow the member, not the number."

## Flagged ambiguities

- "district" was used for both the pentahex and the real constituency (#53). Resolved:
  the pentahex is a **Seat**, the constituency is a **District**.
