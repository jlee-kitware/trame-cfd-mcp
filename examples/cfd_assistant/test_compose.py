"""Headless validation: can the planner compose topology + CFD tools from one prompt?"""
import os, sys, glob, asyncio
sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-cfd-mcp/src')
sys.path.insert(0, '/Users/jeff.lee/gitsync/trame-llm/src')
from dotenv import load_dotenv
load_dotenv()

from paraview import simple

class _Trig:
    def exists(self): return False
    def __call__(self, *a, **k): return None
class _Ctrl:
    def __getattr__(self, n): return _Trig()
class MinimalApp:
    def __init__(self): self.ctrl = _Ctrl()
    def update(self): pass

from trame_cfd_mcp import WorkflowMCP
from trame_llm.paraview import ParaViewMCP
from trame_llm.core import LLMClient

DATA = "/Users/jeff.lee/gitsync/fun3d/fun3d_test/flow_demo2/catalyst_output"
TS = "000051"
TOOL_CALLS = []

def load_clean_volume():
    rs = [simple.OpenDataFile(f) for f in sorted(glob.glob(os.path.join(DATA, "volume_%s_rank*.vtk" % TS)))]
    for r in rs: simple.UpdatePipeline(proxy=r)
    m = simple.AppendDatasets(Input=rs); simple.UpdatePipeline(proxy=m)
    g = simple.RemoveGhostInformation(Input=m); simple.UpdatePipeline(proxy=g)
    c = simple.CleantoGrid(Input=g); simple.UpdatePipeline(proxy=c)
    return c

async def main():
    simple.LoadPlugin('/usr/local/bin/plugins/TopologyToolKit/TopologyToolKit.so', remote=False, ns=globals())
    vol = load_clean_volume()
    view = simple.CreateRenderView(); view.ViewSize = [1200, 800]
    simple.SetActiveView(view); simple.SetActiveSource(vol)
    simple.Show(vol, view); simple.ResetCamera(view)

    wmcp = WorkflowMCP(ParaViewMCP(MinimalApp()))

    def progress(ptype, msg):
        tag = str(ptype).split('.')[-1]
        s = str(msg).replace("\n", " ")
        if tag == "MCP_SELECTION":
            TOOL_CALLS.append(s)
        if len(s) > 260: s = s[:260] + "..."
        print("   [%s] %s" % (tag, s), flush=True)

    llm = LLMClient(max_iteractions=14)
    llm.set_progress_handler(progress)
    llm.register_mcp(wmcp)
    await llm.initialize()
    print("%d tools | model=%s\n" % (len(llm.tools), llm.config.model))

    prompt = ("Show the critical points of the pressure field. Then trace streamlines "
              "from those critical points, colored by velocity magnitude. "
              "Save the result to output/compose_test.png")
    print("PROMPT:", prompt)
    print("=" * 70)
    await llm.process_prompt(prompt)
    print("=" * 70)
    print("TOOL CALL SEQUENCE (%d):" % len(TOOL_CALLS))
    for i, t in enumerate(TOOL_CALLS, 1):
        print("  %d. %s" % (i, t[:180]))

if __name__ == "__main__":
    asyncio.run(main())
