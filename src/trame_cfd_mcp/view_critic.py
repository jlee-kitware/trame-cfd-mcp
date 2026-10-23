"""
View critic: the look-and-correct loop.

Renders the current view, runs cheap deterministic checks against pipeline
state, and only then asks a vision model the perceptual questions that
cannot be computed. Returns findings plus suggested corrective tool calls
the LLM can execute with tools it already has.

Design rule: never infer what can be computed. Anything readable from the
proxy, the camera, or an array range is checked in Python. The vision model
is asked only about occlusion, framing and legibility.
"""

import base64
import json
import os
import urllib.request

from paraview import simple


VISION_URL = os.environ.get("CFD_MCP_VISION_URL", "")
VISION_MODEL = os.environ.get("CFD_MCP_VISION_MODEL", "qwen2.5-vl:32b")
VISION_KEY = os.environ.get("CFD_MCP_VISION_KEY", "")

_VISION_PROMPT = """You are inspecting a scientific visualization rendered by ParaView.

The user asked for: {question}

Answer ONLY about what is visually apparent. Do not speculate about physics,
values, or anything you cannot see. Reply with strict JSON, no prose:

{{
  "shows_requested_feature": true|false|"unclear",
  "occluded": true|false,
  "framing": "good"|"too_far"|"too_close"|"cut_off"|"off_screen",
  "legible": true|false,
  "issues": ["short phrase", ...],
  "note": "one sentence, what you actually see"
}}
"""


def _bounds_ok(b):
    return b is not None and len(b) == 6 and b[0] <= b[1] and b[2] <= b[3] and b[4] <= b[5]


def _center(b):
    return ((b[0] + b[1]) / 2.0, (b[2] + b[3]) / 2.0, (b[4] + b[5]) / 2.0)


def _diagonal(b):
    return ((b[1] - b[0]) ** 2 + (b[3] - b[2]) ** 2 + (b[5] - b[4]) ** 2) ** 0.5


def _inside(pt, b, pad=0.0):
    return (
        b[0] - pad <= pt[0] <= b[1] + pad
        and b[2] - pad <= pt[1] <= b[3] + pad
        and b[4] - pad <= pt[2] <= b[5] + pad
    )


