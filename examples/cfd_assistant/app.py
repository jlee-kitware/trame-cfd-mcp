"""
CFD Assistant - Example app using trame-llm + paraview-llm

This shows how the pieces fit together:
1. trame provides the web app framework
2. trame-llm provides ParaViewMCP (exposes ParaView as tools)
3. paraview-llm provides ExtendedParaViewMCP (CFD tools) and CFDAssistant

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

# paraview-llm provides extended MCP and assistant
from paraview_llm import ExtendedParaViewMCP
from paraview_llm.assistant import create_assistant


class CFDAssistantApp:
    def __init__(self, data_file: str = None):
        # 1. Create trame app
        self.app = Lite()
        self.state = self.app.state
        self.ctrl = self.app.ctrl
        
        # 2. Setup ParaView MCP (from trame-llm)
        self.base_mcp = ParaViewMCP(self.app)
        
        # 3. Wrap with extended CFD tools
        self.extended_mcp = ExtendedParaViewMCP(self.base_mcp)
        
        # 4. Load data if provided
        self.data_source = None
        if data_file:
            from paraview import simple
            reader = simple.OpenDataFile(data_file)
            simple.UpdatePipeline()
            for name, proxy in simple.GetSources().items():
                if proxy == reader:
                    self.data_source = name[0]
                    break
        
        # 5. Create LLM assistant with semantic reasoning
        self.assistant = create_assistant(
            base_mcp=self.base_mcp,
            extended_mcp=self.extended_mcp,
            provider="openai",
            data_source=self.data_source or "data"
        )
        
        # State for UI
        self.state.user_message = ""
        self.state.chat_history = []
        self.state.processing = False
        
        # Build UI
        self._build_ui()
    
    def handle_query(self, user_message: str):
        """Process user query through assistant"""
        if not user_message.strip():
            return
        
        self.state.processing = True
        self.state.chat_history = [
            *self.state.chat_history,
            {"role": "user", "content": user_message}
        ]
        
        try:
            # Run through assistant
            result = self.assistant.execute(user_message)
            
            # Build response message
            response = result.get("response", "")
            
            # Add tool summary if tools were called
            tools = result.get("tools", [])
            if tools:
                response += "\n\n**Tools used:**\n"
                for tool in tools:
                    tool_name = tool.get("tool", "unknown")
                    tool_result = tool.get("result", {})
                    if isinstance(tool_result, dict) and "error" in tool_result:
                        response += f"- ❌ {tool_name}: {tool_result['error']}\n"
                    else:
                        response += f"- ✅ {tool_name}\n"
            
            self.state.chat_history = [
                *self.state.chat_history,
                {"role": "assistant", "content": response}
            ]
            
            # Update view
            self.ctrl.view_update()
            
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
    import sys
    data_file = sys.argv[1] if len(sys.argv) > 1 else None
    app = CFDAssistantApp(data_file)
    app.run()
