# Scientific Model Assumptions and Validation Plan

**Status:** Proposed model specification; pending hydrologist/human-team approval
**Last updated:** 2026-08-21

This document separates governing methods from demonstration parameters. An equation being established does not make uncalibrated local parameters accurate. Values derived from land-cover classes, missing drainage attributes, or synthetic rainfall remain visibly labelled assumptions.

## 1. Units and symbols

The numerical model uses SI units.

| Symbol | Meaning | Unit |
|---|---|---|
| `R` | rainfall rate as commonly ingested | mm h⁻¹ |
| `r` | rainfall rate used by solver | m s⁻¹ |
| `r_e` | effective rainfall after losses | m s⁻¹ |
| `h` | surface water depth | m |
| `z` | bed/terrain elevation | m |
| `η = z + h` | water-surface elevation | m |
| `q_x`, `q_y` | unit-width surface discharge | m² s⁻¹ |
| `Q` | volumetric discharge | m³ s⁻¹ |
| `n` | Manning roughness | s m⁻¹/³ |
| `g` | gravitational acceleration | m s⁻² |
| `A_cell` | plan area of an active grid cell | m² |
| `Δt` | numerical timestep | s |

Rainfall conversion is:

\[
r = \frac{R}{1000 \times 3600}.
\]

For spatially varying rain over one interval, rainfall volume is:

\[
V_{rain} = \sum_i r_i A_i \Delta t.
\]

Conversion tests use exact known values; for example, 3.6 mm h⁻¹ equals 10⁻⁶ m s⁻¹. Floating-point comparison uses an explicit tolerance.

## 2. Rainfall input and nowcasting

### 2.1 Required input semantics

A rainfall field represents mean rain rate over `[valid_from, valid_to)`, not an instantaneous sample. It carries source issue time, valid interval, native grid/resolution, units, nodata, and provenance. Temporal overlaps/gaps are rejected or explicitly quality-flagged.

Spatial alignment uses area-aware/conservative remapping for accumulated precipitation where supported. Any interpolation is recorded. Values are clipped only for impossible negative rain after source quality review; a material negative field fails ingestion. Missing rainfall is never silently replaced with zero.

### 2.2 Baseline 1: persistence

For lead time `τ`:

\[
\hat R(x,y,t_0+\tau) = R(x,y,t_0).
\]

Assumptions:

- the last valid field is recent enough according to a configured maximum age;
- storm growth, decay, and movement are ignored;
- source resolution and uncertainty remain unchanged.

Persistence is a genuine baseline, not an accuracy claim.

Validation when an adequate sequence is available:

- rolling-origin evaluation rather than random train/test splitting;
- MAE and RMSE in mm h⁻¹;
- correlation where variance is non-zero;
- rain/no-rain precision/recall at documented thresholds;
- spatial fractions skill/FSS or another reviewed neighbourhood metric where grid size supports it;
- metrics by lead time and rain-intensity bin.

### 2.3 Baseline 2: simple statistical/advection model

Candidate order:

1. scalar/field exponential smoothing only where station/grid history supports it;
2. optical-flow/advection extrapolation only for frequent radar/satellite images with valid georeferencing;
3. blend with persistence using validation data.

No particular method is approved until the available rainfall data is inspected. A coarse hourly NWP forecast cannot be relabelled as a high-resolution radar nowcast.

### 2.4 ML models

An ML rainfall model is out of the initial critical path. It requires:

- a documented, sufficiently long and homogeneous dataset;
- time-ordered train/validation/test events with no frame leakage;
- persistence and simple baseline comparison;
- reproducible training configuration and model card;
- lead-specific metrics and uncertainty/edge-case analysis;
- a measurable benefit that justifies its inference/deployment cost.

No model accuracy exists at Phase 0.

## 3. Rainfall losses and runoff production

The surface model must not convert every rainfall millimetre directly into flood depth. The proposed MVP keeps loss accounting explicit and conservative.

### 3.1 Depression/interception storage

Each cell has a configured maximum depression/interception store `D_max` (m) and current store `D`:

\[
\Delta D = \min(D_{max}-D,\ r\Delta t),
\]