class ViewCritic:
    """Inspects the rendered view and reports what is wrong with it."""

    def __init__(self, analysis, app=None):
        self._analysis = analysis
        self._app = app
        self._attempts = {}

    # ------------------------------------------------------------------
    # deterministic checks
    # ------------------------------------------------------------------

    def _target(self, proxy_name):
        if proxy_name:
            src = simple.FindSource(proxy_name)
            if src is not None:
                return proxy_name, src
        src = simple.GetActiveSource()
        name = ""
        for key, value in simple.GetSources().items():
            if value is src:
                name = key[0]
                break
        return name, src

    def _checks(self, proxy_name):
        """Everything computable. Runs before any vision call."""
        issues = []
        actions = []
        facts = {}

        view = simple.GetActiveView()
        name, src = self._target(proxy_name)
        facts["target"] = name

        if src is None:
            issues.append("no active source")
            actions.append({"tool": "list_data", "args": {}, "why": "nothing is selected"})
            return facts, issues, actions, True

        info = src.GetDataInformation()
        n_pts = info.GetNumberOfPoints()
        n_cells = info.GetNumberOfCells()
        facts["points"] = n_pts
        facts["cells"] = n_cells

        if n_pts == 0 and n_cells == 0:
            issues.append("filter produced no geometry")
            actions.append({
                "tool": "update_list_property",
                "args": {"property_name": "Isosurfaces", "property_value": "[lower value]",
                         "proxy_name": name},
                "why": "empty output usually means the threshold is above the field range",
            })
            return facts, issues, actions, True

        bounds = info.GetBounds()
        facts["bounds"] = list(bounds) if _bounds_ok(bounds) else None
        if not _bounds_ok(bounds):
            issues.append("degenerate bounds")
            return facts, issues, actions, True
        return self._view_checks(view, name, src, bounds, facts, issues, actions)

    def _view_checks(self, view, name, src, bounds, facts, issues, actions):
        """Camera, visibility and coloring checks. Cheap, no rendering needed."""
        blocking = False

        rep = None
        try:
            rep = simple.GetDisplayProperties(src, view)
        except Exception:
            pass

        if rep is not None and not getattr(rep, "Visibility", 1):
            issues.append("target is hidden")
            actions.append({"tool": "show_or_hide",
                            "args": {"action": "show", "proxy_name": name},
                            "why": "the proxy exists but is not visible"})
            blocking = True

        diag = _diagonal(bounds)
        center = _center(bounds)

        try:
            cam_pos = tuple(view.CameraPosition)
            focal = tuple(view.CameraFocalPoint)
        except Exception:
            cam_pos = focal = None

        if cam_pos and _inside(cam_pos, bounds):
            issues.append("camera is inside the geometry")
            actions.append({"tool": "reset_camera", "args": {},
                            "why": "the eye point sits within the data bounds"})
            blocking = True

        if focal and diag > 0:
            off = sum((focal[i] - center[i]) ** 2 for i in range(3)) ** 0.5
            facts["focal_offset_fraction"] = round(off / diag, 3)
            if off > 1.5 * diag:
                issues.append("camera is not pointed at the target")
                actions.append({"tool": "focus_on", "args": {"proxy_name": name},
                                "why": "focal point is far from the target centroid"})
                blocking = True

        self._color_check(rep, src, name, facts, issues, actions)
        return facts, issues, actions, blocking

    def _color_check(self, rep, src, name, facts, issues, actions):
        """A colormap over a constant range shows nothing. That is computable."""
        if rep is None:
            return
        try:
            assoc, array = rep.ColorArrayName[0], rep.ColorArrayName[1]
        except Exception:
            return
        if not array:
            return
        facts["color_by"] = array
        info = src.GetDataInformation()
        holder = (info.GetCellDataInformation() if assoc == "CELLS"
                  else info.GetPointDataInformation())
        ai = holder.GetArrayInformation(array)
        if ai is None:
            issues.append("coloring by an array that is not on this output")
            actions.append({"tool": "get_fields", "args": {},
                            "why": "the colored array is missing from the target"})
            return
        rng = ai.GetComponentRange(-1)
        facts["color_range"] = [rng[0], rng[1]]
        if rng[0] == rng[1]:
            issues.append("colored field is constant over the visible geometry")
            actions.append({"tool": "update_color",
                            "args": {"proxy_name": name, "field_name": "[a varying field]"},
                            "why": "a flat range renders as a single colour"})

    # ------------------------------------------------------------------
    # vision
    # ------------------------------------------------------------------

    def _capture(self, width, height):
        out = os.environ.get("CFD_MCP_CRITIC_DIR", "output")
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, "_critic_view.png")
        result = self._analysis.save_screenshot(path, width, height)
        if isinstance(result, dict) and "error" in result:
            return None, result["error"]
        return path, None

    def _ask_vision(self, image_path, question):
        """OpenAI-compatible chat/completions with an image part.

        Works against a local Ollama or vLLM endpoint as well as a hosted one,
        so proprietary geometry never has to leave the network.
        """
        if not VISION_URL:
            return None, "vision endpoint not configured"
        with open(image_path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode("ascii")
        payload = {
            "model": VISION_MODEL,
            "max_tokens": 400,
            "temperature": 0,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text",
                     "text": _VISION_PROMPT.format(question=question or "a clear view of the result")},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }],
        }
        req = urllib.request.Request(
            VISION_URL.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {VISION_KEY}"} if VISION_KEY else {})},
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            text = body["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            return None, f"vision call failed: {exc}"
        return self._parse(text)

    @staticmethod
    def _parse(text):
        """Open-weight models fence their JSON. Strip it before parsing."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        try:
            return json.loads(cleaned.strip()), None
        except Exception:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if 0 <= start < end:
                try:
                    return json.loads(cleaned[start:end + 1]), None
                except Exception:
                    pass
        return None, "vision model did not return usable JSON"

    @staticmethod
    def _vision_actions(verdict, name):
        """Map perceptual findings onto tools that already exist."""
        actions = []
        if verdict.get("occluded"):
            actions.append({"tool": "update_display_property",
                            "args": {"property_name": "Opacity", "value": 0.4,
                                     "proxy_name": "[the occluding surface]"},
                            "why": "the requested feature is hidden behind geometry"})
        framing = verdict.get("framing")
        if framing in ("too_far", "too_close", "cut_off", "off_screen"):
            actions.append({"tool": "focus_on", "args": {"proxy_name": name},
                            "why": f"framing reported as {framing}"})
        if verdict.get("shows_requested_feature") is False:
            actions.append({"tool": "update_list_property",
                            "args": {"property_name": "Isosurfaces",
                                     "property_value": "[lower value]", "proxy_name": name},
                            "why": "the requested feature is not visible in the render"})
        return actions

    # ------------------------------------------------------------------
    # entry point
    # ------------------------------------------------------------------

    def critique(self, question="", proxy_name="", width=1024, height=768,
                 use_vision=True, max_attempts=2):
        facts, issues, actions, blocking = self._checks(proxy_name)
        name = facts.get("target", "")

        key = f"{name}|{question}"
        attempt = self._attempts.get(key, 0) + 1
        self._attempts[key] = attempt

        result = {
            "type": "view_critique",
            "attempt": attempt,
            "checks": facts,
            "issues": list(issues),
            "suggested_actions": list(actions),
            "vision": None,
        }

        if attempt > max_attempts:
            result["verdict"] = "stop"
            result["tip"] = ("Correction limit reached. Describe what is on screen and "
                             "hand control back to the user rather than adjusting again.")
            return result

        if blocking:
            result["verdict"] = "blocked"
            result["tip"] = ("The view has a problem that is computable without looking at it. "
                             "Apply the first suggested action, then call inspect_view again.")
            return result
        return self._finish(result, question, name, width, height, use_vision)

    def _finish(self, result, question, name, width, height, use_vision):
        """Pipeline state is sound. Now, and only now, look at the pixels."""
        if not use_vision:
            result["verdict"] = "ok" if not result["issues"] else "issues"
            result["tip"] = "Deterministic checks only; vision inspection was skipped."
            return result

        path, err = self._capture(width, height)
        if err:
            result["verdict"] = "unknown"
            result["tip"] = f"Could not capture the view ({err}). Report the checks above."
            return result
        result["image"] = path

        verdict, err = self._ask_vision(path, question)
        if err:
            result["verdict"] = "ok" if not result["issues"] else "issues"
            result["vision_error"] = err
            result["tip"] = ("Vision inspection unavailable, so the computable checks are all "
                             "that ran. Do not claim the image was inspected.")
            return result

        result["vision"] = verdict
        result["issues"].extend(verdict.get("issues", []) or [])
        result["suggested_actions"].extend(self._vision_actions(verdict, name))
        result["verdict"] = "ok" if not result["issues"] else "issues"
        result["tip"] = (
            "The view looks correct; describe it to the user."
            if result["verdict"] == "ok" else
            "Apply at most one suggested action, then call inspect_view again to confirm. "
            "Tell the user what you corrected and why."
        )
        return result
