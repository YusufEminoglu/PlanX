# Changelog

## [4.15.1] - 2026-09-19

Three tools reported areas and lengths in the layer's own coordinate units while documenting them as metres. Fixed here, with both error classes named, so the next one is checked rather than found. No algorithm added or removed, no parameter changed, no output column renamed - the values that move are the ones that were wrong.

### Fixed
- **`planx:seismicdebris` now reports ground metres.** The tool fed `QgsGeometry.area()` - the layer's own square units - straight into `seismic.debris_extent`, which documents its outputs as cubic metres and tonnes, and into `footprint_area`, which documents square metres. Two different things break that assumption, and they are not the same defect:
  - **The coordinate unit is not always the metre.** On EPSG:2229 - California zone 5, US survey feet - a square 100 units on a side is 929.041 m² of ground. The layer's own `area()` says 10000. A 10.76x figure, the square of the 3.28 foot factor.
  - **A conformal projection carries its own scale factor.** EPSG:3857 is a metre CRS, so its units look like metres, but they are metres on the sphere *at the equator*. At 41°N a 20-unit box is 227.835 m² of ground against 400 square units in the layer - 1.757x, `1/cos(41°)` squared. This is the 1.76x recorded as an open defect in 4.15.0, still in a metre CRS.
  Both scale a plausible number by a constant, which is why neither looks like an error in a result table.
- **`debris_vol_m3`, `debris_pile_m3` and `debris_mass_t` move with it**, being built from that area. The **radius does not**: it is driven by height alone, as the 4.15.0 note said. On the demo city - which sits at the EPSG:3857 origin, the one place on that grid where the scale is exactly 1 - every number is unchanged, which is also why the runtime matrix never saw this.
- **Street corridor widths are now metres too.** The debris envelopes buffered by half the debris width in layer units: on a foot layer a 5 m road was cleared by a 5-foot envelope. Same conversion for the reach along the street axis, the ROI hull and the morphological opening behind `OUT_NAVIGABLE`, where `MIN_CLEAR_WIDTH` is a metre threshold by definition.
- **`planx:streetmorphology` - the defect carried from 4.14.0, fixed in the same release.** `total_length_km`, `avg_segment_length_m` and `intersection_density_km2` divided raw network units by 1000 and raw hull units by 1e6. On a foot layer those figures were wrong by 3.28 and 10.8; on EPSG:3857 at 41°N they were wrong by 1.33 in length and 1.76 in area, on a metre layer that gave no sign of it.
- **`planx:seismicimpact` had the same defect in the same release it was written.** The occupant estimate reads the footprint from the geometry when the layer has no footprint column, which is exactly the fallback path, and that read was raw. The casualties and the shelter need inherited the area error the debris tool had just been fixed for.
- **New module `planx/algorithms/_units.py`.** `GroundUnits` binds a `QgsDistanceArea` to the layer's CRS and ellipsoid and exposes `area()` (m²), `length()` (m), `per_metre()` (layer units per ground metre, measured along the geometry where it has length) and `scale()` (layer units per ground metre at the centre of an extent). One mechanism covers both defects, because both are the same question: how long is a layer unit on the ground here. A CRS with no ellipsoid and a geographic CRS both raise rather than guess.

### Notes
- **The runtime matrix is structurally blind to this class, and still is.** Its fixture city is generated at `(0, 0)` in EPSG:3857 (`engine/demo.py`), where the projection's scale factor is exactly 1 - so 73 cases ran green over a defect that any real city would have shown. `tests/smoke_plugin.py` now carries the check the matrix cannot: a 20-unit box at 41°N on EPSG:3857 against `(20*cos 41°)²`, a 100-foot square at Los Angeles on EPSG:2229 against `(100*0.30480060960122)²` with its `per_metre` reciprocal, and a 1000 m square on EPSG:32635 that must stay near 1e6 rather than be corrected away. Each expectation is written out from the CRS definition, not read back from the module under test.
- **The same class is still live in about a dozen other tools** that write an `area_m2` or a `km2` column from raw geometry - `building_metrics`, `green_connectivity`, `landuse_balance`, `residential_capacity`, `spacematrix`, `tessellation`, `density_grid`, `growth_sim`, `landcover_change`, `sprawl_metrics`, `walkability` among them. They are not touched here: it is a wide pass that changes reported values in most of the plugin's analytical tools, and it deserves its own release rather than a footnote to this one.
- **A value check must not read its own output through QGIS, and the matrix now says so.** The new debris check first read `OUT_BUILDINGS` with a `QgsVectorLayer` and the case went red on both runtimes with `Creation of data source failed (OGR error: A file system object called '...gpkg' already exists.)` - because the matrix's extra runs re-create a destination the primary run already wrote, and on Windows an open QGIS datasource keeps the file from being replaced. Measured: with no prior read the re-create and the delete both succeed; after one read through QGIS both fail with `winerror 32` whether the layer wrapper is kept, `del`-ed, or `del`-ed plus `gc.collect()`. All three value checks now read their output with `sqlite3` (`_read_gpkg`), which holds no GDAL handle and reads the columns exactly as any other program would. The trap was latent in the two checks that already existed; it needed only an extra run on their output to fire.
- **New value check for the debris identity.** `debris_vol_m3` must equal `footprint_area × height_m × SOLID_VOLUME_RATIO × f(damage_state)` for every building, feature by feature - the identity the footprint column exists to make checkable, and the one that breaks first if the reported area and the area the volume was built from ever stop being the same number.
- **`tests/smoke_plugin.py` was hanging, and no longer is - and the cause is not the one the first reading suggested.** Run by hand it printed its verdict and then never returned; run under `pf verify` it finished normally. The difference is the QGIS profile, not the test: both runs hand `QgsApplication` a throwaway profile of their own, but only `pf verify` also sets `QGIS_CUSTOM_CONFIG_PATH` (TRAPS 4.6). Measured on 3.44 - the module as it stood printed `PASS` and exited 0 with that variable set, and printed the same `PASS` and then hung until killed without it - so the block is inside QGIS's own shutdown path, in the real user profile, and a profile folder passed to the constructor does not avoid it. It now exits through `os._exit` from the frame that still holds the application, as `qgis_runtime_algorithm_matrix.py` already did, which short-circuits teardown on either environment; the failure path exits 1 with its traceback and no hang, which is what `pf verify` reads. The teardown half of the hazard (`exitQgis` blocking once a provider is loaded) stays guarded the way the matrix guards it.

## [4.15.0] - 2026-09-19

Seismic Human Impact (`planx:seismicimpact`) is new. One algorithm added, one existing tool gained an output column, none removed. The Seismic Risk group now runs end to end: how hard the ground shakes, what that does to buildings and streets, and who is hurt when it does.

### Added
- **`planx:seismicimpact` - Seismic Human Impact (Casualties and Shelter).** The two existing seismic tools stop at physics. This one carries their result into the two Hazus models that end in people - Section 12 for casualties and Section 13 for displacement and shelter - and it reads the four damage-state probabilities (`prob_slight`, `prob_moderate`, `prob_extensive`, `prob_complete`) that Seismic Collapse and Debris Spread writes, so the chain runs without a file in between. Any layer carrying those four columns works too.
- **Casualties from the whole damage distribution, not from collapse alone.** Hazus's event tree is implemented as the manual writes it: every damage state contributes its own four injury rates, and only the Complete state splits, into complete-but-standing and collapsed, by the Table 12-8 probability of collapse given Complete. That split carries almost all of the deaths - for a C1L frame the collapsed branch's severity-4 rate is 10 per occupant against 0.01 for the intact branch - so a model without it would report Complete damage as nearly harmless.
- **Four severities, in Hazus's own order** - treatable injuries, injuries needing hospitalisation, life-threatening injuries, instant deaths (Table 12-1) - written out per building as `cas_sev1` to `cas_sev4` and summed into `cas_total`. People outside the building are counted separately on the manual's outdoor tables, which drop the slight-damage branch and do not split on collapse: falling parapets and glazing hurt people on the pavement whether or not the floors came down.
- **Who is in the building is a parameter, not an assumption.** Hazus Table 12-2 gives the indoor and outdoor share of every occupancy class at 2 a.m., 2 p.m. and 5 p.m., and those shares decide the outcome: a residential building is 98.9 percent occupied at 2 a.m. and 52.5 percent at 2 p.m., a school is empty at 2 a.m., and a hotel is a fifth full at 2 p.m. A night earthquake and a day one are two runs of this tool, and the help recommends both.
- **Occupants** come from a population field when the layer has one, or - when it does not - from footprint area times storeys divided by an area per occupant, 30 m² by default. That divisor is stated as the tool's own screening assumption rather than a Hazus figure, in the parameter description and in the run log, together with which of the two sources produced the count. A dwelling-units field drives the Section 13 equations when the layer has one; without it a residential building counts as one dwelling and a non-residential building as none, which is what a non-residential occupancy is.
- **The floor-area source reads the footprint from the geometry, or from a column when the buildings are points.** A point has no area, and the tool upstream of this one writes points, so the footprint is taken from a field when the geometry gives nothing - named by the new optional **Footprint area field** parameter, or found automatically in `footprint_area`, `area_m2`, `area`, `shape_area` so the debris-to-casualties chain runs with nothing to configure. With no footprint anywhere the run **stops** and says so: the floor-area estimate would be zero at every building, and a run reporting a city of nobody is exactly the answer this tool refuses to give quietly. When only some buildings lack one, it warns with the count instead.
- **Shelter** is Hazus Equations 13-1 to 13-5 with Table 13-1's single-family and multi-family weights: `displaced_hh` is the households that lose their home, and `public_shelter` is the people who will seek publicly provided shelter. The demographic filter is implemented in full, with Table 13-2's category weights and four modifiers that default to 1.0. That default is deliberate and is said wherever the number appears: at neutral the filter changes nothing, α is exactly 1.0, and the answer is an **upper bound** in which every displaced person seeks public shelter. Hazus's own Table 13-3 factors run from 0.13 to 0.62, so a real estimate sits well below the default.
- **No damage columns, no answer.** If the four probability columns are absent and no damage-state column is named, the tool raises with the reason rather than returning zeros, because a zero casualty count is indistinguishable from a good outcome. A single damage-state column is accepted as a fallback and the run log says that it discards the distribution. Neither `displaced_hh` nor `public_shelter` is an error case for a non-residential building - both are zero, which is what the equations give.
- **`planx:seismicdebris` now writes `footprint_area`** - the building's own `QgsGeometry.area()`, kept so the casualties tool can read a footprint back off its point output. It is not called `area_m2` because it is in the layer's area unit, not necessarily square metres. Placed next to `height_m`, which it pairs with; it carries no renderer token, so `collapse_prob` is still the field the default renderer colours by, and the field-order contract in that method's docstring and `tests/smoke_plugin.py` still holds.
- Output is one feature per building with its geometry and every input attribute preserved, so the layer joins straight back onto the damage and debris outputs, plus `occ_class`, `bldg_type` (the resolved Hazus type), `occupants`, the four severity counts, `cas_total`, `displaced_hh` and `public_shelter`. `RENDER_FIELD` is set to `cas_total` so the default renderer colours by it rather than by whichever numeric field the generic candidate list happened to match last.