before remaining rainfall becomes available for infiltration/surface input. The stored amount is tracked as a state, not deleted from the mass ledger. Drainage/evaporation of this store is omitted over the short 3-hour horizon unless explicitly configured.

Caveat: topographic depressions are also represented by the DEM and surface solver. `D_max` is micro-storage/interception below the resolved grid scale and must not double-count large visible terrain depressions.

### 3.2 Proposed MVP infiltration: Horton capacity

Potential infiltration capacity after elapsed wetting time `t` is:

\[
f_c(t) = f_{min} + (f_0-f_{min})e^{-kt},
\]

where:

- `f_0` is initial infiltration capacity (m s⁻¹),
- `f_min` is minimum/asymptotic capacity (m s⁻¹),
- `k` is decay coefficient (s⁻¹),
- `t` is elapsed wetting time (s).

Actual infiltration is limited by potential capacity and water available from rainfall plus ponding during the numerical interval. The implementation must never remove more water than exists in the cell.

Assumptions/limitations:

- parameters are empirical and spatially assigned from land-cover/optional soil zones;
- initial moisture and recovery between storms are simplified;
- underground utilities and preferential flow are ignored;
- impervious cells may have near-zero but not negative infiltration;
- no parameter defaults will be labelled local measurements.

Alternative before approval: Green–Ampt infiltration is more process-based but requires saturated conductivity, wetting-front suction, moisture deficit, and careful ponded/unponded transitions. It should replace Horton only if defensible soil/initial-state data and tests are available.

### 3.3 Effective rainfall

For a timestep, effective rainfall source is the non-negative remainder after depression/interception storage and actual infiltration:

\[
r_e = \max(0, r - i - d),
\]

where `i` and `d` are the equivalent interval rates allocated to infiltration and depression storage. The discrete ledger—not only this shorthand equation—is authoritative and prevents ordering losses from exceeding available water.

Validation:

- zero rain produces zero loss/runoff;
- rainfall below available loss capacity yields no effective runoff in a closed single-cell test;
- impervious/no-loss test passes all rain into surface storage;
- every interval closes `rain = effective rain + infiltration + change in micro-storage` within numeric tolerance;
- parameter sensitivity and cell-wise finite/non-negative checks.

## 4. Terrain and land-surface representation

### 4.1 DEM interpretation

The initial likely source is a 30 m digital surface model. Therefore:

- it may include buildings and vegetation;
- street gutters, kerbs, small channels, culverts, and underpasses are unresolved;
- vertical error can be comparable to shallow flood depths;
- associating output with roads does not create street-scale terrain detail.

The model domain uses a projected metric CRS. Nodata cells are closed or excluded according to an explicit domain mask. Any datum conversion or vertical offset is documented.

### 4.2 DEM conditioning

Urban pluvial flooding depends on depressions, so global pit filling is not acceptable by default. Conditioning may include only reviewed operations:

- removal of known spikes/voids;
- hydrologic burning/breaching for verified culverts or channels;
- building treatment where resolution/data support it;
- boundary clipping and active-cell mask generation.

Each operation records algorithm, parameters, before/after checksums, affected cell count/volume, and reason. Results should be sensitivity-tested against the unconditioned DEM.

### 4.3 Roughness

Manning `n` is mapped from land-cover classes using literature ranges chosen and cited during implementation. It is not inferred as a measured property from a classification label. The parameter manifest preserves:

- class-to-`n` mapping;
- literature/source;
- selected value and tested range;
- raster date/resolution;
- cells with unknown class.

## 5. 2-D surface-water routing

### 5.1 Proposed established implementation

Use Landlab's [`OverlandFlow`](https://landlab.readthedocs.io/en/latest/generated/api/landlab.components.overland_flow.generate_overland_flow_deAlmeida.html), which implements the de Almeida et al. local-inertial approximation on a structured raster grid. This avoids presenting a novel, unverified hydraulic solver.

Key references:

