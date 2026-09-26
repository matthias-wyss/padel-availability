# Public Research Notes

Checked at: `2026-09-21T00:00:00Z`

This pass used public pages only. No login, private booking session, credential,
cookie, paid API, CAPTCHA solving, or scraper was used. `data/verified_locations.json`
is the source of truth for typed facts and fact-specific evidence records. Fields
not stated by the checked page are `unknown` or `null`.

## Candidate Coverage

| Candidate | Catalog decision | Primary source | Booking status | Remaining uncertainty | Duplicate decision |
| --- | --- | --- | --- | --- | --- |
| AIRPAD Les Acacias | `airpad-les-acacias` confirmed | [AIRPAD](https://www.airpad.ch/airpad) | AIRPAD reserve page linked | Cover, access, rental, locker, and account facts unknown | none identified |
| AIRPAD La Praille | `airpad-la-praille` confirmed | [AIRPAD](https://www.airpad.ch/airpad) | AIRPAD reserve page linked | Cover, access, rental, locker, and account facts unknown | none identified |
| AIRPAD Meyrin | `airpad-meyrin` confirmed | [AIRPAD](https://www.airpad.ch/airpad) | AIRPAD reserve page linked | Cover, access, rental, locker, and account facts unknown | none identified |
| AIRPAD Plan-les-Ouates | `airpad-plan-les-ouates` confirmed | [AIRPAD](https://www.airpad.ch/airpad) | AIRPAD reserve page linked | Cover, access, rental, locker, and account facts unknown | none identified |
| L'Asphalte / Pointe de la Jonction | `asphalte-jonction` probable | [Ville de Genève](https://www.geneve.ch/asphalte), [PadelHike](https://padelhike.ch/en/clubs/l-asphalte) | [Padel Connect Jonction grid](https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=9) | Official and regional sources both say two courts; regional source supplies street address; account requirement remains unknown | same physical site confirmed |
| Padel Station | `padel-station` confirmed | [Padel Station](https://padelstation.ch/) | [Playtomic](https://playtomic.com/fr/clubs/padel-station1) | Published weekday/weekend prices and durations are retained as evidence; membership, account, locker, and racket-rental facts remain unknown because "rackets available" does not establish rental | none identified |
| Centre sportif de Maisonnex | `maisonnex` probable | [Bookinea](https://shop.bookinea.app/fr/meyrin-sports) | [Bookinea](https://shop.bookinea.app/fr/meyrin-sports) | Former commune URL returns 404; current portal supports booking/conditional access and publishes Padel 90 minutes at CHF 60.00 plus guest padel at CHF 15.00, but not address or court count | none identified |
| Centre sportif des Cherpines | `cherpines` confirmed | [Commune de Plan-les-Ouates](https://www.plan-les-ouates.ch/pages/que-faire-a-plan-les-ouates/envie-de-sport/installations-sportives/padel) | [AIRPAD reserve](https://www.airpad.ch/reserve) | Street address, cover, membership, and account facts unknown | none identified |
| Padel des Evaux | `evaux` confirmed | [Fondation des Evaux](https://www.evaux.ch/index.php/reserver/reservation-padel) | [Padel Connect Evaux grid](https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=8) | Membership and price/window facts unknown; the public grid is viewable without login but booking still requires an account | none identified |
| Tennis, badminton et padel de Vernier | `vernier` probable | [Ville de Vernier](https://www.vernier.ch/lieux/tennis-badminton-et-padel-de-vernier), [Padel reservations](https://www.vernier.ch/vie-pratique/demarches/courts-de-padel-reservations), [PadelHike](https://padelhike.ch/en/clubs/padel-first-tc-vernier) | [Padel First](https://padelfirst.ss-r.ch/court-vernier/) online reservation/payment; CHF 48 / 1h30 | Official reservation page confirms two outdoor courts and pricing; doubles format remains directory-only, while access, account, rental, and locker facts remain unknown | none identified |
| Court de padel / TC Bernex | `bernex` to_verify | [PadelHike](https://padelhike.ch/en/clubs/centre-sportif-de-bernex) | No current booking URL confirmed | Access, operator, and booking facts unknown | none identified |
| Padel REDSPORT-LANDAGORA / TC Fraisiers | `fraisiers` to_verify | [PadelHike](https://padelhike.ch/en/clubs/tc-lancy-fraisiers) | No current booking URL confirmed | Current operator and access facts unknown after 2023 cession | none identified |
| CSU Champel | `csu-champel` to_verify | [PadelHike](https://padelhike.ch/en/clubs/csu-champel) | No current booking URL confirmed | University eligibility and access facts unknown | none identified |
| Drizia-Miremont / Bout-du-Monde | `drizia-miremont` to_verify | [PadelHike](https://padelhike.ch/en/clubs/drizia-miremont-tennis-club) | No current booking URL confirmed | Only Drizia directory facts confirmed; slash wording is not an alias | none identified |
| Centre sportif de Cologny | `cologny` to_verify | [PadelHike](https://padelhike.ch/en/clubs/centre-sportif-de-cologny) | No current booking URL confirmed | Access and group conditions unknown | none identified |
| Padel de Collonge-Bellerive | `collonge-bellerive` to_verify | [PadelHike](https://padelhike.ch/en/clubs/tc-collonge-bellerive) | No current booking URL confirmed | Club identity and access facts unknown | none identified |
| David Lloyd Country Club Geneva | `david-lloyd-geneva` to_verify | [PadelHike](https://padelhike.ch/en/clubs/david-lloyd-country-club) | No public booking URL confirmed | Membership status was not carried over from the candidate list | none identified |
| GVA Padel / Palexpo | `gva-palexpo` confirmed | [GVA Padel](https://gvapadel.ch/), [PadelHike](https://padelhike.ch/en/clubs/gva-padel) | [Playtomic](https://playtomic.com/clubs/gva-padel-mp-sports-sa) | Official three-court count conflicts with directory two-court observation | same physical site confirmed |
| Tennis Club Mies-Tannay | `mies-tannay` to_verify | [PadelHike](https://padelhike.ch/en/clubs/tc-mies) | No current booking URL confirmed | Directory identifies Mies; access and booking facts unknown | none identified |
| Tennis Padel Crans VD | `crans-vd` to_verify | [PadelHike](https://padelhike.ch/en/clubs/tp-crans) | No current booking URL confirmed | Access and booking facts unknown | none identified |
| Everness | `everness` confirmed | [Everness padel](https://everness.ch/fr/padel/) | [Everness booking](https://padel.everness.ch/) | Court count, cover, locker, membership, and account facts unknown | none identified |
| Padel Tennis Gland | `gland` to_verify | [PadelHike](https://padelhike.ch/en/clubs/tc-gland) | No current booking URL confirmed | Directory identifies Gland; access and booking facts unknown | none identified |
| Padel Parc Etoy | `padel-parc-etoy` confirmed | [Padel Parc Etoy](https://padelparc.ch/etoy/) | [Playtomic](https://playtomic.com/clubs/padel-parc-etoy) | Access, membership, and account facts unknown | none identified |
| Padel Parc Préverenges | `padel-parc-preverenges` confirmed | [Padel Parc Préverenges](https://padelparc.ch/preverenges/) | [Playtomic](https://playtomic.com/clubs/padel-parc-preverenges) | Access, membership, and account facts unknown | none identified |
| Padel One Echandens | `padel-one-echandens` confirmed | [Padel One clubs](https://www.padel-one.ch/nos-clubs) | [Padel One playing page](https://www.padel-one.ch/jouer) | Access, membership, rental, and account facts unknown | none identified |
| Urban Padel Lausanne | `urban-padel-lausanne` to_verify | [PadelHike](https://padelhike.ch/en/clubs/urban-padel-lausanne) | No current booking URL confirmed | Official domain is Coming Soon; access facts unknown | none identified |
| EHL Padel Club | `ehl-padel-club` to_verify | [PadelHike](https://padelhike.ch/en/clubs/ehl-padel-club) | No current booking URL confirmed | Campus eligibility, access, and booking facts unknown | none identified |
| Vaudoise aréna | `vaudoise-arena` confirmed | [Vaudoise aréna padel](https://vaudoisearena.ch/centres-sportifs/padel) | [Playtomic](https://playtomic.io/vaudoise-arena/53b5aaf2-7449-4691-96f8-a582ce37144b) | Published off-peak/peak prices are CHF 42/h and CHF 52/h; official page does not state the street address, lockers, membership, or account rule | none identified |
| Green Club | `green-club` to_verify | [PadelHike](https://padelhike.ch/en/clubs/green-club-romanel) | No current booking URL confirmed | Official page could not be fetched; access facts unknown | none identified |

## Matchpoint Booking Grid Verification

The public Matchpoint tenant was checked on `2026-09-26T00:00:00Z` without login or
reservation. The base Bernex URL is reused for multiple centers; the public center
selectors are `id=8` for Parc des Evaux and `id=9` for Jonction. `club=Evaux` and
`club=Jonction` do not select those centers and fall back to the default grid.

- [Parc des Evaux grid](https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=8) visibly labels `Parc des Evaux` and courts `Evaux 1`, `Evaux 2`, and `Evaux 3`.
- [Jonction grid](https://padelgeneva.matchpoint.com.es/Booking/Grid.aspx?id=9) visibly labels `Jonction` and courts `Jonction 1` and `Jonction 2`.
- The grid is public for availability viewing; this does not remove Evaux's separately evidenced account requirement for completing a reservation.

## Duplicate Decisions

- AIRPAD remains four separate records; the operator lists them as separate sites.
- `L'Asphalte / Pointe de la Jonction` remains one probable record. The current City page and regional directory identify the same site and both state two courts; the official page also supports both supplied names as aliases.
- `Padel REDSPORT-LANDAGORA / TC Fraisiers` remains one to-verify record; no alternate alias was retained because current operator identity was not confirmed, so its slash-separated candidate decision is unresolved.
- `Drizia-Miremont / Bout-du-Monde` remains one to-verify record; the supplied slash wording remains only in `canonical_name`, not `aliases`, because the checked directory confirms Drizia-Miremont but not Bout-du-Monde as a separate identity, so its candidate decision is unresolved.
- No candidate was merged merely because two venues use the same booking platform.
- Tennis Club Nyon was not added; it is outside the supplied 29-candidate set.

## Evidence Rules Applied

- Every non-unknown access, membership, public-booking, racket-rental, locker, account, court, cover, address, booking-platform, and URL field has a matching fact-specific evidence key. Published prices and durations are retained as supporting evidence where the checked source states them; they are not required for locations without schema fields for them.
- Mixed evidence was split into separate records. A directory court observation is never described as supported by an official page.
- The current City of Geneva page says L'Asphalte has two covered courts and public paid online reservation. No official one-court contradiction was fabricated because the checked official page does not say one.
- The current GVA Padel operator page says three seasonal courts; the regional two-court observation remains explicit contradictory evidence.
- Candidate-list access labels, prices, durations, aliases, and booking-window claims were not copied unless a checked public source supported them.