### Changed
- `metadata.txt` is 4.15.0, with the description and the about text now describing three chained seismic tools and a 4.15.0 changelog block. No literal percent sign.
- The manual gained a nine-section card for the new tool - overview, theoretical background, ten numbered equations, input requirements, 22 parameters, outputs, symbolic representation, an eight-part interpretation guide and three references - plus its table-of-contents entry and a Seismic Risk group preface that now says three tools and describes what the new one closes. Counts are read off the built manual rather than estimated: 314 to 323 numbered display equations, 388 to 391 reference entries, 300 with DOIs, 72 to 73 algorithms in the four places the figure appears. The debris card's output row also gained `footprint_area` - and, in the same row, the four `prob_*` columns, which were added to that tool's schema for the casualty model in this release and had not been listed. A field list a reader takes as complete, and which is not, is a defect of a different kind from a wrong number - and it was the second one this pass turned up. The first was this file: 4.15.0 credited the new tool with 22 parameters when its manual table had 21 rows and `initAlgorithm` defined 21. The parameter added here makes the figure 22 and true, which is a coincidence, not a correction. Both counts were then re-derived by reading the parameter table and `initAlgorithm` against each other - 22 rows, 22 parameters, same order - rather than by trusting either figure.
- The README's tool table had **no seismic rows at all** - nor the two parking tools - so it listed 68 of the 73 algorithms while claiming 72. It now carries a Seismic Risk group with all three tools and the two parking tools under Travel Demand, and has exactly one row per algorithm. Its algorithm count, its "seventy-three tools" line and its engine-check figure (627 to 670, which is what the suite actually runs) are current.
- `docs/METHODS.md` gained a **Seismic Risk section, which it did not have**: the ground-motion functional form and site term, the fragility and debris equations, the casualty event tree and the shelter equations with their sources. The group was previously undocumented there even though the README points at that file for methods and sources. The two parking tools' methods were added to its Travel Demand section in the same pass.
- Both gate floors moved from 72 to 73 (`smoke_provider_catalog.py`, `qgis_runtime_algorithm_matrix.py`).
- `THIRD_PARTY_NOTICES.md` gained a Hazus casualty and shelter section alongside the existing fragility one, naming Sections 12 and 13, the figures and tables transcribed, and the two limits that are not FEMA's: the rates are applied to Turkish stock without calibration, and the neutral shelter modifiers are not Table 13-3.

### Notes
- These are **orders of magnitude, not counts**. The casualty rates were fitted to United States earthquakes and the shelter factors to United States Red Cross shelter data, and the damage distribution arrives with the uncalibrated-to-Turkish-stock caveat the debris tool already carries. The tool says so in its help, in the manual and in the run log.
- Bridges and the population on the street away from any building are left out rather than approximated: both need an inventory the plugin does not model - a bridge layer carrying damage states, and a count of people in the street. Hazus's bridge rows and its street-population parameters are therefore not implemented.
- `displaced_hh` and `public_shelter` answer different questions. Most displaced households go to family, friends or a hotel; only the fraction α that stays in the area seeks a public shelter, which is why the neutral default is an upper bound and not a forecast.
- **Three defects the runtime matrix caught, and the engine suite could not.** The first two were reported as the same `FAIL (72/73)` on both runtimes, and the first was hiding the second - so the count staying the same between runs was not evidence that nothing had moved. The third was hiding behind both, and behind a value check that could not see it.
  - **The tool failed on its own primary workflow.** Its first input is the four damage-state columns the debris tool writes, and those four columns are only the damaged states: the undamaged share of a building is their complement. The engine's event tree indexes the distribution by state, so reading those four as a distribution raised `KeyError: 'none'` - the tool failing on the one workflow it exists for, while 665 engine checks passed, because every one of them supplied all five states by hand. `engine/impact.py` now has `fill_undamaged`, which completes a four-state distribution with its complement (clipped at zero, so a row summing above 1.0 gets no undamaged share rather than a negative one, and the run log still reports those rows), and the tool calls it. Five checks were added for the new function, including one that the filled distribution reproduces the hand-derived C1L counts. It is the second release in a row where the matrix's chained run found what the unit suite could not.
  - **The chained run modelled a population of nobody and passed.** With the harness fixed the case ran, and the run log read `Population modelled: 0 people across 70 feature(s)` while the same run reported 17.7 displaced households - the tool's own "no silent zeros" rule, broken, with the value check green. The cause is the seam between two tools: `planx:seismicdebris` writes its buildings as **point centroids**, because the debris envelopes need a point to hang off, and a centroid has no area, so `QgsGeometry.area()` is 0.0 for every building and the floor-area occupant estimate multiplies out to zero everywhere. Casualties went to zero with it. Shelter did not, because a residential building with no dwelling-unit column counts as one dwelling and the displaced-household equation divides a default dwelling count by an occupant count it never needed - which is how a run with no people in it still produced a number, and how the loose end was spotted.
    - The fix is a footprint that survives the handover: `planx:seismicdebris` now writes `footprint_area`, and the casualties tool reads a footprint from a column when the geometry gives none, auto-detected or named. It **raises** when no building has a footprint at all rather than returning the zero-population answer.
    - The value check needed a floor as well as a ceiling. Every bound it asserted was an upper bound - casualties below occupants, shelter below occupants - and zero occupants satisfies all of them, so the defect was invisible to the check written to catch physical impossibilities. It now also requires the run to put somebody in a building. `planx:seismicimpact` is the only entry in `VALUE_EXPECTATIONS` with a chained case behind it, so this was also the only case in the matrix where a zero-population run was possible.
    - The run log now names the source: `Footprint area: 0 building(s) from their geometry, 70 from column 'footprint_area'`.
  - **The matrix's own resolver could not reach the tool's other two input paths.** With the first fixed, the next run failed in 0.10 s before the tool started: `KeyError: 'buildings_occupancy'`. The harness resolves a `fixture:` token against the file dictionary, which holds only the GTFS zip; the occupancy fixture is a layer and lives in the layer dictionary. Every `fixture:` token in the file until this release named that one zip, so the branch had never had to look elsewhere. The two coverage cases added here - a population field against an occupancy field, and a single damage-state column - were the first to name a layer, and had therefore never executed once. `_resolve_special` now looks in both dictionaries and raises naming what it does hold.
- The engine suite stands at 670 checks, including the Section 12 rate tables, the collapse split, the Table 12-2 occupancy shares, the Section 13 weights and the identities that α is exactly 1.0 at neutral modifiers and that a non-residential building contributes no shelter need.
- **Still open, found while fixing the above.** `planx:seismicdebris` feeds `QgsGeometry.area()` - the layer's own area unit - straight into `seismic.debris_extent`, which documents its outputs as cubic metres and tonnes. On a metre grid the two agree; on a layer projected in feet, or one still in degrees, `debris_vol_m3`, `debris_pile_m3` and `debris_mass_t` are inflated by the square of the unit factor. It is the same class as the `streetmorphology` defect below: a unit assumption that holds for the demo city and is never checked. The radius is unaffected, being driven by height alone. Not fixed here - it changes reported values, and the same release should carry both. The constraint is now stated on `debris_extent` itself, and on the new `footprint_area` column, so the next reader meets it at the boundary rather than in a bug report. **Fixed in 4.15.1**, which also names the two error classes separately - the projection's own scale factor is the one that bit here, on a metre CRS.
- **Still open, carried from 4.14.0.** `planx:streetmorphology` divides raw network length by 1000 and hull area by 1e6 to report `total_length_km` and `intersection_density_km2`, so on a layer projected in feet those two figures are wrong by 3.28 and 10.8. It remains a different tool's defect and belongs in a release that changes reported values and says so. **Fixed in 4.15.1**, in the release that changed reported values and said so.

## [4.14.0] - 2026-09-19

Ground Motion Scenario (`planx:groundmotion`) is new. One algorithm added; none changed, none removed. The seismic group now holds a chain rather than a single tool: ground motion in, debris out.

