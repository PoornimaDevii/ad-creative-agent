import subprocess
import json
import threading
import queue
import time
from fastapi import FastAPI, HTTPException

app = FastAPI()

MCP_COMMAND = ["python", "mcp_server.py", "stdio"]
TIMEOUT = 25


# ================= MCP CLIENT =================

class MCPClient:
    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()
        self.q = queue.Queue()
        self.start()

    def start(self):
        self.proc = subprocess.Popen(
            MCP_COMMAND,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self):
        for line in self.proc.stdout:
            try:
                self.q.put(json.loads(line.strip()))
            except:
                continue

    def _read_stderr(self):
        for line in self.proc.stderr:
            print("MCP STDERR:", line.strip())

    def call_tool(self, tool_name, arguments):
        with self.lock:
            req = {
                "type": "call_tool",
                "tool": tool_name,
                "arguments": arguments
            }

            try:
                self.proc.stdin.write(json.dumps(req) + "\n")
                self.proc.stdin.flush()

                start = time.time()
                while time.time() - start < TIMEOUT:
                    try:
                        return self.q.get(timeout=0.5)
                    except queue.Empty:
                        continue

                raise TimeoutError("MCP timeout")

            except Exception as e:
                self.start()
                raise e


mcp = MCPClient()


# ================= ROUTES =================

@app.get("/")
def health():
    return {"status": "ok", "service": "adcp-mcp-wrapper"}


# 🔹 1. List formats (maps to your tool)
@app.post("/list_formats")
def list_formats(payload: dict = {}):
    try:
        result = mcp.call_tool("list_creative_formats", payload)
        return result
    except TimeoutError:
        raise HTTPException(504, "Timeout from MCP")
    except Exception as e:
        raise HTTPException(500, str(e))


# 🔹 2. Preview creative (maps to your tool)
@app.post("/preview")
def preview(payload: dict):
    try:
        result = mcp.call_tool("preview_creative", payload)
        return result
    except TimeoutError:
        raise HTTPException(504, "Timeout from MCP")
    except Exception as e:
        raise HTTPException(500, str(e))
