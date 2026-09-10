# Excalidraw — Hand-Drawn Style Diagrams

Create informal, hand-drawn style diagrams for architecture, flow, sequence, or brainstorming.

## Element Types

| Type | Code | Example |
|------|------|---------|
| Rectangle | `type: "rectangle"` | Main blocks, services, components |
| Diamond | `type: "diamond"` | Decision points, conditionals |
| Ellipse | `type: "ellipse"` | Users, external entities, data sources |
| Arrow | `type: "arrow"` | Connections, data flow, dependencies |
| Text | `type: "text"` | Labels, descriptions |

## JSON Format

```json
{
  "type": "excalidraw",
  "version": 2,
  "elements": [
    {
      "type": "rectangle",
      "x": 100, "y": 100,
      "width": 200, "height": 80,
      "id": "rect-1",
      "backgroundColor": "#e8f4fd",
      "strokeColor": "#1971c2",
      "text": "API Gateway"
    }
  ]
}
```

## Upload Script

Requires `cryptography` pip package. The Excalidraw viewer loads .excalidraw files directly.

## Architecture Diagram Patterns

Common layouts:
- **Layered**: User → API → Services → Database (vertical)
- **Flow**: Input → Process → Output (horizontal)
- **Network**: Components with connecting lines showing data flow