### Added
- **`planx:groundmotion` - Ground Motion Scenario.** Seismic Debris could always be driven by a joined PGA field, but nothing in the plugin produced one: the only ways in were a ShakeMap or an AFAD raster from outside QGIS, or the debris tool's own magnitude guess, which has no distance, site or fault term. This tool computes the shaking itself, from Akkar, Sandikkaya & Bommer (2014) - one of the four ground-motion models in the logic tree of Turkey's 2018 national seismic hazard map - with the authors' own published coefficients.
- **`SCENARIO`** - A, a point source (an epicentre plus a focal depth), or B, an extended rupture (a fault trace). An extended rupture has no single hypocentre, so geometry B offers Joyner-Boore distance only; a point source has no rupture surface, so its Joyner-Boore and epicentral distances are the same number. The tool raises with the reason rather than inventing the distance it cannot support.
- **`DISTANCE_METRIC`** - Joyner-Boore, epicentral or hypocentral. The choice is written to every output row as `dist_metric` and the distance itself as `r_km`, so a result joined back onto a map can never be read as the wrong distance.
- **`FAULT_MECHANISM`** - strike-slip (the model's reference), normal, reverse. **`EPSILON`** shifts every value by a chosen number of total standard deviations, which is how a scenario is pinned to a rarer level than the median.
- **`VS30`** and **`VS30_FIELD`** - site velocity as a constant or per receiver. The default is 750 m/s, the model's own reference velocity where its site term is exactly zero, so a default run reports rock-reference motion and every bit of soil amplification in a result is a choice the user made. The value actually used is written to a `vs30` column; a receiver whose field is empty falls back to the constant and is flagged in `caveat` instead of quietly becoming rock.
- **`SPECTRAL_PERIODS`** - any periods the model tabulates, in seconds, added to the output as `sa_<T>_g` columns. It does not interpolate: a period the paper does not publish is refused, with the nearest tabulated periods named in the error. An interpolated value would be one no source supports.
- Output is the receiver layer returned with its own geometry and attributes plus `pga_g`, `pgv_cms`, `sa_<T>_g`, `r_km`, `dist_metric`, `vs30`, `pga_rock_g` (the rock PGA the site term is conditioned on, so the amplification applied to each receiver is auditable), `sigma_pga` and `caveat`.
- **`caveat`** names the applicability limits each row breaks - `mag_below`, `mag_above`, `dist_above`, `vs30_below`, `vs30_above`, `depth_above`, `vs30_missing`, `vs30_capped` - and the run log repeats them as warnings. The number is still computed and still written; the point is that it is labelled rather than silently extrapolated, and the paper's own magnitude, distance, depth and site ranges are the ones the flags use.

### Changed
- Distances are converted from the receivers' own CRS units into kilometres. Every term of the model is in kilometres - the distance, the focal depth, the `a6` site-scale constant added to `R²` - and the receiver coordinates arrive in whatever the layer's projection uses. Assuming metres is right for UTM and wrong by 3.28 for a state-plane CRS, and a factor of 1000 is wrong enough to read the demo city's 750-metre span as 472 km, which is what an early build of this tool did: the matrix case reported receivers up to 472 km away from an epicentre 500 m from most of them, and stayed green because a wrong number is still a number. The scale is now read off the CRS, and the engine's distance functions take it as a required argument with no default, so the mistake cannot be made silently again.
- A fault trace is reprojected into the receivers' CRS before distances are measured. It previously kept its own layer's coordinates, so a trace in a different projection - or one in feet - produced distances mixed from two unit systems.
- The Seismic Risk group's manual section no longer describes a single tool, and the debris card's ground-motion paragraph now points at this tool as the in-plugin route to a PGA field.
- Manual counts are now 314 numbered display equations, 388 reference entries, 298 with DOIs; the version literal, the README and the metadata are current. 72 algorithms, 19 groups.
- The pure engine suite gained 33 checks for the ground-motion engine and stands at 627, including a committed fixture of pyGMM's own expected outputs that pins the functional form, the site term and the row indexing, and checks that state the unit contract in metre-scale coordinates - synthetic coordinates small enough to pass as either unit are how the 1000× error survived the suite. See `THIRD_PARTY_NOTICES.md`, which is new and covers the ASB2014 coefficients, the pyGMM test values and the Hazus fragility curves.
- `tests/smoke_provider_catalog.py` counted reference entries carrying a DOI by counting `doi.org` *occurrences*, so one listing with two DOIs paid for one listing with none and the README's "with DOIs" figure read one higher than the manual supports. It now counts entries, and the README states 298.

### Notes
- The model has no raster output and no raster site sampling. QGIS's own *Create grid* into the receivers parameter gives a scenario grid, and it keeps each run's inputs visible in the model designer; a hidden raster path would have been a second, less inspectable way to ask the same question.
- `tests/qgis_runtime_algorithm_matrix.py` now checks values, not only presence, for tools where a silent unit error is the plausible failure. It previously asked one question of every output - was anything produced? - which no unit bug can ever fail. The ground-motion case asserts that the demo city's receiver distances are consistent with a city under a kilometre across, and fails the case if they are not.
- **Known follow-up, not fixed here.** `planx:streetmorphology` divides raw network length by 1000 and hull area by 1e6 to report `total_length_km` and `intersection_density_km2`, so on a layer projected in feet those two figures are wrong by 3.28 and 10.8. It is the same class of defect as the one this release fixed in the ground-motion tool, but it is a different tool, and correcting it changes reported values, so it belongs in a release that says so.
- These are median values from a shallow-crustal model for Europe and the Middle East: not design levels, not a code check, and not a substitute for the national hazard map. The model carries no basin term and no directivity, so deep soft-soil amplification and forward-directivity pulses are not represented.

## [4.13.0] - 2026-09-19

Seismic Collapse and Debris Spread (`planx:seismicdebris`) rebuilt on the Hazus fragility curves. One algorithm changed; none added, none removed. All five previous outputs keep their meaning, three new parameters are additive and the defaults reproduce the old single-realisation workflow.

### Fixed
- **The collapse probability saturated.** The model scaled a construction-year baseline by `exp(0.8 (Mw - 7.0))` and clipped at 1.0, so the pre-1985 stock hit certainty at roughly Mw 7.2 and the 1986-2000 stock at Mw 7.8 - the band a Marmara scenario occupies. The tool reported `collapse_prob = 1.0` for the entire oldest tier and carried no information about it. Probabilities now rise smoothly and separately with magnitude, from a lognormal fragility rather than an exponential clip.
- **Debris came only from total collapse.** A building left standing while losing its facade, infill walls and parapets put nothing in the street, which under-counted the most common form of post-earthquake obstruction. Debris is now generated from the sampled damage state through a released-material fraction (0 for none and slight, 0.10 moderate, 0.35 extensive, 1.00 complete), so partial damage contributes to blockage.
- **Source A accepted a non-polygonal layer and returned a zero-area network.** Everything downstream - blockage, corridors, navigable core - is areal, so the run looked successful and meant nothing. It now raises with the message naming sources B and C.

### Added
- **`PGA_FIELD`** (optional, recommended) - a peak-ground-acceleration column in g on the buildings layer. Supplying it drives fragility from real site shaking and bypasses the magnitude path entirely, which is the only route with distance and site effects; buildings with a null or non-positive value fall back to the nominal intensity and the log counts them.
- **`BUILDING_TYPE`** - 13 Hazus structural types (C1, C2, S1, S2, S3, S4, W1, W2, RM1, RM2, PC1, PC2, MH). The height class is appended from the floor-count field, so C1 with five storeys reads the `C1M` row. Three Hazus types are deliberately absent: C3, S5 and URM have no Moderate- or High-Code curve in the manual, and a row invented to fill the gap would be worse than the absence. The help text says what that costs.
- **`REFERENCE_PGA`** - the nominal site PGA at Mw 7.0 (default 0.35 g) used only when no PGA field is given. Exposed rather than buried, because it is a user assumption, not a physical constant.
- **`VOID_RATIO`** (default 0.35) and **`DEBRIS_DENSITY`** (default 1.8 t/m3) - the pile's air fraction and the material density. `debris_vol_m3` keeps its meaning as solid material volume; the two new columns are `debris_pile_m3` (bulked, what competes with the street for space) and `debris_mass_t` (tonnage to haul).
- **`MIN_CLEAR_WIDTH`** (default 3.5 m) and the **`OUT_NAVIGABLE`** output - the corridor network morphologically opened at the clear width, so a sliver of pavement beside a debris pile stops counting as an evacuation route. Unblocked is not the same as passable, and the corridors layer alone over-stated the evacuation map invisibly. The log reports the street area lost to pinching.
- **`SIMULATIONS`** (default 0) - reruns the scenario under N seeds and writes an empirical `collapse_freq` per building plus mean, standard deviation and 5th/50th/95th percentiles of blocked street area. This replaces the manual's advice to repeat the tool by hand with one parameter. `collapse_freq` is NULL when the parameter is left at 0.

### Changed
- Damage state and `collapse_prob` now come from the Hazus equivalent-PGA structural fragilities (Technical Manual 6.1, Tables 5-37 to 5-40: High-, Moderate-, Low- and Pre-Code), with the manual's uniform dispersion of 0.64 - the root-sum-of-squares of its capacity (0.4) and demand (0.5) dispersions. The medians were transcribed from the published manual, not recalled, and the embedded table was verified row for row against a parse of the source PDF.
- The four construction-year tiers keep their breakpoints but are now *Hazus design levels* rather than probabilities: 1985 and earlier Pre-Code, 1986-2000 Low-Code, 2001-2018 Moderate-Code, newer High-Code. This is an analogy to Turkish regulation years, not a calibration, and the engine, the manual and the reference list all say so.
- `collapse_prob` is still the last preferred-token numeric field, so the default graduated renderer still colours the map by it. `tests/smoke_plugin.py` now asserts that against the algorithm's own field list rather than a copied one, because adding `debris_pile_m3`, `debris_mass_t`, `collapse_freq` and `damage_state` moved that choice and nothing else in the suite would have noticed.
- Manual card rewritten to the new chain: 12 display equations, the design-level and released-material tables, the navigable-core definition, and a validation table of the C1M damage distribution by design level. Manual counts are now 305 numbered display equations, 386 reference entries, 298 with DOIs; the README, the version literal and the changelog are current.
- The runtime matrix now covers the seismic tool through the centerline network sources it can actually express. It previously bound the demo city's line layer to source A, a polygon input, so blockage, corridors and the navigable core all had zero area while the case read green.

### Notes
- The engine suite stands at 596 checks. `tests/qgis_runtime_algorithm_matrix.py` gained extra-run verification: an extra run whose output is empty now fails the case instead of counting as coverage.
- The Hazus curves are American: a western-United States reference spectrum (Mw 7.0, Site Class D, distance at least 15 km) and design levels tied to United States code eras. Turkish building stock, and especially its unreinforced masonry and infilled frames, is not represented by the available type list. Treat the output as comparative screening and do not quote it as a Turkish loss estimate. Calibrating these curves to Turkish damage observations is a separate piece of work and is not done here.
- The same constants still live in `planx_urban_resilience`'s `processing/seismic/monte_carlo_debris.py`. The two plugins are separate repositories, so the engine change cannot be shared; that copy will drift from this one unless it is ported in its own release.

## [4.12.0] - 2026-09-19

Parking demand and supply balance. Two new algorithms, both in the Travel Demand group. Purely additive: no existing algorithm's parameters, ids or default behaviour changed.

### Added
- **Parking Demand Estimator** (`planx:parkingdemand`) - estimates the parking spaces each zone demands from its land-use category and size, through an editable per-category rate table. Each entry is `category=basis:rate`, where the basis (`unit`, `sqm`, `seat`) states what one rate unit counts against, because parking standards are not written on one common denominator. A zone whose category matches no rate row demands zero and is listed separately in the log, so a gap in the rate table is never reported as a zone that needs no parking. The shipped rates are illustrative values written in the ITE convention, not figures taken from it, and the help text says so.
- **Parking Supply-Demand Balance** (`planx:parkingsupplybalance`) - compares the demand each zone carries against a counted parking inventory within an access radius, and reports the surplus or deficit. Reach follows the street network when one is supplied and is straight-line otherwise, and the output records which was used. Every zone is classified `counted`, `zero supply found` (a real deficit) or `supply data absent` (a coverage gap in the inventory), and the unsurveyed case gets a NULL balance so the column cannot be summed into a false shortfall.

### Changed
- The manual documents both new tools to the same depth as the rest, and its counts, version literal and search index are current: 71 algorithms, 19 tool groups, 300 numbered display equations, 386 reference entries.
- README and Studio dock counts updated to 71. The engine suite stands at 570 checks.

### Notes
- Mixed-use and shared-parking reduction factors are deliberately not implemented. The demand tool reports the sum of the single-use requirements, which is the quantity any shared-parking argument has to answer.

## [4.11.2] - 2026-09-19

Quality infrastructure. No algorithm behaviour changed and no algorithm was added.

### Fixed
- The Help button was dead for all 69 algorithms. `DOC_BASE_URL` still named the retired GitHub Pages host, so every Help link and both Studio dock documentation actions opened a 404 while `metadata.txt` advertised the live host. The URL is now defined once and imported by the dock.
- `tests/test_engine.py` (528 checks, no QGIS imports) was filed under `tests_qgis` with `tests_pure = []`, so no CI-reachable runner executed it. It is now filed as a pure suite.
- The manual advertised a stale version and eight stale Processing IDs (`planx:buildingformmetrics`, `planx:morphologicaltessellation`, `planx:spacematrixdensity`, `planx:streetnetworkmorphology`, `planx:multiamentiyaccess`, `planx:frontalareaindex`, `planx:noisescreening`, `planx:airscreening`), so documented IDs did not match the registry.
- The README claimed counts nothing checked: it said 285 display equations against the manual's 289, and an undefined "~600 citations". Both are now counted and true.

### Added
- `tests/smoke_provider_catalog.py`: 15 pure catalog gates tying the algorithm registry to the manual (anchors one-to-one in both directions, the 19 groups as an exact set, stable ids, one icon per algorithm, version literals, help host versus `metadata.txt` homepage).
- `tests/qgis_runtime_algorithm_matrix.py`: builds a fixture city, auto-wires each algorithm's declared parameters, executes all 69 on QGIS 3.44 LTR and 4.2, and verifies that every declared output is actually populated. Reports the wiring chosen and the algorithm's own log per case.

## [4.11.1] - 2026-09-17

- Upgraded official plugin icon to high-end tactile 3D brand identity (isometric 45°, slim teal pedestal, full bleed transparent canvas).
- Synchronized documentation, repository and issue tracker endpoints to GeoPhilo and GitLab.
- Fixed field preservation and fid handling in network preparation and service areas algorithms.

## [4.11.0] - 2026-09-05

### Added
- Analysis provenance manifests and deterministic fingerprints on generated layers; Scenario Snapshot now carries the lineage of its source analyses.
- Searchable PlanX Studio with favorites, recent tools, active-layer filtering, presets, and six guided multi-tool workflows.
- Directed/asymmetric routing, network snapping controls, component diagnostics, and prepared-network node identifiers.
- Multi-threshold and distance-decay accessibility measures, including gravity access and cumulative reach counts.
- Enhanced two-step floating catchment accessibility in Facility Adequacy.
- Monte Carlo weight sensitivity for Scenario Ranking with mean rank, rank deviation, and probability of ranking first.
- Exact small-instance optimality audits for facility location heuristics.
- Walking transfers, minimum transfer times, and departure-window P50/P90 reliability for GTFS accessibility.
- Optional observed-share validation diagnostics for Mode Split and optional EPW calibration for Annual Solar Potential.
- Provider-wide QGIS smoke coverage and focused regression tests for the new engine capabilities.

### Changed
- Every network-consuming algorithm honors `dir_code`; tools that accept generalized costs also auto-detect `cost_fwd` and `cost_rev` from Prepare Network, while metric walking tools retain physical length.
- Generated vector results receive readable aliases and a default graduated renderer when an analytical score field is present.

## [4.10.6] - 2026-08-09

- Open PlanX Studio from the single toolbar icon and remove the separate `Plugins > PlanX` menu entry.
- Move the Plan Dashboard workflow into the `Plan Dashboard & Performance Report (HTML)` Processing tool instead of a separate dashboard dock.

## [4.10.5] - 2026-08-07

- Added online user manual link (https://yusufeminoglu.github.io/PlanX/) and GitHub repository star call-to-action.

## [4.10.4] - 2026-08-07

- 3-5x content depth expansion: 14.7K lines, ~600 refs, 285 equations, MathJax, icons, group colors, per-algorithm helpUrl, GitHub Pages

## [4.10.3] - 2026-08-07

- MathJax equations, per-algorithm icons in sidebar, group color coding, Studio Dock documentation button, per-algorithm helpUrl, GitHub Pages with redirect

## [4.10.2] - 2026-08-07

- Add comprehensive 69-algorithm academic reference manual (standalone HTML with KaTeX equations, DOI-verified references, appendices)

All notable changes to PlanX are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [4.10.1] - 2026-07-15

QGIS 4 / Qt6 readiness and a fully clean security scan. No functional change.

### Changed
- **Scoped every Processing and geometry enum** (`QgsProcessing.SourceType.*`, `QgsProcessingParameterNumber.Type.*`, `QgsProcessingParameterField.DataType.*`, `QgsWkbTypes.Type.*` / `.GeometryType.*`, `QgsFeatureSink.Flag.*`, `QgsProcessingParameterDefinition.Flag.*`, `QgsProcessingParameterFile.Behavior.*`, `QgsVectorDataProvider.Capability.*`) across all algorithms so the QGIS Hub Qt6 compatibility check reports zero issues. These resolve and run identically on QGIS 3.28+ (Qt5) and QGIS 4.x (Qt6); minimum QGIS is now **3.28**.
- **Fully "Validated" security scan**: the betweenness source-sampling `random` call (Bandit B311) is replaced by a self-contained seeded generator and the `.bandit` config was removed, so the Hub scan passes with no developer-supplied suppressions. Sampling stays deterministic per seed.

## [4.10.0] - 2026-07-15

Network resilience: Link Criticality tool.

### Added
- **Link Criticality (Network Robustness) algorithm** (`planx:linkcriticality` / `algorithms/alg_link_criticality.py`): ranks every street segment by how badly the network would suffer if it were lost - the road-network vulnerability view (Network Robustness Index; Scott et al. 2006 / Jenelius et al. 2006). Over a supplied origin-destination demand (or all pairs among the origins), it routes the intact network, removes each segment in turn and re-routes, and reports the extra travel cost forced (`criticality` as a fraction of baseline, `extra_cost` in absolute units), the demand it severs (`n_disconnected`) and how many shortest paths run over it (`used_by`); only segments carrying a shortest path are re-tested. Outputs a per-segment criticality map to style for a network-vulnerability picture.
- **Network robustness engine** (`engine/robustness.py`): pure NumPy on the embedded predecessor-tracking Dijkstra; edge-removal is a CSR mask so no external routing plugin or graph rebuild is needed.
- **New tool icon**: `tool_linkcriticality.png`.

### Improved
- OD Routes, OD Cost Matrix and Nearest Facility Allocation help now spells out the cost-field contract: the router minimises the SUM of the chosen network-layer column, so it must be an additive per-segment quantity (a time or weighted length, never a speed - conversion formula included); net_cost, CUTOFF and k-nearest inherit the column's units; NULL costs read as 0 (free segments) and values must be non-negative; Walking Slope Comfort's time_fwd_min is the ready-made slope-aware cost; the detour ratio is a pure ratio only under the default length cost.

## [4.9.0] - 2026-07-11

Network Routing UX & Walking Comfort additions.

### Added
- **OD Routes (Shortest Paths) algorithm** (`planx:odroutes` / `algorithms/alg_od_routes.py`): computes network shortest paths between origins and destinations, supporting `K_NEAREST` filtering, cost limits (`CUTOFF`), real street route paths (`OUT_ROUTES`), and straight desire lines (`OUT_LINES`).
- **Walking Slope Comfort algorithm** (`planx:walkingslope` / `algorithms/alg_walking_slope.py`): profiles street segments against a DEM, interpolating elevation samples along the geometry, and calculates length-weighted grades, climb/descent, Tobler forward/reverse speeds and travel times, and slope comfort classes.
- **Street Environment Comfort algorithm** (`planx:streetcomfort` / `algorithms/alg_street_comfort.py`): scores streets 0-100 based on positive assets and negative barriers point layers using spatial index search and distance kernel weights (uniform, triangular, epanechnikov, gaussian) plus raster factors, combined into a weighted comfort index.
- **Prepare Network option `TARGET_CRS`** (`alg_prepare_network.py`): reprojects geometries to a target CRS while keeping length measurements in source-CRS meters.
- **Prepare Network option `CREATE_INDEX`** (`alg_prepare_network.py`): creates a spatial index on the output layer.
- **Nearest Facility route geometry output `ROUTES`** (`alg_nearest_facility.py`): outputs travel path geometries for allocated demand using Dijkstra predecessor tree tracking.
- **Dijkstra predecessor tracking `multi_source_tree` & `path_to_root`** (`engine/paths.py`): tracks predecessors to reconstruct shortest path routes.
- **Walking comfort engine** (`engine/comfort.py`): pure numpy math for Tobler speeds, profile times, grades, kernel weights, segment density, and multi-component index combining.
- **Three new tool icons**: `tool_odroutes.png`, `tool_walkingslope.png`, `tool_streetcomfort.png`.

### Tested
- 503 engine unit checks (46 new checks for predecessor tracking, Tobler speeds, grades, kernel weights, and comfort combining), passing on both QGIS runners.
- 448 real-QGIS e2e assertions on QGIS 3 LTR and QGIS 4, 0 failures on each (new blocks verify preparenetwork CRS and index, nearestfacility routes, odroutes vs odmatrix cost equality, walkingslope, and streetcomfort).
- 26 dashboard check assertions on both QGIS runners.
- Import check: 68 algorithms in 19 groups register cleanly on QGIS 3 LTR and QGIS 4.

## [4.8.0] - 2026-07-11

Weighted composite scenario ranking, Processing ranking algorithm, HTML ranking board, and dashboard rank button.

### Added
- **Weighted multi-scenario ranking** (`engine/scenario.py`): ranks any number of scenario snapshots into a composite score based on direction-aware, weighted min-max normalisation, with tie-breaks and skipped-metrics (neutral, not-shared, constant) tracking.
- **Processing algorithm `planx:scenariorank`** (`algorithms/alg_scenario_rank.py`): collects snapshots from files and/or folders, parses weights (supporting `;` and `,`), handles error paths, and outputs a composite ranking table and a detail metrics table.
- **Scenario Ranking Board (HTML)** (`engine/report.py`): self-contained HTML page with a scoreboard, metrics heatmap, and skipped-metrics footnotes using inline styles and the theme color ramp.
- **Dashboard Rank button** (`dashboard_dock.py`): QPushButton next to the Auditor button to launch the ranking algorithm dialog from the dock.
- **New tool icon `tool_scenariorank.png`**: podium bars and a star glyph, generated from the script.

### Tested
- 457 engine unit checks (32 new checks for scenario ranking, weight parsing, and error validation).
- 384 real-QGIS e2e assertions on QGIS 3 LTR and QGIS 4 (verifying the scenariorank algorithm with files, folders, weights, HTML output, and error conditions).
- 26 dashboard check assertions on both QGIS runners.
- Import checks and zip audit structures validated.

## [4.7.0] - 2026-07-11

Service Areas rebuilt as exact isochrones with pedshed analysis; every tool's help now teaches how to interpret its results.

### Changed
- **Service Areas (Isochrones) rebuilt** - the old implementation kept or dropped WHOLE street segments (an edge with one endpoint under the break was included entirely, overshooting by up to a full block) and offered only buffer polygons. Reach is now computed exactly: streets are trimmed at the precise point where the cost budget runs out, including meet-in-the-middle coverage from both ends and mid-edge facility entries. Facilities enter the network at the nearest point of the nearest street (not the nearest junction), and with length costs the straight-line approach distance is deducted from the budget.
- **Every algorithm's help (64/64) now ends with a "How to read the results" section**: per-field meaning in planning terms, reference values where the literature has them (NACH benchmarks, LTS audiences, pedshed and LCRPGR ranges, dB(A) and headway thresholds...), and practical next steps. Existing descriptions kept verbatim.

### Added
- Service Areas: **polygon methods** - street buffer (hugs the trimmed network), concave hull (isochrone blob, detail parameter, convex fallback on older GEOS) and convex hull; **per-facility catchments** (optional facility label field) alongside the merged nearest-facility scope; **rings mode** (band differences) for clean cartography.
- Service Areas: **straight-line catchment circles** per facility and break - the regulation "desired reach" radius (e.g. a 500 m school catchment) drawn next to the real network catchment.
- Service Areas: **catchment summary table with the pedshed ratio** (network catchment area / circle area), circle and network areas, and the trimmed reached street length per scope and break.
- Reached-street output now carries facility, band, cost_from and len_m per trimmed piece - pieces are split at the break boundaries for exact band styling.
- New pure-NumPy `engine/isochrone.py`: vectorized partial-edge reach fractions, interval algebra (merge/subtract/length), polyline cutting by arc-length fraction and mid-edge entry budgets - all hand-fixture unit-tested.

### Fixed
- README test counts were stale (387 unit / 317 e2e); now 425 / 363 and released numbers will track the suites.

### Tested
- 425 engine unit checks (19 new isochrone fixtures: trimming, meet-in-the-middle, interval algebra, polyline cuts, entry budgets) and 363 real-QGIS e2e assertions on QGIS 3 LTR and QGIS 4, including hand-derived exactness: 1000/3400 m trimmed street length on the grid fixture, an 80,000 m2 convex-hull diamond with pedshed = 2/pi on a cross network, and a 60 m entry piece after a 10 m snap. Dashboard harness 24/24 on both QGIS.

## [4.6.1] - 2026-07-10

Seismic debris tool: four road / open-space network sources - the network input no longer requires manual digitizing.

### Added
- **Four network sources** for Seismic Collapse and Debris Spread ("Network source" selector, parameters labelled A-D): (A) street/open-space polygons used as-is; (B) OSM highway centerlines buffered by class-typical urban widths (motorway/trunk 25 m ... path 3 m, `_link` ramps inherit the parent class, `width` values override per feature, the `highway` field is auto-detected); (C) any centerlines buffered by a road-width attribute (lenient parsing: `6.5`, `6,5`, `'6.5 m'` all work, fallback width for gaps - the Demo City streets plug straight in); (D) region of interest minus dissolved blocks/parcels (cadastral parcels dissolve into blocks internally; without an ROI, the convex hull of the blocks expanded by the fallback width is used). Wrong mode/layer combinations fail fast with an actionable message.
- Street-width helpers in `engine.seismic` (`highway_width_m`, `parse_width_m`) - pure NumPy, unit-tested.

### Fixed
- Network inputs in a different CRS are now reprojected to the buildings CRS (mixed-CRS inputs previously produced misaligned blockage), and the buildings layer requires a projected CRS, since debris radii and street widths are metric.
- README algorithm count corrected to sixty-four.

### Tested
- 406 engine unit checks and 347 real-QGIS e2e assertions on QGIS 3 LTR and QGIS 4 (all four network sources exercised end-to-end, including exact blockage-area checks and wrong-mode error paths).

## [4.6.0] - 2026-07-10

Seismic Risk: Monte Carlo building-collapse and debris-spread screening (64 algorithms, 19 groups).

### Added
- **Seismic Collapse and Debris Spread** (new Seismic Risk group) - screening-quality Monte Carlo model for earthquake-induced building collapse: per-building collapse probability from construction year and event moment magnitude (Mw), a seeded random draw so a scenario is exactly reproducible (or re-rollable by changing the seed), debris spread radius and volume for collapsed buildings, the resulting network blockage, and the remaining open evacuation corridors.
- Pure-NumPy `engine.seismic` module (`base_probability`, `magnitude_factor`, `collapse_probability`, `simulate_collapse`, `debris_extent`) - vectorized and unit-testable without a QGIS session.

### Fixed
- **Generate Demo City**: green-space blocks no longer receive building footprints (the block-fill loop placed a 2x2 grid of buildings in every block regardless of land use). Buildings, DSM and demand-point counts adjusted accordingly.

### Tested
- 397 engine unit checks and 324 real-QGIS e2e assertions on QGIS 3 LTR and QGIS 4.

## [4.5.0] - 2026-07-10

LUTI-lite Scenario Pipeline: growth, allocation and evaluation chained (63 algorithms, 18 groups).

### Added
- **Allocate Population Growth** (Population and Housing group) - distributes a population growth increment over parcels or zones with deterministic largest-remainder (Hare-Niemeyer) apportionment, weighted by capacity, a custom field, or uniformly.
- **Scenario Pipeline (LUTI-lite)** (Reporting group) - one run chains the cellular-automaton growth simulation, apportions the population growth onto the newly converted cells proportional to suitability, rebuilds the grown city's demand points, and re-evaluates 15-minute accessibility and walkability into a scenario snapshot JSON plus a metric table.
- Pure-NumPy `population.allocate_growth` (sums exactly to the total, deterministic tie-break).

### Tested
- 387 engine unit checks and 317 real-QGIS e2e assertions on QGIS 3 LTR and QGIS 4.

## [4.4.0] - 2026-07-10

Travel Demand: trip generation, gravity distribution, and mode split modeling (61 algorithms, 18 groups).

### Added
- **Trip Generation** (new Travel Demand group) - calculates zone production and attraction trip rates from population and jobs.
- **Gravity Distribution** (Travel Demand group) - computes doubly constrained zone-to-zone flow balancing (Furness/IPF) with exponential or power deterrence over street network costs.
- **Mode Split** (Travel Demand group) - splits OD flows into multiple mode shares and flows using a multinomial logit model.
- Pure-NumPy `engine/demand.py` with trip generation, Furness gravity balancing, and logit mode split calculations.

### Tested
- 384 engine unit checks and 310 real-QGIS e2e assertions on QGIS 3 LTR and QGIS 4.

## [4.3.0] - 2026-07-10

Hazard Screening: flow accumulation, HAND, and flood exposure mapping (58 algorithms, 17 groups).

### Added
- **Flow Accumulation** (new Hazard Screening group) - fills DEM depressions, computes D8 flow directions, and calculates topological flow accumulation.
- **HAND and Inundation** (Hazard Screening group) - calculates Height Above Nearest Drainage by tracing D8 paths, and generates a binary inundation mask.
- **Flood Exposure** (Hazard Screening group) - intersects the inundation mask with building footprint centroids and population points to calculate exposed counts and percentage shares, and annotates receiver features.
- Pure-NumPy `engine/hydro.py` with priority-flood filling, D8 steepest-descent direction, topological flow accumulation, HAND, inundation, and building/population exposure calculations.

### Tested
- 378 engine unit checks and 300 real-QGIS e2e assertions on QGIS 3 LTR and QGIS 4.

## [4.2.0] - 2026-07-10

Air Quality Screening: road emissions calculation and air dispersion modeling (55 algorithms, 16 groups).

### Added
- **Road Emissions** (Microclimate group) - calculates segment emissions (g/km/day) from a traffic volume field and a documented generic NOx-proxy emission factor.
- **Air Quality Screening** (Microclimate group) - generates a unitless pollution dispersion index grid and calculates receiver levels and exposure bands, accounting for wind speed, decay exponent alpha, and street canyon effects.
- Pure-NumPy `engine/air.py` with emissions, sample strength, concentration, canyon factor, and exposure bands.

### Tested
- 372 engine unit checks and 294 real-QGIS e2e assertions on QGIS 3 LTR and QGIS 4.

## [4.1.0] - 2026-07-10

Cycling and LTS: cycling stress classification and low-stress connectivity (53 algorithms, 16 groups).

### Added
- **Cycling Stress (LTS)** (new Cycling group) - classifies street segments into LTS 1-4 from speed, lanes, AADT and cycling infrastructure fields, with editable threshold rules and a length-share table.
- **Low-Stress Connectivity** (Cycling group) - filters the network by an LTS threshold, labels connected cycling islands, reports low-stress network length share and optional destination-reach population.
- Pure-NumPy `engine/cycling.py` with threshold parsing, vectorized LTS classification and LTS-filtered primal graph components.

### Tested
- 367 engine unit checks and 288 real-QGIS e2e assertions on QGIS 3 LTR and QGIS 4.

## [4.0.0] - 2026-07-09

Demo City & Speed: synthetic city generator and hot-loop vectorisation (51 algorithms).

### Added
- **Generate Demo City** (Reporting group) — deterministic synthetic town generator: streets, buildings, land use, POIs, facilities, demand, green, and a DSM raster, allowing all tools to be tried in one click.

### Optimized
- **Speed optimization in visibility.isovist_field** — precomputes direction offsets once per field execution, speeding up the loop.
- **Speed optimization in noise screening grid** — broadcasts distance calculations per row-chunk to avoid cell-by-cell loops.

### Testing
- Engine unit checks grown to **360** (including exact feature counts for demo city, DSM elevation validation, cross-process determinism, and isovist_field bit-identity regression checks); end-to-end assertions at **282** on QGIS 3.44 LTR and QGIS 4.0.2.

## [3.6.0] - 2026-07-09

The Batch Plan Auditor closes the loop (50 algorithms, 15 groups).

### Added
- **Batch Plan Auditor** (Reporting group) — the whole standard battery in one run: network + demand + amenities + land use + facilities + greens in, and it chains the 15-minute access score, walkability audit, land-use balance, facility adequacy, green-space access and access equity; every score lands in one scenario snapshot JSON (ready for Scenario Compare A/B) plus an optional one-file Plan Performance Report. Each part optional; fully headless and model-designer friendly.
- **Plan Dashboard**: Plan Performance Index **history sparkline** (grows with every saved snapshot) and an **Audit…** button opening the Batch Plan Auditor.
- Scenario metric registry gains the auditor keys (walkability mean, low-walk share, weakest green coverage, access Gini) — direction-aware in comparisons.
- `docs/METHODS.md` — the method, formula and primary source of every tool group.

### Testing
- Engine unit checks grown to **350**; end-to-end assertions to **274**; dashboard harness to **24 checks** — on QGIS 3.44 LTR and QGIS 4.0.2.

## [3.5.0] - 2026-07-09

Urban Growth: change accounting, growth simulation and the sprawl scorecard (49 algorithms).

### Added
- **NEW GROUP: Urban Growth.**
- **Land-Cover Change Analysis** — the transition matrix of two class rasters: from/to pairs with cells + hectares, per-class gains/losses/persistence/net, optional class labels; the largest conversion named in the log.
- **Urban Growth Simulation (CA)** — constrained cellular automaton (SLEUTH tradition): score = suitability × (base + weight × urban neighbourhood share); top scorers convert per step until the land demand is met; never-build constraints; deterministic for a given seed **across processes** (unit-tested). Output: year-of-conversion raster.
- **Urban Sprawl Metrics** — SDG 11.3.1 LCRPGR (land consumption vs population growth) + patch count, largest-patch share, edge density.
- Engine: pure-NumPy `engine/growth.py`; three new group-coloured tool icons.

### Testing
- Engine unit checks grown to **345** (hand-counted transition matrices, gradient-following CA, constraint masks, cross-process determinism, hand-computed LCRPGR and edge lengths); end-to-end assertions to **266** on QGIS 3.44 LTR and QGIS 4.0.2.

## [3.4.0] - 2026-07-09

Environment Screening: road noise and green infrastructure (46 algorithms).

### Added
- **Road Noise Screening** (Microclimate group) — screening-quality dB(A) grid: RLS-90-style emission from traffic volumes (hourly factor for AADT) and heavy shares; roads as line-calibrated point sources; energetic sum with 20 lg r spreading; fixed insertion loss behind buildings. Optional receivers report levels + a population exposure table (5 dB bands). Documented as screening, not compliance.
- **NEW GROUP: Green Infrastructure.**
- **Green Space Access** — the park-hierarchy standard (`min_ha=max_dist` ladder) on real network distances: per-demand pass/fail per class, classes met, per-class covered population, citywide m²/capita.
- **Urban Green Connectivity** — crossable-gap patch graph: components, binary Probability-of-Connectivity index, per-patch dPC importance (the stepping-stone argument, quantified).
- Engine: pure-NumPy `engine/noise.py` (the infinite-line calibration is a unit test) and `engine/green.py`; three new group-coloured tool icons.

### Testing
- Engine unit checks grown to **331**; end-to-end assertions to **256** on QGIS 3.44 LTR and QGIS 4.0.2.

## [3.3.0] - 2026-07-09

Population & Housing: the demographic backbone of plan-making (43 algorithms).

### Added
- **NEW GROUP: Population and Housing.**
- **Population Projection (Cohort-Component)** — a Leslie-matrix projection from a plain age-group table: per-step survival, fertility and optional net migration as fields, any number of steps. Outputs step × age-group rows and per-step totals. Single-sex screening form; rates constant over the horizon.
- **Housing Needs Assessment** — the standard needs identity, batchable: future households, vacancy allowance, replacement losses, backlog; every intermediate in a metric/value table. Negative need = surplus.
- **Residential Capacity** — per-parcel buildable floorspace from FAR − existing floorspace → whole dwelling units (unit size, net-to-gross efficiency), with a district roll-up. The reality check against the housing need; feeds the Land-Use Allocation Optimizer.
- Engine: pure-NumPy `engine/population.py` (`leslie_matrix`, `cohort_projection`, `housing_needs`, `residential_capacity`); `report.svg_pyramid` age-structure chart; three new group-coloured tool icons.

### Testing
- Engine unit checks grown to **316** (hand-computed two-step Leslie projection, migration floors, needs identity, capacity clamps); end-to-end assertions to **242** on QGIS 3.44 LTR and QGIS 4.0.2.

## [3.2.0] - 2026-07-09

Visibility: viewsheds, isovists and landmark exposure (40 algorithms).

### Added
- **NEW GROUP: Visibility.**
- **Viewshed (DSM)** — line-of-sight sweep from observer points: observer/target heights, view radius, direction count; visibility-count raster output. Radial sweep with a running horizon angle, rays capped at the raster diagonal.
- **Isovist Field** — Benedikt's 2-D visibility measures sampled on a point grid between buildings: visible area/perimeter, min/max/mean radial, circularity, occlusivity. The VGA companion to the space-syntax tools.
- **Visual Exposure of Landmarks** — the inverse viewshed: outline samples (optional extra height for spires), per-cell count of visible outline points; difference before/after DSMs for skyline & heritage impact.
- Engine: pure-NumPy `engine/visibility.py`; three new group-coloured tool icons.

### Testing
- Engine unit checks grown to **304** (wall shadows, tall-target pokes, radius caps, corridor vs plaza isovists); end-to-end assertions to **233** on QGIS 3.44 LTR and QGIS 4.0.2.

## [3.1.0] - 2026-07-09

Transit: GTFS feeds become first-class citizens (37 algorithms).

### Added
- **NEW GROUP: Transit.**
- **GTFS Import and Service Stats** — loads a GTFS zip into QGIS with validation on the way in (named errors for missing files / malformed times). Stops as WGS84 points with daily departures + route counts; a route summary table (mode, trips, service span, longest stop sequence). Service day defaults to the feed's first active day.
- **Transit Frequency Map** — departures per stop within a time window: departures/hour, mean headway minutes, distinct routes (the frequent-network map), plus per-route trips in the window.
- **Transit Travel-Time Access** — door-to-door with public transport: walk to a stop on the street network, ride a RAPTOR-style timetable with up to N transfers, walk to each destination. Reports walk-only vs transit minutes, winning mode and minutes saved per destination. Overtaking trips treated FIFO (screening simplification, documented).
- Engine: pure-stdlib+NumPy `engine/transit.py` — GTFS zip reader (utf-8-sig, past-midnight times as plain seconds, never datetimes), `calendar`/`calendar_dates` service resolution, `stop_frequencies`, RAPTOR `compile_day` (pattern grouping by route + stop sequence) and `earliest_arrival`; `paths.multi_source_offset` (egress Dijkstra whose sources start at their own arrival offsets); three new group-coloured tool icons.

### Testing
- Engine unit checks grown to **287** (synthetic in-code GTFS: transfer chains, no-transfer cutoffs, late boarding, cancelled service days); end-to-end assertions to **221** on QGIS 3.44 LTR and QGIS 4.0.2.

## [3.0.0] - 2026-07-09

Scenarios & Walkability: the plan-evaluation loop closes and a tenth tool
group opens (34 algorithms).

### Added
- **Scenario Snapshot** (Reporting group) — captures the plan score metrics of the current project into a snapshot JSON.
  - PlanX output layers auto-detected by field signatures (access score, balance table, facility adequacy, demand coverage, density grid) or pinned explicitly.
  - Model-designer friendly: run the tools for alternative A, snapshot, rerun for B, snapshot, feed both files to Scenario Compare (A/B).
- **NEW GROUP: Walkability.**
- **Walkability Audit** — scores every street segment 0–100 from the classic walkability-index ingredients (Frank et al. 2010): intersection density, land-use mix entropy, destination counts, block length, slope. Editable weights and breakpoints; sub-scores + raw ingredients on every segment; missing inputs renormalised away.
- **Pedestrian Route Quality** — routes over quality-weighted streets (weight = length × (1 + penalty × (100 − score)/100)); reports detour ratio vs the plain shortest path, length-weighted mean walk score and the share of the route on low-scoring segments. Nearest-destination or all-pairs.
- Engine: pure-NumPy `engine/walkability.py`; `paths.shortest_path_tree` / `reconstruct_path` (predecessor Dijkstra that names the parallel edge taken); shared collector `planx/collect.py` feeding both the dashboard dock and the snapshot algorithm; three new group-coloured tool icons.

### Testing
- Engine unit checks grown to **265**; end-to-end assertions to **205** on QGIS 3.44 LTR and QGIS 4.0.2.

## [2.13.0] - 2026-07-08

Equity Cross-Tabs & Scenario Compare: who holds the low values, and which
plan alternative wins (31 algorithms).

### Added
- **Demographic Equity Cross-Tabs** (Equity group) — cross-tabulates any per-unit value by population subgroup.
  - Population-weighted quantile classes (quintiles by default) or fixed breaks.
  - Representation ratio per group × class cell (1 = proportional; over-representation in the lowest class flags a disadvantaged group).
  - Per-group population/value shares, weighted mean/P10/median/P90, internal Gini, and the Duncan & Duncan dissimilarity index vs the rest.
  - Optional second group field crosses two demographics; the input comes back annotated with its value class and cell representation ratio for mapping.
- **Scenario Compare (A/B)** (Reporting group) — the A/B view of the Plan Dashboard.
  - The dashboard dock gains **Save A / Save B** scenario snapshots (score metrics to JSON next to the project) and an in-dock comparison panel with direction-aware winners and coloured deltas.
  - Headless too: `planx:scenariocompare` diffs two snapshot JSON files into a comparison table and an optional one-file HTML comparison report.
- Engine: pure-NumPy `equity.crosstab` / `equity.value_classes`; new pure-stdlib `engine/scenario.py` (snapshot / compare / verdict, direction registry); `report.compare_section` / `build_compare_html`; two new group-coloured tool icons.

### Testing
- Engine unit checks grown to **250**; end-to-end assertions to **188** on QGIS 3.44 LTR and QGIS 4.0.2.

## [2.12.0] - 2026-07-08

Siting & Contiguity: Capacitated Facility Siting and Contiguous Land-Use Allocation (29 algorithms).

### Added
- **Capacitated Facility Siting** (Optimization group) — chooses where to build p new facilities respecting per-site capacity constraints and travel limits.
  - First, a greedy construction phase selects sites that maximize newly served demand under a capacity-respecting allocation.
  - Then, a Teitz-Bart vertex substitution phase optimizes the locations by swapping sites to maximize total served demand (with total travel cost as a tiebreaker).
  - Existing facilities enter as fixed-open.
  - Outputs selected sites (with rank, load, utilization, marginal demand gain), allocation lines (demand to site connection with cost), and uncovered demand.
- **Contiguous Land-Use Allocation** (Optimization group) — optional Hard Contiguity mode on the Land-Use Allocation algorithm to assign parcels to uses forming a single connected component per use.
  - Seed-based concurrent region-growing followed by boundary-swap local search preserving subgraph connectivity of affected uses.
  - Default is Soft (existing behaviour unchanged).
- `engine/optimize.capacitated_siting` and `engine/allocate.allocate_contiguous` — pure NumPy.
- A new group-coloured tool icon for Capacitated Facility Siting.

### Testing
- Engine unit checks grown to **225**; end-to-end assertions to **174** on QGIS 3.44 LTR and QGIS 4.0.2.

## [2.11.0] - 2026-06-30

Inequality Curves: Lorenz / concentration curves and the Atkinson index
(28 algorithms).

### Added
- **Inequality Curves (Lorenz & Atkinson)** (Equity group) — the
  distributional view of any per-unit good (access score, green space per
  capita, income…), with an exportable curve to chart and a measure that lets
  you set how much you weight the worst-off.
  - Outputs the **Lorenz curve** as a table — cumulative population share vs
    cumulative value share, bowing below the 45° line of equality — and the
    **Gini** coefficient (twice the area between them).
  - Reports the **Atkinson index** at low/medium/high inequality aversion
    (ε = 0.5, 1, 2) and at your own ε: higher ε weights the lower tail more,
    so the index reads as the share of total value society would trade to
    equalise the distribution.
  - A **rank field** (deprivation, income…) switches it to a **concentration
    curve and index**, revealing whether the value concentrates on the
    advantaged or disadvantaged end (negative when it falls as rank rises).
- `engine/equity.atkinson_index`, `lorenz_points`, `gini_from_lorenz` and
  `concentration_index` — pure NumPy, population-weighted; a new
  group-coloured tool icon.

### Testing
- Engine unit checks grown to **216**; end-to-end assertions to **166** on
  QGIS 3.44 LTR and QGIS 4.0.2. The trapezoidal Gini is asserted equal to the
  mean-difference Gini, and Atkinson against hand-computed geometric/harmonic
  means.

## [2.10.0] - 2026-06-30

Land-Use Pareto Front: the suitability vs compactness trade-off (27 algorithms).

### Added
- **Land-Use Pareto Front** (Optimization group) — maps the **trade-off**
  between per-parcel suitability and compact zoning instead of committing to
  a single weighted run. There is rarely one best plan: clustering a use into
  compact zones usually costs some suitability, and vice versa.
  - Solves the Land-Use Allocation Optimizer across a **sweep of compactness
    weights** (auto-scaled to the data, or capped by an upper weight) and
    records two higher-is-better scores per result: area-weighted
    **suitability** and the shared boundary between adjacent same-use parcels
    (**compactness**).
  - Reports the **non-dominated set** (the Pareto front) and its **knee** —
    the point furthest from the chord joining the front's extremes, i.e. the
    best-balanced compromise.
  - Outputs a **front table** (one row per weight: both scores raw and 0–1
    normalised, plus on-front / knee / selected flags) to plot, and the
    **parcel map** of one chosen solution — the knee by default, or the
    maximum-suitability or maximum-compactness end.
- `engine/allocate.pareto_front`, `pareto_mask` and a knee detector — pure
  NumPy, reusing the existing multi-objective allocation core
  (`allocate_multi`); a new group-coloured tool icon.

### Testing
- Engine unit checks grown to **202**; end-to-end assertions to **158** on
  QGIS 3.44 LTR and QGIS 4.0.2. The high-weight runs are asserted to reach the
  blocked (compact) allocation and the front extremes to be non-dominated.

## [2.9.0] - 2026-06-29

Annual Solar Potential: year-long clear-sky irradiation (26 algorithms).

### Added
- **Annual Solar Potential (DSM)** (Microclimate group) — clear-sky global
  solar irradiation **summed over a whole year** (kWh/m²/yr): rooftop-PV
  screening, annual solar access and year-round heat exposure, with no
  external solver or atmospheric dataset.
  - Instead of sweeping all 365 days, one representative **average day per
    month** (Klein 1977; Duffie & Beckman, *Solar Engineering of Thermal
    Processes*) is computed with the same shadow-aware beam +
    sky-view-weighted diffuse model as the single-day Solar Irradiation
    tool, scaled by the number of days in that month and summed. Twelve
    day-sweeps stand in for the year — accurate for screening, far faster
    than a full daily run.
  - Outputs the **annual irradiation raster**; optionally a **12-band
    monthly raster** (one named band per month) for seasonal analysis. The
    log reports the unobstructed flat-ground annual reference, scene
    statistics and the **peak month**.
- `engine/solar.annual_irradiation` — pure-NumPy aggregation that reuses the
  daily irradiation kernel; `_raster.write_raster_multiband` for the monthly
  output; a new group-coloured tool icon.

### Testing
- Engine unit checks grown to **191**; end-to-end assertions to **150** on
  QGIS 3.44 LTR and QGIS 4.0.2. The monthly bands are asserted to sum back
  to the annual raster.

## [2.8.0] - 2026-06-29

Multi-objective land-use allocation: compactness & adjacency.

### Added
- The **Land-Use Allocation Optimizer is now multi-objective** — beyond
  per-parcel suitability it can shape the *spatial pattern* of the plan,
  maximizing `w_suit · Σ(area · suitability) + Σ_adjacent L · C[use, use]`
  over the parcel adjacency graph (`L` = shared boundary length):
  - **Compactness weight**: rewards same-use parcels that share a
    boundary, so each land use forms compact contiguous zones instead of
    scattering (reward per map unit of shared boundary; `0` = off).
  - **Adjacency rules**: free text `residential|industry=-2,
    residential|green=1` rewards (+) or penalises (-) specific use pairs
    being neighbours, per unit of shared boundary — keep incompatible uses
    apart and compatible ones together.
  - **Suitability weight** (advanced) balances suitability against the
    spatial terms.
  Parcel adjacency and shared-boundary lengths are computed with a spatial
  index; the run reports the spatial score and the share of shared
  boundary that is between same-use parcels (a compactness indicator).
  With compactness `0` and no rules the result is **identical** to the
  pure-suitability allocation of 2.7.0.
- `engine/allocate.allocate_multi` and a shared `_allocate_core`: the
  spatial term is a symmetric use-compatibility matrix over the adjacency
  graph; greedy construction + reassignment + capacity-respecting pairwise
  swaps now optimise the full objective (pure NumPy, unit-tested).

### Tests
- Engine suite 168 → 175 checks (compactness clustering and an adjacency
  penalty that relocates a repelled use, with hand-computed objectives);
  e2e harness 137 → 141 assertions (a 2×2 checkerboard that stays
  fragmented without compactness and forms blocks with it / a repel rule)
  — verified on QGIS 3.44 LTR and QGIS 4.0.2.

## [2.7.0] - 2026-06-29

Land-Use Allocation Optimizer — 25 algorithms total.

### Added
- **Land-Use Allocation Optimizer** (Optimization group): assigns a land
  use to each parcel to **maximize total suitability** while meeting a
  **target area** for each use — the spatial-allocation problem at the
  heart of plan-making, solved natively with no external solver. You
  supply, on the parcel layer, one **suitability field per land use**
  (0–1 or 0–100 — e.g. straight from Suitability Lab) and a target area
  per use; each parcel is assigned in full to at most one use so the area
  given to a use stays within its target and the **area-weighted
  suitability** is as high as possible. Parcels not needed to meet the
  targets are left **unassigned**; a use that cannot be filled reports a
  **shortfall**. An optional **lock field** fixes already-zoned parcels to
  a use (consuming that use's target). Method: greedy construction (best
  suitability first) plus a local search of single-parcel reassignments
  and **capacity-respecting pairwise swaps** — a fast heuristic, not a
  guaranteed global optimum. Outputs the parcels with their assigned use,
  its suitability, the parcel area and a locked flag (style by
  `alloc_use` for a land-use map), and a per-use summary table (target vs
  allocated area, shortfall, parcel count and mean suitability achieved).
- `engine/allocate.py` (`parse_targets`, `allocate_land_use`) — pure
  NumPy, unit-tested; new group-coloured tool icon.

### Tests
- Engine suite 156 → 168 checks (incl. a greedy-trap case the swap phase
  must escape to reach the optimum); e2e harness 126 → 137 assertions with
  a hand-computed allocation and a locked-parcel scenario — verified on
  QGIS 3.44 LTR and QGIS 4.0.2.

## [2.6.0] - 2026-06-29

Equity & Allocation release: two new tools — 24 algorithms total.

### Added
- **Accessibility Equity (Gini / Theil)** (new "Equity" group): measures
  how *fairly* a value is distributed across the population — the
  spatial-equity / environmental-justice view the level-of-access tools
  do not give. Feed it any per-unit value (an Access Score, a travel
  time, a distance to the nearest facility). Population-weighted
  indices: **Gini** coefficient, **Theil's T** additively decomposed
  into **between-group** and **within-group** inequality (give a group
  field — district, income class, tenure — and the between share is the
  environmental-justice headline), **P90/P10** ratio, coefficient of
  variation and an **access-poverty share** (population beyond a
  threshold). Outputs the input units enriched with their weighted
  percentile rank, deviation from the mean and a poverty flag, plus a
  summary table — one row for the study area and one per group.
- **Capacitated Allocation (Nearest with Capacity)** (Optimization
  group): allocates demand to fixed facilities while **respecting
  capacity** — the realistic companion to Facility Adequacy (which
  assigns everyone to the nearest facility and only flags the overload
  afterwards). Each demand point is sent in full to the nearest facility
  with room and **spills** to the next-nearest when its nearest is full;
  points that fit nowhere in reach are left **uncovered**. Outputs the
  demand (assigned facility, network cost, status Assigned / Spilled /
  Uncovered, nearest facility) and the facilities (assigned load,
  remaining capacity, utilization, status Full / Has space / Unused).
- `engine/equity.py` (Gini, Theil T and decomposition, weighted
  quantiles, percentile ratio/rank, CV, poverty shares) and
  `engine/optimize.capacitated_assign` — pure NumPy, unit-tested; two
  new group-coloured tool icons.

### Tests
- Engine suite 131 → 156 checks (incl. the weighted Gini against the
  O(n²) mean-difference definition and the Theil between+within
  identity); e2e harness 109 → 126 assertions with hand-computed equity
  indices and a capacity-denial/spill scenario — verified on QGIS 3.44
  LTR and QGIS 4.0.2.

## [2.5.1] - 2026-06-18

- docs: add CITATION.cff for Zenodo DOI integration

## [2.5.0] - 2026-06-11

Microclimate II + per-tool icons: three new tools — 22 algorithms total.

### Added
- **Sun Hours (DSM)** (Microclimate): hours of direct sunlight per cell
  over one full day in a single run — the day is swept at a configurable
  interval (default 30 min), each step casts the DSM shadow mask with the
  embedded NOAA sun position. Replaces the old "run Shadow Casting in
  Batch mode" workaround. Right-to-light checks, courtyard/playground sun
  audits; the log reports the site's potential daylight.
- **Solar Irradiation (DSM)** (Microclimate): clear-sky daily global
  irradiation per cell (kWh/m²) — ASHRAE-style beam (Masters 2004) blocked
  by cast shadows + isotropic diffuse weighted per cell by the sky view
  factor. Quick screening of roofs and open spaces for solar potential or
  summer heat exposure; flat-ground reference reported for comparison.
- **Heat Island Risk Grid** (Microclimate): vector UHI screening from the
  layers every plan already has — building footprints (with optional
  height field), green areas and water polygons. Per cell: built fraction,
  area-weighted mean height, green/water fractions and a **fixed-scale
  0–100 risk score** (weights are parameters; the scale is set by the
  weights, not stretched to the data, so scenarios stay comparable) with
  Low/Moderate/High/Very High classes.
- **Eigenvector centrality** in Network Centrality (Bonacich power
  iteration on A + I — the shift makes it converge on bipartite street
  graphs; max-normalized to 1), new `eigen` field on junction output.
- **Population-weighted summary** in Multi-Amenity Access Score: optional
  population field on origins reports total population, weighted mean
  score, share with full access and share with no category reachable.
- **Per-tool icons**: all 22 algorithms now carry their own meaningful
  icon (colour-coded by group) in the Processing toolbox and the PlanX
  Studio dock; the Plan Dashboard menu action got the report icon.
  Generator: `scratch/make_planx_tool_icons.ps1` (GDI+, 256 px PNG).
- `engine/solar.py`: `sun_hours`, `clear_sky_irradiance`,
  `daily_irradiation`, `heat_risk_index`; `engine/centrality.py`:
  `eigenvector` (all pure NumPy, unit-tested).

### Fixed
- Shadow casting could crash (negative-slice broadcast in the array
  shifter) and wastefully over-scan at very low sun altitudes: shifts
  beyond the raster now short-circuit and the sweep is capped at the
  raster diagonal.

### Tests
- Engine suite 111 → 131 checks; e2e harness 90 → 109 assertions —
  verified on QGIS 3.44 LTR and QGIS 4.0.2 (including icon coverage).

## [2.4.0] - 2026-06-11

Optimization release: facility location on the network — 19 algorithms
total. The v2.x roadmap is complete.

### Added
- **Facility Location Optimizer (Coverage / P-Median)** (new
  "Optimization" group): chooses the best sites for new facilities among
  candidate locations on real network distances — no external solver.
  - *Maximize coverage* (Church & ReVelle 1974): greedy picks, each adding
    the most uncovered weighted demand within the catchment radius;
  - *Minimize total travel* (p-median): greedy construction + Teitz & Bart
    (1968) vertex substitution on the population-weighted travel cost;
  - existing facilities (optional) are kept in the solution as fixed
    sites — new picks complement them;
  - outputs: every candidate with its standalone **screening score**
    (demand within reach), selection flag, pick rank and marginal gain;
    plus the demand allocation (assigned facility, network cost, covered).
- `engine/optimize.py`: coverage weights, greedy maximal coverage,
  p-median with vertex substitution and penalty handling for unreachable
  demand, nearest-assignment helper (pure NumPy, unit-tested).
- Tests: engine suite 98 → 111 checks (incl. a greedy-trap case the
  substitution phase must escape); e2e harness 80 → 90 assertions with
  hand-computed selections, verified on QGIS 3.44 LTR and QGIS 4.0.2.

## [2.3.0] - 2026-06-11

Performance Dashboard release: live score cards + one-click HTML report —
18 algorithms total.

### Added
- **Plan Dashboard dock** (PlanX menu → Plan Dashboard): live score cards
  over the PlanX output layers — Plan Performance Index, accessibility
  score, standards compliance, covered-population share and density. The
  output layers of Multi-Amenity Access Score, Land-Use Balance, Facility
  Adequacy and Density Grid are auto-detected in the project by their field
  signatures; "Save HTML Report…" exports the report and opens it in the
  browser.
- **Plan Performance Report (HTML)** algorithm (new "Reporting and
  Dashboard" group): builds the same single-file report headless / in the
  model designer — score cards, score histogram, SVG score map (red→green),
  provided-vs-required balance bars, facility utilization table and density
  summary. Everything is inline CSS/SVG drawn by the embedded engine: a
  shareable one-file report with no external assets or services.
- `engine/report.py`: summaries, score cards, colour ramp and the full
  HTML/SVG renderer (pure stdlib — not even NumPy — unit-tested anywhere).
- Tests: engine suite 77 → 98 checks; e2e harness 70 → 80 assertions, all
  verified on QGIS 3.44 LTR and QGIS 4.0.2; new headless dashboard-dock
  check (auto-detection + cards) on both.

## [2.2.0] - 2026-06-11

Plan Standards & QA release: three new tools in a new group — 17 algorithms
total.

### Added
- **Land-Use Balance (Per-Capita Standards)**: the classic balance table —
  area and m² per capita per category, required area from *configurable*
  per-capita standards ("green=10, education=4"...), surplus/deficit and
  status. Standards are free text, never hard-coded regulation values;
  keywords match category names by containment.
- **Facility Adequacy (Capacity + Distance)**: one multi-source network
  pass assigns population to its nearest facility within a catchment cost,
  then compares assigned load with capacity — outputs facility utilization
  (Adequate / Overloaded / Unused) and covered/uncovered demand, with the
  covered-population share in the log.
- **Density Grid**: distributes any numeric value (population, dwellings,
  GFA) from polygons or points onto a regular grid by area share (simple
  dasymetric disaggregation) and reports density per hectare.
- `engine/standards.py`: standards parser, category matcher and balance
  computation (pure Python, unit-tested).
- Tests: engine suite 69 → 77 checks; e2e harness 56 → 70 assertions, all
  verified on QGIS 3.44 LTR and QGIS 4.0.2.

## [2.1.0] - 2026-06-11

Microclimate (UMEP-lite) release: three new tools in a new "Microclimate"
group, all on the embedded engine — 14 algorithms total.

### Added
- **Shadow Casting (DSM)**: cast shadows for any date and local time with an
  embedded NOAA solar-position model (sun altitude/azimuth computed at the
  raster center); UMEP-style iterative DSM sweep; byte raster output
  (1 = shadow), batch-friendly for shadow-duration maps.
- **Sky View Factor (DSM)**: hemispheric SVF per cell from N-direction
  horizon scans (SVF = 1 - mean sin² horizon; flat = 1, foot of a long
  wall ≈ 0.5); configurable directions and search radius.
- **Frontal Area Index**: λf (wind-facing facade area / cell area) and λp
  (plan area ratio) on a grid, building frontal areas distributed by
  footprint overlap (Grimmond & Oke roughness indicators).
- `engine/solar.py`: solar position (NOAA simplified), shadow ray-march,
  SVF horizon scan, projected footprint width — pure NumPy, no qgis
  imports.
- Tests: engine suite 52 → 69 checks (solstice/equinox sun positions,
  closed-form shadow lengths, SVF flat/wall values, projected widths);
  e2e harness 43 → 56 assertions (synthetic DSM tower) on QGIS 3 LTR + 4.

## [2.0.0] - 2026-06-11

Complete rewrite: PlanX is now the **Urban Analytics Studio** — an embedded
analytics engine with eleven Processing algorithms, zero external
dependencies, English-only UI.

### Added
- **Engine** (`engine/`): NumPy core with SciPy `csgraph` fast path and an
  identical pure-Python Dijkstra fallback; CSR primal (junction) and dual
  (segment/angular) graph builders; Brandes (2001) betweenness with radius
  limiting, pruned dual-cost search and source sampling; closeness
  (Wasserman–Faust + harmonic) and straightness; pure-geometry morphology
  kernels (shoelace, monotone-chain hull, rotating-calipers MRR,
  orientation entropy, meshedness).
- **Network Analysis**: Prepare Network (noding/dedupe/sliver removal),
  OD Cost Matrix (detour ratio, desire lines), Service Areas / Isochrones
  (multi-source bands as edges + dissolved polygons), Nearest Facility
  Allocation (assignment, spider lines, facility load summary).
- **Centrality & Space Syntax**: Network Centrality (degree, closeness,
  harmonic, straightness, node+edge betweenness); Space Syntax segment
  angular analysis with metric radii — integration, choice, NACH, NAIN
  (Hillier & Iida 2005; Hillier, Yang & Turner 2012).
- **Urban Morphology**: Building Form Metrics (IPQ, convexity,
  rectangularity, elongation, orientation, courtyards, fractal dimension,
  shared-wall ratio); Morphological Tessellation (Fleischmann method on
  native GEOS Voronoi); Spacematrix Density (GSI/FSI/OSR/L + class);
  Street Network Morphology (orientation entropy/order after Boeing 2019,
  alpha/beta/gamma indices, junction typology).
- **Accessibility**: Multi-Amenity Access Score — 15-minute-city composite
  over any number of amenity layers.
- **PlanX Studio dock**: grouped launcher for the toolset.
- New brand icon and hero banner; ROADMAP with the v2.x plan.
- Test suite: 52 engine unit checks vs hand-computed graphs; 43-assert
  end-to-end harness verified on QGIS 3.44 LTR **and** QGIS 4.0.2.

### Changed
- `hasProcessingProvider=yes`; minimum QGIS raised to 3.22; metadata,
  tags and description rewritten for the analytics scope.

### Removed
- The legacy mixed script collection (16 tools): QNEAT3/GRASS-dependent
  ODQNet and NetCentral, duplicates of other PlanX plugins (parcelflux,
  coverage footprint, road platform), and assorted utilities. Their
  network use-cases return as embedded, dependency-free implementations.

## [1.0.9] and earlier

Legacy PlanX script suite (2025): dynamic script loader with 16 mixed
tools. See git history for details.
