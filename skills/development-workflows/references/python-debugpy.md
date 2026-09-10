# Python Debugging with debugpy

## Quick Start: pdb REPL
```bash
python3 -m pdb script.py
```

pdb commands: `n(ext)` — next line, `c(ontinue)` — run to next breakpoint, `l(ist)` — show current context, `p(rint)` — print expression, `b(reak)` — set breakpoint, `w(here)` — show stack trace, `s(tep)` — step into function, `q(uit)` — exit

## Remote Debugging with debugpy
```bash
pip install debugpy
```

**In your script:**
```python
import debugpy
debugpy.listen(("0.0.0.0", 5678))
debugpy.wait_for_client()  # blocks until debugger attaches
```

**Alternative: non-blocking startup**
```python
debugpy.listen(5678)
debugpy.wait_for_client(timeout=5)  # timeout if no client in 5s
```

## DAP Client Connection

```json
{
  "type": "python",
  "request": "attach",
  "connect": {
    "host": "localhost",
    "port": 5678
  }
}
```

## Common Workflow
1. Insert `debugpy.breakpoint()` at desired pause point
2. Start program
3. Attach DAP client
4. Step through, inspect variables, set more breakpoints
5. Remove all debugger statements before committing

## Pitfalls
1. `wait_for_client()` blocks indefinitely — use timeout variant
2. Firewall may block port 5678
3. Debugpy can affect timing — race conditions may not reproduce
4. Remove `debugpy` imports before production deployment
5. Only one DAP client can connect at a time
