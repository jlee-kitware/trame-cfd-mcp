# Server-side spanwise loading and integrated pressure forces.
# Injected: NUM_STATIONS (int), PRESSURE_FIELD (str), VELOCITY_FIELD (str),
#           DENSITY_FIELD (str)
#
# Input: ExtractSurface of the full flow domain (vtkPolyData). Faces lying on
# the domain bounding box are the farfield/symmetry boundaries; every other
# face belongs to the body.
#
# Freestream comes from the inflow face (the bounding-box face with the most
# negative mean V.n). Drag is along the freestream velocity, lift is normal to
# it in the plane of the freestream and the body's thickness axis, and the span
# is the body's longest extent normal to the freestream.
#
# Output vtkTable columns (NUM_STATIONS rows):
#   eta, span_position, chord, lift_per_span, drag_per_span, cl, cd, cl_c_over_cref
# FieldData scalars: CL, CD, lift, drag, planform_area, semispan, mean_chord,
#   q_inf, p_inf, mach_like_speed, alpha_deg, stream_idx, span_idx, thickness_idx,
#   num_body_cells, lift_check

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk

inp = inputs[0].VTKObject
tbl = output


def _flag_error(code):
    a = vtk.vtkDoubleArray()
    a.SetName("error")
    a.InsertNextValue(float(code))
    tbl.AddColumn(a)


def _col(name, values):
    a = vtk.vtkDoubleArray()
    a.SetName(name)
    for v in values:
        a.InsertNextValue(float(v))
    tbl.AddColumn(a)


def _fd(name, value):
    a = vtk.vtkDoubleArray()
    a.SetName(name)
    a.InsertNextValue(float(value))
    tbl.GetFieldData().AddArray(a)


def _point_array(ds, name):
    arr = ds.GetPointData().GetArray(name)
    return None if arr is None else vtk_to_numpy(arr)


tri_f = vtk.vtkTriangleFilter()
tri_f.SetInputData(inp)
tri_f.PassVertsOff()
tri_f.PassLinesOff()
tri_f.Update()
surf = tri_f.GetOutput()

p_pt = _point_array(surf, PRESSURE_FIELD)
v_pt = _point_array(surf, VELOCITY_FIELD)
r_pt = _point_array(surf, DENSITY_FIELD) if DENSITY_FIELD else None

if p_pt is None or v_pt is None or surf.GetNumberOfCells() == 0:
    _flag_error(1)
