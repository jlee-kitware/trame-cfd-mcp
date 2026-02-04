"""
CFD Assistant - Example app using trame-llm + paraview-llm

This shows how the pieces fit together:
1. trame provides the web app framework
2. trame-llm provides ParaViewMCP (exposes ParaView as tools)
3. paraview-llm provides the orchestrator (CFD-aware query compilation)

Run:
    pip install trame trame-llm paraview-llm[openai]
    export OPENAI_API_KEY="sk-..."
    python app.py
"""

from trame.app import Lite
from trame.widgets import vuetify3, paraview
from trame.ui.vuetify3 import SinglePageLayout

# trame-llm provides the ParaView MCP
from trame_llm.paraview import ParaViewMCP

# paraview-llm provides the orchestrator
from paraview_llm import Orchestrator, TrameMCPAdapter


class CFDAssistant:
    def __init__(self):
        # 1. Create trame app
        self.app = Lite()
        self.state = self.app.state
        self.ctrl = self.app.ctrl
        
        # 2. Setup ParaView MCP (from trame-llm)
        self.paraview_mcp = ParaViewMCP(self.app)
        
        # 3. Wrap with our adapter
        self.adapter = TrameMCPAdapter(self.paraview_mcp)
        
        # 4. Create orchestrator (uses OpenAI by default)
        self.orchestrator = Orchestrator(mcp_client=self.adapter)
        
        # State for UI
        self.state.user_message = ""
        self.state.chat_history = []
        self.state.processing = False
        
        # Build UI
        self._build_ui()
    
    def handle_query(self, user_message: str):
        """Process user query through orchestrator"""
        if not user_message.strip():
            return
        
        self.state.processing = True
        self.state.chat_history = [
            *self.state.chat_history,
            {"role": "user", "content": user_message}
        ]
        
        try:
            # Run through orchestrator
            result = self.orchestrator.run(user_message)
            
            if result.get("success"):
                # Build response message
                response = f"**Reasoning:** {result['reasoning']}\n\n"
                response += f"**Executed {len(result['results'])} operations:**\n"
                for r in result['results']:
                    if 'error' in r:
                        response += f"- ❌ {r['tool']}: {r['error']}\n"
                    else:
                        response += f"- ✅ {r['tool']}: {r['result']}\n"
            else:
                response = f"**Error:** {result.get('error')}\n"
                if result.get('unresolved_fields'):
                    response += f"\nMissing fields: {result['unresolved_fields']}"
                if result.get('details'):
                    response += f"\nDetails: {result['details']}"
            
            self.state.chat_history = [
                *self.state.chat_history,
                {"role": "assistant", "content": response}
            ]
            
        except Exception as e:
            self.state.chat_history = [
                *self.state.chat_history,
                {"role": "assistant", "content": f"**Error:** {str(e)}"}
            ]
        
        self.state.processing = False
        self.state.user_message = ""
    
    def _build_ui(self):
        with SinglePageLayout(self.app) as layout:
            layout.title.set_text("CFD Assistant")
            
            with layout.content:
                with vuetify3.VContainer(fluid=True, classes="fill-height"):
                    with vuetify3.VRow(classes="fill-height"):
                        # Left: ParaView view
                        with vuetify3.VCol(cols=8):
                            view = paraview.VtkRemoteView(
                                self.app.render_window,
                                interactive_ratio=1,
                            )
                            self.ctrl.view_update = view.update
                        
                        # Right: Chat panel
                        with vuetify3.VCol(cols=4):
                            with vuetify3.VCard(classes="fill-height d-flex flex-column"):
                                vuetify3.VCardTitle("Chat")
                                
                                # Chat history
                                with vuetify3.VCardText(classes="flex-grow-1 overflow-auto"):
                                    with vuetify3.VList():
                                        with vuetify3.VListItem(
                                            v_for="(msg, i) in chat_history",
                                            key="i",
                                        ):
                                            vuetify3.VListItemTitle(
                                                "{{ msg.role === 'user' ? 'You' : 'Assistant' }}"
                                            )
                                            vuetify3.VListItemSubtitle(
                                                "{{ msg.content }}",
                                                style="white-space: pre-wrap"
                                            )
                                
                                # Input
                                with vuetify3.VCardActions():
                                    vuetify3.VTextField(
                                        v_model=("user_message", ""),
                                        label="Ask about your CFD data...",
                                        density="compact",
                                        hide_details=True,
                                        disabled=("processing",),
                                        __events=["keyup.enter"],
                                        keyup_enter=lambda: self.handle_query(self.state.user_message),
                                    )
                                    vuetify3.VBtn(
                                        "Send",
                                        color="primary",
                                        loading=("processing",),
                                        click=lambda: self.handle_query(self.state.user_message),
                                    )
    
    def run(self):
        self.app.start()


if __name__ == "__main__":
    app = CFDAssistant()
    app.run()
