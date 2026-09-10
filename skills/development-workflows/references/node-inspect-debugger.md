# Node.js Debugging with --inspect

## Quick Start: Node.js Built-in Debugger
```bash
node inspect script.js
```

Commands: `c(ontinue)`, `n(ext)`, `s(tep)`, `o(ut)`, `pause`, `.exit`, `watch(expr)`, `unwatch(expr)`, `repl`

## Remote Debugging via Chrome DevTools Protocol
```bash
node --inspect-brk script.js
# Opens WebSocket debugger on port 9229
# Connect via chrome://inspect
```

Use `--inspect` (no `-brk`) to avoid stopping at first line.

## Chrome DevTools Protocol CLI
```bash
npm install -g devtools-protocol-cli
node --inspect-brk script.js &
devtools-protocol list  # shows available targets
devtools-protocol connect <target-id>  # connects CLI debugger
```

## Debugging TypeScript
Use `tsx` or `ts-node` with --inspect:
```bash
npx tsx --inspect-brk src/server.ts
```

## VS Code Configuration (.vscode/launch.json)
```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "type": "node",
      "request": "attach",
      "name": "Attach to Node",
      "port": 9229,
      "restart": true,
      "skipFiles": ["<node_internals>/**"]
    }
  ]
}
```

## Pitfalls
1. `--inspect-brk` stops at first line — use `--inspect` to continue execution
2. Port 9229 must be accessible (open firewall, localhost only by default)
3. Node.js 8+ required for `node inspect` built-in debugger
4. Chrome DevTools Protocol version mismatch between Node.js and tools
5. Use `--inspect-publish-uid http` to expose beyond localhost when needed