else:
    pts = vtk_to_numpy(surf.GetPoints().GetData()).astype(float)
    conn = vtk_to_numpy(surf.GetPolys().GetConnectivityArray()).reshape(-1, 3)
    a, b, c = pts[conn[:, 0]], pts[conn[:, 1]], pts[conn[:, 2]]
    area_vec = 0.5 * np.cross(b - a, c - a)
    areas = np.linalg.norm(area_vec, axis=1)
    normals = area_vec / np.maximum(areas, 1e-300)[:, None]
    centers = (a + b + c) / 3.0
    p_cell = p_pt[conn].mean(axis=1)

    lo = pts.min(axis=0)
    hi = pts.max(axis=0)
    tol = 1e-6 * np.max(hi - lo)

    # A face is on the domain boundary when all three vertices share a bounding plane.
    face_planes = []
    on_boundary = np.zeros(len(conn), dtype=bool)
    for ax in range(3):
        for side, bound, outward in ((0, lo[ax], -1.0), (1, hi[ax], 1.0)):
            on_plane = np.all(np.abs(pts[conn][:, :, ax] - bound) < tol, axis=1)
            on_boundary |= on_plane
            face_planes.append((ax, outward, on_plane))

    # Inflow face: most negative mean V.n_outward.
    best = None
    for ax, outward, on_plane in face_planes:
        if not np.any(on_plane):
            continue
        vn = v_pt[conn[on_plane]].mean(axis=1)[:, ax] * outward
        score = float(np.sum(vn * areas[on_plane]) / np.sum(areas[on_plane]))
        if best is None or score < best[0]:
            best = (score, on_plane)
    inflow = best[1]
    w = areas[inflow]
    v_inf = (v_pt[conn[inflow]].mean(axis=1) * w[:, None]).sum(axis=0) / w.sum()
    p_inf = float((p_cell[inflow] * w).sum() / w.sum())
    rho_inf = 1.0
    if r_pt is not None:
        rho_inf = float((r_pt[conn[inflow]].mean(axis=1) * w).sum() / w.sum())
    speed = float(np.linalg.norm(v_inf))
    q_inf = 0.5 * rho_inf * speed * speed
    stream = v_inf / speed

    body = ~on_boundary
    if not np.any(body):
        _flag_error(2)
    else:
        bpts = pts[np.unique(conn[body])]
        blo, bhi = bpts.min(axis=0), bpts.max(axis=0)
        bmid = 0.5 * (blo + bhi)

        # Orient normals out of the body (positive enclosed volume).
        vol = np.sum(np.sum((centers[body] - bmid) * normals[body], axis=1) * areas[body]) / 3.0
        if vol < 0:
            normals = -normals

        stream_idx = int(np.argmax(np.abs(stream)))
        ext = bhi - blo
        others = [i for i in range(3) if i != stream_idx]
        span_idx = others[int(np.argmax(ext[others]))]
        thick_idx = [i for i in others if i != span_idx][0]
        span_hat = np.zeros(3)
        span_hat[span_idx] = 1.0
        up = np.zeros(3)
        up[thick_idx] = 1.0
        lift_hat = up - np.dot(up, stream) * stream
        lift_hat /= np.linalg.norm(lift_hat)
        alpha_deg = float(np.degrees(np.arctan2(np.dot(stream, up), np.dot(stream, np.eye(3)[stream_idx]) * np.sign(stream[stream_idx]))))

        pg = p_cell - p_inf
        f_cell = -(pg * areas)[:, None] * normals
        F = f_cell[body].sum(axis=0)
        lift = float(np.dot(F, lift_hat))
        drag = float(np.dot(F, stream))
        planform = 0.5 * float(np.sum(areas[body] * np.abs(normals[body, thick_idx])))
        semispan = float(ext[span_idx])
        mean_chord = planform / semispan if semispan > 0 else 0.0
        CL = lift / (q_inf * planform) if q_inf * planform > 0 else 0.0
        CD = drag / (q_inf * planform) if q_inf * planform > 0 else 0.0

        body_conn = conn[body]
        cells = vtk.vtkCellArray()
        offsets = np.arange(0, 3 * len(body_conn) + 1, 3, dtype=np.int64)
        cells.SetData(numpy_to_vtk(offsets, deep=True, array_type=vtk.VTK_ID_TYPE),
                      numpy_to_vtk(body_conn.ravel().astype(np.int64), deep=True, array_type=vtk.VTK_ID_TYPE))
        body_poly = vtk.vtkPolyData()
        body_poly.SetPoints(surf.GetPoints())
        body_poly.SetPolys(cells)
        pg_arr = numpy_to_vtk((p_pt - p_inf).astype(float), deep=True)
        pg_arr.SetName("pg")
        body_poly.GetPointData().AddArray(pg_arr)
        n_arr = numpy_to_vtk(normals[body].astype(float), deep=True)
        n_arr.SetName("n_out")
        body_poly.GetCellData().AddArray(n_arr)

        plane = vtk.vtkPlane()
        plane.SetNormal(*span_hat)
        cutter = vtk.vtkCutter()
        cutter.SetInputData(body_poly)
        cutter.SetCutFunction(plane)

        # Stop short of the tip so no station cuts the tip cap.
        eta = 0.97 * (np.arange(NUM_STATIONS) + 0.5) / NUM_STATIONS
        rows = []
        for e in eta:
            origin = bmid.copy()
            origin[span_idx] = blo[span_idx] + e * ext[span_idx]
            plane.SetOrigin(*origin)
            cutter.Update()
            sec = cutter.GetOutput()
            if sec.GetNumberOfCells() == 0 or sec.GetLines().GetNumberOfCells() == 0:
                rows.append((e, origin[span_idx], 0.0, 0.0, 0.0))
                continue
            spts = vtk_to_numpy(sec.GetPoints().GetData()).astype(float)
            sp = vtk_to_numpy(sec.GetPointData().GetArray("pg"))
            sn = vtk_to_numpy(sec.GetCellData().GetArray("n_out"))
            lines = vtk_to_numpy(sec.GetLines().GetConnectivityArray()).reshape(-1, 2)
            t = spts[lines[:, 1]] - spts[lines[:, 0]]
            seg_len = np.linalg.norm(t, axis=1)
            t_hat = t / np.maximum(seg_len, 1e-300)[:, None]
            n2 = sn - np.sum(sn * span_hat, axis=1)[:, None] * span_hat
            n2 = n2 - np.sum(n2 * t_hat, axis=1)[:, None] * t_hat
            n2 /= np.maximum(np.linalg.norm(n2, axis=1), 1e-300)[:, None]
            p_seg = 0.5 * (sp[lines[:, 0]] + sp[lines[:, 1]])
            f = -(p_seg * seg_len)[:, None] * n2
            fsum = f.sum(axis=0)
            s_along = spts @ stream
            chord = float(s_along.max() - s_along.min())
            rows.append((e, origin[span_idx], chord, float(np.dot(fsum, lift_hat)), float(np.dot(fsum, stream))))

        rows = np.array(rows)
        chord = rows[:, 2]
        lp = rows[:, 3]
        dp = rows[:, 4]
        safe = np.where(chord > 0, q_inf * chord, np.inf)
        cl = lp / safe
        cd = dp / safe
        cref = mean_chord if mean_chord > 0 else 1.0
        lift_check = float(np.sum(lp) * 0.97 * ext[span_idx] / NUM_STATIONS)

        _col("eta", rows[:, 0])
        _col("span_position", rows[:, 1])
        _col("chord", chord)
        _col("lift_per_span", lp)
        _col("drag_per_span", dp)
        _col("cl", cl)
        _col("cd", cd)
        _col("cl_c_over_cref", cl * chord / cref)

        for k, v in (("CL", CL), ("CD", CD), ("lift", lift), ("drag", drag),
                     ("planform_area", planform), ("semispan", semispan),
                     ("mean_chord", mean_chord), ("q_inf", q_inf), ("p_inf", p_inf),
                     ("rho_inf", rho_inf), ("freestream_speed", speed), ("alpha_deg", alpha_deg),
                     ("stream_idx", stream_idx), ("span_idx", span_idx),
                     ("thickness_idx", thick_idx), ("num_body_cells", int(np.sum(body))),
                     ("lift_check", lift_check)):
            _fd(k, v)
