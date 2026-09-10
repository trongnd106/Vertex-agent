# Architecture Diagrams — SVG Cloud/Infra Diagrams

Create clean, dark-themed, professional SVG architecture diagrams as self-contained HTML files.

## Features
- Dark theme with JetBrains Mono font
- Color-coded component types
- Self-contained HTML (no external assets, works offline)
- Responsive layout

## Component Color Coding

| Type | Color | Example |
|------|-------|---------|
| Compute | Blue | API servers, Lambda functions, containers |
| Storage | Green | Databases, S3, file storage |
| Network | Purple | Load balancers, CDN, gateways |
| Security | Red | Auth services, WAF, encryption |
| Database | Orange | PostgreSQL, Redis, Elasticsearch |

## Layout Patterns

| Pattern | Description | Best For |
|---------|-------------|----------|
| Layered | Vertical stack: User → API → Services → Data | Web apps, microservices |
| Horizontal | Left-to-right flow | Data pipelines, request flows |
| Hub-and-Spoke | Central service with satellites | Message queues, event-driven |
| Grid | Matrix of components | System overview, infrastructure |

## HTML Output

Produces a single `.html` file that can be:
- Opened in any browser
- Screenshotted for docs
- Embedded in Notion/confluence
