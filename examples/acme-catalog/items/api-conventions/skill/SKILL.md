---
name: api-conventions
description: REST API conventions for Acme services. Use when designing or reviewing an HTTP endpoint.
---

# API conventions

## When to use
- Adding or changing a route
- Reviewing an OpenAPI diff

## Rules
- Plural nouns, kebab-case paths
- Errors follow RFC 9457 problem+json
- Never break a published field