- Bates, Horritt & Fewtrell (2010), *A simple inertial formulation of the shallow water equations for efficient two-dimensional flood inundation modelling*, Journal of Hydrology 387, 33–45.
- de Almeida et al. (2012), *Improving the stability of a simple formulation of the shallow water equations for 2-D flood modeling*, Water Resources Research.
- Adams et al. (2017), *The Landlab v1.0 OverlandFlow component*, Geoscientific Model Development 10, 1645–1663.

### 5.2 Governing approximation

Surface continuity is:

\[
\frac{\partial h}{\partial t}
+ \frac{\partial q_x}{\partial x}
+ \frac{\partial q_y}{\partial y}
= r_e + s_{surcharge} - s_{inlet} + s_{external}.
\]

A representative local-inertial momentum form in the x direction is:

\[
\frac{\partial q_x}{\partial t}
+ gh\frac{\partial \eta}{\partial x}
+ \frac{gn^2 q_x|q_x|}{h^{7/3}} = 0,
\]

with the analogous y-direction equation and the selected implementation's stabilised staggered-grid discretization. Convective acceleration is neglected.

The adaptive timestep follows a Courant-type restriction of the form:

\[
\Delta t \leq \alpha \frac{\Delta x}{\sqrt{g h_{max}}},
\]

with the implementation's dry-depth and stability handling. Proposed initial `α = 0.5` lies inside the documented 0.2–0.7 range but is a numerical configuration to verify, not a calibrated physical value.

### 5.3 Applicability assumptions

The local-inertial approximation is suited to slowly varying, predominantly subcritical shallow flooding where friction and pressure-gradient effects dominate. Limitations include:

- omitted advective acceleration;
- reduced suitability for rapidly varied/supercritical flow, hydraulic jumps, dam breaks, and steep terrain;
- structured D4 link flow in the proposed library representation;
- unresolved buildings/kerbs at the default grid;
- uncertain roughness and terrain dominate shallow-depth uncertainty;
- numerical velocity derived at near-dry cells is unreliable and should be null/quality-flagged below a wet threshold.

### 5.4 Initial and boundary conditions

MVP initial condition: zero modelled surface water above terrain unless a warm-start artifact is explicitly supplied. Permanent water bodies must be masked or initialized through a reviewed boundary/state definition; they are not assumed dry roads.

Default boundaries:

- reviewed open/outflow boundary at downstream edges/receiving water;
- closed boundaries where physical divides are justified;
- no unrecorded water source at edges.

A flat fixed zero-depth edge is only a demonstration boundary and can drain too aggressively. Boundary sensitivity is mandatory. Tide/storm-surge stage is a stretch input, important for coastal pilots but omitted from the first MVP unless trustworthy stage data exist.

### 5.5 Surface validation

Before use on a city pilot:

1. exact volume in a level closed bowl under uniform rain/no losses;
2. wetting/drying and disconnected depression tests;
3. flow over a planar surface compared to an analytical/accepted runoff benchmark;
4. implementation/library regression examples;
5. selected UK Environment Agency 2-D benchmark cases, especially urban rainfall Test 8A;
6. cell-size, `α`, wet threshold, roughness, and boundary sensitivity;
7. non-negative/finite depth and a closed mass ledger.

Passing numerical benchmarks is verification, not local event validation.

## 6. 1-D drainage hydraulics

### 6.1 Proposed engine

