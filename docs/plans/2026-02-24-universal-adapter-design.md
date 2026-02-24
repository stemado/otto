# Universal Adapter — Simple Stakeholder Overview

**Date**: 2026-02-24
**Status**: Design
**Type**: Single-file static HTML (zero dependencies)
**Output**: `docs/universal-adapter.html`

## Purpose

A visual, PowerPoint-simple animated page that explains Otto's 4-phase journey using the "universal adapter" metaphor. Designed for mixed audiences (execs + engineers). No code, no jargon — just icons, connectors, and large captions.

## Core Metaphor

Legacy systems have no API. Otto **becomes** the API by adapting to whatever the system presents. When the system changes, Otto re-adapts. Like a universal travel adapter that fits any outlet — or a Transformer that integrates seamlessly with whatever it connects to.

## Layout

Full-viewport, single-screen experience. No scrolling needed.

- **Center stage**: Animated diagram with legacy systems (left), Otto hub (center), modern systems (right)
- **Caption area**: Large text below the diagram — one headline + one sub-caption per phase
- **Phase dots**: Bottom of screen, 4 dots showing current phase

## Phase States

All elements exist in the DOM from the start. Phases are CSS class changes on the same elements — no innerHTML swapping. This creates smooth evolution between states.

### Phase I — "Otto learns your portal."
- 1 legacy system (locked) → Otto → 1 user
- Connector reaches from Otto to portal, lock opens, data flows
- Caption: "You describe the task. Otto navigates the portal, handles the login, and brings back the data."

### Phase II — "Now it runs without you."
- User replaced by clock/schedule icon
- Connector becomes always-on, data flows continuously
- Caption: "Set a schedule. Otto runs the same workflow automatically — every day, every week, whenever you need."

### Phase III — "Every system gets an API."
- 3 legacy systems on left, 3 modern systems on right
- Otto grows into an "API" hub
- Caption: "Other systems call Otto directly. They get clean data back — never knowing a browser was involved."

### Phase IV — "Portals change. Otto adapts."
- One legacy system glitches/morphs
- Otto's connector reshapes to match
- No disruption on right side
- Caption: "When a portal updates its interface, Otto detects the change and adapts automatically."

## Technical

- Single-file HTML, same dark palette as showcase
- SVG connectors with animated data flow (dashes/dots moving along paths)
- CSS animations for glows, pulses, state transitions
- JS manages phase state via CSS classes
- Auto-play ~8s per phase, clickable phase dots to jump
