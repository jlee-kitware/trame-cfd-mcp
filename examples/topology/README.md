# Topology (TTK) examples

Scripts that exercise the topological-analysis domain (TTK) added to
`trame-cfd-mcp`, and generate the topology figures and the cross-domain
ParaView state used in the paper.

They run under ParaView's `pvpython` with the TopologyToolKit plugin available
(built/installed separately, e.g. `/usr/local/bin/plugins/TopologyToolKit`).

## Scripts

- `ttk_demo.py` - Reproducible smoke test on a synthetic Wavelet (RTData) field.
  Imports `topology_analysis.py` directly (no `trame_llm` dependency) and runs
  persistence, critical points, Morse-Smale, and simplification, writing
  `ttk_*.png` to `docs/images`.
  Usage: `pvpython ttk_demo.py [/path/to/catalyst_output]`

- `ttk_figures.py` - Publication figures from the FUN3D Catalyst pressure field:
  `fig_persistence` (matplotlib birth/death diagram), `fig_denoise_compare`
  (critical-point counts before vs after simplification), and `fig_critical_points`
  / `fig_morse_smale` over the wing geometry. Writes to `docs/images`.
  Usage: `pvpython ttk_figures.py [/path/to/catalyst_output] [timestep_index]`

- `ttk_state.py` - Builds the cross-domain ParaView state
  (`docs/images/ttk_scene.pvsm`): wing geometry, critical points colored by
  CriticalType, and streamlines seeded from the critical points colored by
  velocity magnitude. Open it in the GUI to frame the camera and save screenshots.
  Usage: `pvpython ttk_state.py`

## Data and ghost cells

The FUN3D figures expect the Catalyst output directory (per-rank
`volume_*_rank*.vtk` / `surface_*_rank*.vtk`). The ranks are reassembled as
`AppendDatasets` -> `RemoveGhostInformation` -> `CleantoGrid`. Removing ghosts is
required before topology: each rank carries a halo of ghost cells that are
duplicates of cells owned by neighbor ranks, and `CleantoGrid` merges coincident
points but does not drop those duplicates, so leaving them in produces spurious
critical points along the partition interfaces. The data path defaults to a local
absolute location; override it via the command-line argument where supported.
