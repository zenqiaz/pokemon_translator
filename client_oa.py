import os, sys, json, asyncio
from typing import Optional
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from anthropic import Anthropic
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()  # load environment variables from .env
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

class MCPClient:
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.oa = OpenAI()  # uses OPENAI_API_KEY

    async def connect_to_server(self, server_script_path: str):
        """Connect to an MCP server
        
        Args:
            server_script_path: Path to the server script (.py or .js)
        """
        is_python = server_script_path.endswith('.py')
        is_js = server_script_path.endswith('.js')
        if not (is_python or is_js):
            raise ValueError("Server script must be a .py or .js file")
            
        command = "python" if is_python else "node"
        server_params = StdioServerParameters(
            command=command,
            args=[server_script_path],
            env=None
        )
        
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
        
        await self.session.initialize()
        
        # List available tools
        response = await self.session.list_tools()
        tools = response.tools
        print("\nConnected to server with tools:", [tool.name for tool in tools])

    async def _mcp_call_and_text(self, tool_name: str, tool_args: dict) -> str:
        """
        Call an MCP tool and return best-effort text. Falls back to JSON if needed.
        """
        if self.session is None:
            raise RuntimeError("MCP session not initialized")
        res = await self.session.call_tool(tool_name, tool_args)
        # Prefer the first text block
        for c in getattr(res, "content", []) or []:
            if getattr(c, "type", None) == "text":
                return c.text
        # Fallback: serialize the blocks
        try:
            return json.dumps([getattr(c, "__dict__", str(c)) for c in res.content], ensure_ascii=False)
        except Exception:
            return str(res.content)

    async def process_query(self, query: str) -> str:
        """Process a query using Claude and available tools"""
        messages = [
            {
                "role": "user",
                "content": query
            }
        ]

        tl = await self.session.list_tools()
        oa_tools = [{
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.inputSchema or {"type": "object", "properties": {}}
            }
        } for t in tl.tools]

        messages = [{"role": "user", "content": query}]

        # 1) First turn: let the model decide to call a tool
        r1 = self.oa.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=oa_tools,
            tool_choice="auto",
            temperature=0,
        )
        first = r1.choices[0].message
        tool_calls = first.tool_calls or []

        # If no tool is requested, return the model’s text
        if not tool_calls:
            return (first.content or "").strip()

        # 2) Append the assistant tool-calls message (required by OpenAI protocol)
        messages.append({
            "role": "assistant",
            "content": first.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                } for tc in tool_calls
            ],
        })

        # 3) Execute each requested tool via MCP and append tool results
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_text = await self._mcp_call_and_text(name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": name,
                "content": tool_text,
            })

        # 4) Final turn: let the model produce the answer conditioned on tool results
        r2 = self.oa.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=0,
        )
        return (r2.choices[0].message.content or "").strip()

    async def chat_loop(self):
        """Run an interactive chat loop"""
        print("\nMCP Client Started!")
        print("Type your queries or 'quit' to exit.")
        
        while True:
            try:
                query = input("\nQuery: ").strip()
                
                if query.lower() == 'quit':
                    break
                    
                response = await self.process_query(query)
                print("\n" + response)
                    
            except Exception as e:
                print(f"\nError: {str(e)}")
    
    async def cleanup(self):
        """Clean up resources"""
        await self.exit_stack.aclose()

async def main():
    if len(sys.argv) < 2:
        print("Usage: python client.py <path_to_server_script>")
        sys.exit(1)
        
    client = MCPClient()
    try:
        await client.connect_to_server(sys.argv[1])
        await client.chat_loop()
    finally:
        await client.cleanup()

if __name__ == "__main__":
    import sys
    asyncio.run(main())