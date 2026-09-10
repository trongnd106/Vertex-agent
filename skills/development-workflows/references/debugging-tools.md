# Debugging Tools — Python (debugpy) and Node.js (--inspect)

Set up remote debugging sessions for Python (via debugpy/DAP) and Node.js (via Chrome DevTools Protocol via CLI).

## Python Debugging (debugpy)

Use `python-debugpy` when you need to step through code, inspect variables, set breakpoints, and follow execution paths in Python applications.

### Quick Start: pdb REPL
```bash
python3 -m pdb script.py
# Commands: n(ext), c(ontinue), l(ist), p(rint), b(reak), w(here), s(tep)
```

### Remote Debugging with debugpy
```bash
pip install debugpy

# In script, add at entry point:
import debugpy
debugpy.listen(("0.0.0.0", 5678))
debugpy.wait_for_client()  # blocks until debugger attaches

# Connect via DAP client or VSCode:
# {"type": "python", "request": "attach", "connect": {"host": "localhost", "port": 5678}}
```

### Common Workflow
1. Insert `debugpy.breakpoint()` at pause point
2. Start the program
3. Attach DAP client
4. Step through and inspect
5. Remove breakpoints when done

## Node.js Debugging (--inspect)

Use `node-inspect-debugger` when you need to debug JavaScript/TypeScript applications via the Chrome DevTools Protocol.

### Quick Start: Built-in Debugger
```bash
node inspect script.js
# Commands: c(ontinue), n(ext), s(tep), o(ut), pause, restart
```

### Remote Debugging
```bash
node --inspect-brk script.js
# Opens WebSocket debugger on port 9229
# Connect via chrome://inspect or CLI inspector
```

### Using the Chrome DevTools Protocol CLI
```bash
npm install -g devtools-protocol-cli
node --inspect-brk script.js &
devtools-protocol list
devtools-protocol connect <target-id>
```

## Which Tool to Use

| Runtime | Debug CLI | Remote (DAP/CDP) | When |
|---------|-----------|-------------------|------|
| Python | `python3 -m pdb` | debugpy on port 5678 | Python apps, scripts, FastAPI |
| Node.js | `node inspect` | `--inspect-brk` on port 9229 | JS/TS apps, Express, Next.js |

## Common Pitfalls
1. **debugpy blocks startup** — `wait_for_client()` halts execution until connected. Use `timeout` variant for non-blocking.
2. **--inspect-brk stops at first line** — Use `--inspect` (no `-brk`) to avoid stopping immediately.
3. **Firewall blocks ports** — Ensure ports 5678 (debugpy) or 9229 (Node) are accessible.
4. **Clean up breakpoints** — Always remove debugger statements before committing.
5. **DAP requires JSON config** — Know the structure: `{"type":"python","request":"attach","connect":{"host":"localhost","port":5678}}`.