Use [US EPA Storm Water Management Model (SWMM) 5.2](https://www.epa.gov/water-research/storm-water-management-model-swmm) with dynamic-wave routing through a maintained Python toolkit/interface. EPA documents SWMM as a dynamic rainfall-runoff and drainage-routing model; dynamic wave can represent surcharge, backwater, pressurization, and flow reversal.

The Phase 1 dependency spike will compare the current official `epaswmm` package, `swmm-toolkit`/PySWMM, and `swmm-api` for:

- Python 3.11/Linux wheels and licence;
- deterministic model stepping;
- setting time-varying lateral node inflow;
- retrieving node head/flooding, link flow/depth, and continuity reports;
- modifying link/orifice controls for blockage;
- avoiding unsafe global state under a worker process.

### 6.2 SWMM representation

- Inlets exchange water with mapped surface cells.
- Junctions have ground/rim elevation, invert elevation, max depth, and optional ponded area.
- Conduits use actual geometry, length, invert/slope, and roughness when known.
- Outfalls define downstream stage/boundary and flap-gate behavior when known.
- Dynamic wave is selected so pressure/backwater/reversal can occur.

MVP avoids double-counting rainfall-runoff: raster loss/surface routing creates surface water, and inlet exchange supplies captured water to the drain network. SWMM subcatchment rainfall-runoff is disabled for this coupled path unless a separately reviewed partitioning scheme is introduced.

### 6.3 Missing parameters

Plan geometry alone is not a hydraulic model. When dimensions/inverts/inlet capacities are absent:

- values may be generated only under a named deterministic scenario;
- every generated field is `ASSUMED_PARAMETER`;
- the UI says the drainage capacity is simulated;
- no statement is made that a mapped actual drain is overloaded in reality;
- sensitivity ranges are run;
- a completely synthetic test network remains available so verification does not depend on uncertain municipal geometry.

### 6.4 Blockage

Scenario blockage fractions are proposed as 0%, 25%, 50%, and 100% capacity obstruction. The implementation must alter the hydraulic model, not just a status label.

Preferred representation after SWMM spike:

- a controlled inlet/orifice/conduit opening or adjusted effective cross-section consistent with the blocked element;
- 100% closes that path;
- roughness-only adjustment is not used as a universal blockage proxy without justification.

Blockage location, start/end time, affected element, implementation method, and effective opening are included in run parameters. Partial obstruction can have nonlinear effects and reroute flow; therefore the capacity percentage is a scenario control, not an assertion of exact discharge reduction.

### 6.5 Drain validation

- reproduce an EPA SWMM example and expected continuity behavior;
- simple single-conduit normal-flow capacity cross-check using a known analytical/Manning case where applicable;
- no-rain/no-inflow steady state;
- capacity exceedance produces surcharge/ponding through SWMM state;
- flow reversal/backwater controlled test under dynamic wave;
- 0/25/50/100% blockage on an isolated network changes flow/flooding consistently with the configured obstruction;
- SWMM runoff and flow-routing continuity error parsed and stored.

## 7. Two-way surface–drain coupling

### 7.1 Exchange concept

At an inlet mapped to surface cell(s), exchange is driven by surface water-surface elevation `η_s`, drainage hydraulic head `H_d`, inlet crest elevation, and inlet geometry. A conceptual signed orifice relation for a submerged opening is:

\[
Q_{ex} = C_d A_o \sqrt{2g|\eta_s-H_d|}\;\operatorname{sign}(\eta_s-H_d),
\]

subject to the correct free/submerged inlet regime, a reviewed grate/weir/orifice formulation, and caps from:

- water physically available in the source cell/node over `Δt`;
- configured inlet/opening capacity;
- numerical stability;
- closed/flap-gate/blockage controls.

A positive sign means surface capture; when drainage head exceeds surface head and no flap gate prevents it, the sign reverses and SWMM water returns as surface surcharge/backflow.

This equation is a design direction, not yet an approved inlet model. The implementation must cite the selected inlet formulation and test transitions between regimes.

### 7.2 Conservation requirements

For every exchange substep:

\[
\Delta V_{surface} = -Q_{ex}\Delta t,
\quad
\Delta V_{drain} = +Q_{ex}\Delta t,
\]

with reversed signs for surcharge. Exchange is written to both component ledgers under one exchange ID. The whole-system ledger excludes it as an external source/sink.

No source may become negative. If a requested exchange exceeds available volume, cap it and record the cap reason.

### 7.3 Coupling timestep

The coupling interval must be no larger than the stable surface/SWMM stepping interval needed to avoid lagged oscillation or excessive exchange. Proposed approach:

1. obtain the next stable surface and SWMM timestep;
2. step to the minimum of those, the next rainfall boundary, output boundary, and configured maximum exchange interval;
3. perform exchange in a documented operator-splitting order;
4. run timestep-halving convergence tests.

The exact split order is pending a coupling spike. A 30-second value from the problem prompt is not assumed scientifically correct.

### 7.4 Coupled verification

- one-cell surface reservoir connected to one storage node with a known equilibrium;
- capture-only volume transfer;
- surcharge-only volume transfer;
- oscillating head test to detect sign/lag instability;
- UK Environment Agency benchmark Test 8B (surface flow from a surcharging sewer), subject to data availability/licence;
- timestep-halving sensitivity;
- whole-system mass closure.

## 8. Mass conservation

For a run from initial to final state:

\[
V_{rain} + V_{external\_in} + V_{surface,0} + V_{drain,0}
=
V_{infiltration} + V_{surface\_boundary\_out} + V_{drain\_outfall}
+ V_{microstore,final} + V_{surface,final} + V_{drain,final} + \epsilon.
\]

If initial micro-storage is nonzero it is included on the left. Evaporation is omitted over the MVP's short horizon; if enabled later it becomes an explicit loss term.

Residual:

\[
\epsilon = V_{inputs+initial} - V_{outputs+final}.
\]

Proposed diagnostic relative error:

\[
e_{rel} = \frac{|\epsilon|}{\max(V_{rain}+V_{external\_in}, V_{scale})},
\]

with an absolute-volume check for dry/nearly dry runs. `V_scale` is a documented small reference volume to avoid unstable division.

Initial quality gate proposal:

- pass: relative error ≤ 1%;
- warning: >1% and ≤5%;
- fail: >5% or a material unaccounted negative/positive source.

These are engineering gates to review and tighten through benchmark evidence, not claimed model accuracy. Component and interval ledgers are retained to locate errors.

## 9. Flood depth, extent, velocity, and severity

Depth is:

\[
h = \max(0, \eta-z).
\]

Material negative values fail the run; only tiny floating-point undershoot below an explicitly tested epsilon may be clamped and counted in diagnostics.

Proposed configurable **demonstration** severity classes:

| Depth | Label |
|---:|---|
| 0–0.05 m | Low |
| 0.05–0.15 m | Moderate |
| 0.15–0.30 m | High |
| >0.30 m | Severe |

These are not universal life-safety or vehicle standards. `extent_threshold_m` is stored with every flood extent. Changing the threshold changes IoU/extent metrics and must be reported.

Velocity is derived only where the solver and wet depth support a stable estimate. Near-dry velocity is null/quality-flagged rather than divided by a tiny depth. Velocity-depth hazard classifications are stretch work requiring policy review.

## 10. Road exposure and routing

### 10.1 Raster-to-road exposure

Each road edge is densified/sampled over a buffered corridor. Store:

- maximum depth;
- 95th-percentile depth;
- wet length above the configured extent threshold;
- source prediction/timestamp;
- nodata fraction and sampling resolution.

A segment with substantial nodata is `unknown`, not dry.

### 10.2 Cost model

Base edge travel time:

\[
t_{base,e} = \frac{L_e}{v_e},
\]

where OSM speed tags are preferred and class-based imputation is recorded.

A proposed lower-exposure generalized cost is:

\[
C_e = t_{base,e}\left(1 + \lambda_d P_d(h_e) + \lambda_l P_l(L_{wet,e})\right)
+ \lambda_u P_u(u_e),
\]

where penalty functions/weights are configuration, not scientific constants. Edges above a profile's closure criterion are removed (`C_e = ∞`).

Vehicle passability thresholds are deliberately **TBD** pending a disaster-management/transport reviewer. The flood severity legend must not be automatically reused as vehicle passability.

### 10.3 Route outputs

- fastest route minimizes base travel time but reports flood exposure;
- lower-exposure route minimizes reviewed generalized cost and closes impassable/unknown edges according to policy;
- emergency route uses a separately reviewed vehicle profile and destination priorities;
- route explanation names avoided closed/high-depth edges and ETA/exposure trade-off.

The system says “lower modelled exposure,” never guarantees “safe.”

### 10.4 Routing validation

- known small graphs with analytically expected shortest paths;
- zero-flood lower-exposure route equals/closely follows fastest according to tie-breaking;
- a flooded edge receives the exact configured penalty;
- closed edge is never traversed;
- alternate route is chosen when its generalized cost is lower;
- disconnected origin/destination returns a clear no-route state;
- all candidate routes report consistent distance, ETA, maximum depth, and wet length.

## 11. Alerts

Alerts are deterministic rules over model outputs, not an ML classifier. Each rule includes threshold/config version, prediction ID, valid time, area/road/drain entity, and provenance.

Candidate rules:

- depth threshold exceeded for a configured duration;
- road closure/profile exceedance;
- drainage node surcharge/backflow;
- mass-balance/model-quality warning;
- stale/missing rainfall source.

No public warning semantics or dissemination are used without authority review.

## 12. Uncertainty

Initial deterministic output has no calibrated probability. Credible first uncertainty display is a **scenario envelope** across reviewed members, for example:

- rainfall forcing variants;
- infiltration/roughness ranges;
- inlet capacity ranges;
- drainage blockage states;
- DEM sensitivity source/conditioning.

The dashboard may show min/median/max or member exceedance count, explicitly called scenario spread. `flood_probability` remains null unless members and weights have a defensible probabilistic interpretation.

## 13. Proposed parameter register

Values marked TBD must be selected from data/literature and approved, not invented during coding.

| Parameter | Proposed initial policy | Status / validation |
|---|---|---|
| Forecast horizon | 180 min | Problem requirement |
| Rainfall forcing interval | 15 min | Proposed; source-dependent |
| Output interval | 5 min | Proposed visualization/impact cadence |
| Surface/SWMM timestep | Adaptive/bounded seconds | Determine by solver/coupling tests |
| Pilot size | about 4 km × 4 km | Compute-budget proposal |
| Grid cell | 30 m with current open global DEM | Data-limited; sensitivity required |
| Surface solver | Landlab local inertial | Pending dependency and benchmark spike |
| Stability `α` | 0.5 initial numerical test value | Verify 0.2–0.7 documented range |
| Wet/dry threshold | TBD from implementation tests | Report extent sensitivity |
| Manning `n` by cover | TBD with citations/ranges | Uncalibrated until event data |
| Horton `f0`, `fmin`, `k` | TBD by cover/soil scenario | Uncalibrated; sensitivity required |
| Depression storage | TBD by cover scenario | Avoid DEM double count |
| SWMM routing | Dynamic wave | Proposed established engine |
| Inlet coefficient/geometry | Measured/published or TBD assumed scenario | Must be status-labelled |
| Blockage | 0/25/50/100% opening/capacity scenario | Implementation verified hydraulically |
| Mass warning/fail | 1% / 5% plus absolute test | Proposed quality gate, review after benchmarks |
| Severity classes | 0.05/0.15/0.30 m boundaries | Demo-only, configurable |
| Vehicle closure | TBD per reviewed vehicle profile | Do not infer from severity legend |

## 14. Scientific honesty and known limitations

At Phase 0:

- no rainfall model has been trained or evaluated;
- no flood event has been calibrated or validated;
- no local drainage capacity dataset has been accepted;
- no source provides surveyed street-scale terrain;
- no runtime benchmark has been measured;
- no route is suitable for real emergency navigation.

The proposed methods make rainfall, terrain, loss, drainage capacity, surcharge, and blockage causally participate in the simulation. They do not remove uncertainty from missing local data.

## 15. Pre-release scientific checklist

- [ ] Rainfall changes runoff and depth in controlled tests.
- [ ] Terrain changes flow path/storage in controlled tests.
- [ ] Infiltration and depression storage are volume-accounted.
- [ ] Drainage capture removes equal surface volume.
- [ ] Surcharge/backflow returns equal drain volume to the surface.
- [ ] A hydraulic blockage changes model behavior, not only UI state.
- [ ] All depths/losses/storage are finite and non-negative within numeric tolerance.
- [ ] CRS, vertical reference, units, issue time, valid time, and lead time are valid.
- [ ] Whole-system and component mass residuals pass reviewed gates.
- [ ] Predictions and scenarios are visibly distinct from observations/static reference data.
- [ ] Metrics, if any, are computed from an ingested independent reference with code/artifacts.
- [ ] Another person can rebuild the pilot and rerun all scenarios from documented commands.
