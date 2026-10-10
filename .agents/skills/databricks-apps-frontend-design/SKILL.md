---
name: databricks-apps-frontend-design
description: Create extraordinary, production-grade frontend designs for Databricks Apps (APX/FastAPI+React). Invoke when building UI components, pages, data visualizations, dashboards, or interactive features for Databricks Apps. Covers premium dark themes, cinematic animations, D3.js/SVG visualizations, glass-morphism, gradient systems, and distinctive typography. Goes beyond generic AI aesthetics to deliver interfaces that feel custom-designed by a world-class studio.
---

# Databricks Apps Frontend Design

Create extraordinary frontend interfaces for Databricks Apps that obliterate generic AI aesthetics. Every interface should feel like it was designed by a premium studio — intentional, surprising, memorable.

This skill builds on `/databricks-app-apx` (FastAPI + React stack) and `/frontend-design` (aesthetic principles) but goes further with Databricks-specific patterns, data visualization excellence, and cinematic motion design.

## When to Invoke

- Building or redesigning UI components for a Databricks App
- Creating data visualizations (trees, graphs, charts, gauges, timelines)
- Designing dashboards, admin panels, or monitoring interfaces
- Adding animations, transitions, or micro-interactions
- Implementing dark themes, glass-morphism, or premium visual effects
- Any request mentioning "sexy", "premium", "modern", "dynamic", "polished" UI

## Design Philosophy: "Engineered Luxury"

### The Anti-Slop Manifesto

Generic AI frontends share these sins. **Never commit them**:
- Inter/Roboto/system fonts everywhere
- Purple-on-white gradient backgrounds
- Uniform border-radius on every element
- Identical card components in a grid
- No atmospheric depth — flat, clinical surfaces
- Animations that are either absent or gratuitous
- Cookie-cutter layouts from component library demos

### The Standard We Set

Every interface must have:
1. **A concept** — not just "dark dashboard" but "Mission Control for Database Topology" or "Cinematic Data Observatory"
2. **A signature element** — one thing the viewer remembers (a particular animation, a unique layout choice, a distinctive data viz)
3. **Atmospheric depth** — layers of transparency, blur, shadow, and light that create a sense of physical space
4. **Intentional restraint** — maximalism and minimalism both work; thoughtless middle ground never does

## Phase 1: Design Audit (Before Touching Code)

Before writing any code, answer these questions:

### Context
- What data is being displayed? What's the user's primary task?
- Who is the audience? (Korean enterprise customer demo? Internal tool? Investor pitch?)
- What emotional response should this evoke? (Confidence? Excitement? Calm authority?)

### Aesthetic Direction
Choose ONE primary direction and commit fully:

| Direction | Vibe | Key Techniques |
|-----------|------|----------------|
| **Constellation Network** | Space command center, data as stars | SVG particle fields, glow filters, orbital animations |
| **Glass Observatory** | Clean, translucent, floating UI | Backdrop-filter blur, layered transparency, frosted surfaces |
| **Neon Circuit** | Cyberpunk data terminal | Neon borders, scanline effects, monospace everything |
| **Brutalist Data** | Raw, powerful, unapologetic | Harsh contrasts, oversized type, grid-heavy, no border-radius |
| **Editorial Precision** | Magazine-quality, refined | Distinctive serif fonts, generous whitespace, subtle motion |
| **Organic Flow** | Natural, breathing, alive | Bezier curves, gradient meshes, breathing animations, fluid shapes |

### Databricks Brand Alignment
When building for customer-facing demos:
- **Primary accent**: Databricks Red `#FF3621` — use sparingly as a signature, not everywhere
- **Secondary**: Teal/Cyan `#00D4AA` — for active/healthy states
- **Blue system**: `#3B82F6` → `#1D4ED8` — for information, links, progress
- **Dark backgrounds**: `#0A0A0F` (deepest) → `#1A1A2E` (surface) → `#252540` (elevated)
- **Text**: `#FAFAFA` (primary) → `#A0A0B0` (secondary) → `#6B7280` (dim)

## Phase 2: Technical Stack (Databricks App Constraints)

### Framework: React 19 + APX Stack
- **Build**: Vite 6 (NOT Vite 7 — Node 18 constraint on Databricks Apps)
- **Routing**: TanStack Router (file-based)
- **Data fetching**: TanStack Query (polling for real-time)
- **Components**: shadcn/ui v4 (no `type` on Accordion, no `asChild` on Collapsible)
- **Styling**: Tailwind CSS v4 + CSS custom properties
- **TypeScript**: `erasableSyntaxOnly` — NO enums, use string union types
- **Visualization**: D3.js v7, SVG, Canvas, CSS animations

### Critical APX Constraints
- `erasableSyntaxOnly: true` → string union types, `import type` for type-only imports
- Manual `lib/api.ts` (Orval incompatible with Node 18)
- shadcn/ui v4 API differences from v3 — check component docs
- Vite proxy: use `http://127.0.0.1:8000` NOT `localhost` (IPv6 issue on macOS)

## Phase 3: Design System Implementation

### Typography
**Never use**: Inter, Roboto, Arial, system-ui as primary fonts.

**Recommended pairings for Databricks Apps**:
```css
/* Option A: Technical Precision */
--font-display: 'Instrument Sans', sans-serif;  /* Fontshare */
--font-body: 'Satoshi', sans-serif;             /* Fontshare */
--font-mono: 'JetBrains Mono', monospace;       /* Google Fonts */

/* Option B: Editorial Authority */
--font-display: 'Cabinet Grotesk', sans-serif;  /* Fontshare */
--font-body: 'General Sans', sans-serif;        /* Fontshare */
--font-mono: 'IBM Plex Mono', monospace;        /* Google Fonts */

/* Option C: Korean-Optimized */
--font-display: 'Pretendard', sans-serif;       /* For Korean text */
--font-body: 'Pretendard', sans-serif;
--font-mono: 'JetBrains Mono', monospace;
```

Load via Fontshare CDN (free, no API key) or Google Fonts.

### Color Architecture
Use CSS custom properties with semantic naming:
```css
:root {
  /* Surface layers (darkest to lightest) */
  --bg-void: #050508;
  --bg-deep: #0A0A0F;
  --bg-surface: #1A1A2E;
  --bg-elevated: #252540;
  --bg-floating: #2D2D4A;

  /* Glass surfaces */
  --glass-bg: rgba(26, 26, 46, 0.7);
  --glass-border: rgba(255, 255, 255, 0.06);
  --glass-hover: rgba(255, 255, 255, 0.12);

  /* State colors with alpha variants */
  --state-active: #22c55e;
  --state-active-glow: rgba(34, 197, 94, 0.2);
  --state-warning: #f59e0b;
  --state-error: #ef4444;
  --state-info: #3b82f6;
  --state-muted: #6b7280;
}
```

### Glass-Morphism Pattern (Core Building Block)
```css
.glass-card {
  background: var(--glass-bg);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid var(--glass-border);
  border-radius: 16px;
  box-shadow:
    0 4px 24px rgba(0, 0, 0, 0.3),
    inset 0 1px 0 rgba(255, 255, 255, 0.04);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.glass-card:hover {
  background: rgba(26, 26, 46, 0.85);
  border-color: var(--glass-hover);
  box-shadow:
    0 8px 40px rgba(0, 0, 0, 0.5),
    inset 0 1px 0 rgba(255, 255, 255, 0.06);
  transform: translateY(-1px);
}
```

### Gradient Borders (State-Aware)
```css
.state-border {
  position: relative;
  border: none;
}
.state-border::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  padding: 1px;
  background: linear-gradient(
    135deg,
    var(--state-color, #3b82f6) 0%,
    transparent 50%,
    var(--state-color, #3b82f6) 100%
  );
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask-composite: exclude;
  opacity: 0.4;
  transition: opacity 0.3s;
}
.state-border:hover::before { opacity: 0.8; }
```

## Phase 4: Animation Patterns

### Entrance Animations (Staggered Reveal)
```css
@keyframes reveal-up {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

.reveal-stagger > * {
  opacity: 0;
  animation: reveal-up 0.6s cubic-bezier(0.16, 1, 0.3, 1) forwards;
}
.reveal-stagger > *:nth-child(1) { animation-delay: 0ms; }
.reveal-stagger > *:nth-child(2) { animation-delay: 80ms; }
.reveal-stagger > *:nth-child(3) { animation-delay: 160ms; }
.reveal-stagger > *:nth-child(4) { animation-delay: 240ms; }
.reveal-stagger > *:nth-child(5) { animation-delay: 320ms; }
```

### State Pulse (for CREATING/UPDATING states)
```css
@keyframes state-pulse {
  0%, 100% {
    box-shadow: 0 0 0 0 var(--state-color-glow);
    border-color: var(--state-color);
  }
  50% {
    box-shadow: 0 0 20px 4px var(--state-color-glow);
    border-color: color-mix(in srgb, var(--state-color) 60%, white);
  }
}
```

### Data Flow Animation (SVG connections)
```css
@keyframes data-flow {
  from { stroke-dashoffset: 20; }
  to { stroke-dashoffset: 0; }
}
.connection-active {
  stroke-dasharray: 10 10;
  animation: data-flow 1.5s linear infinite;
}
```

### Breathing Glow (for live indicators)
```css
@keyframes breathe {
  0%, 100% { opacity: 0.4; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.2); }
}
.live-indicator::after {
  content: '';
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.3;
  animation: breathe 2s ease-in-out infinite;
}
```

## Phase 5: D3.js Visualization Patterns

### Tree/Graph Layout with Premium Styling
```typescript
// SVG gradient definitions for connections
function createLinkGradient(svg, id, startColor, endColor) {
  const gradient = svg.append("defs")
    .append("linearGradient")
    .attr("id", id)
    .attr("gradientUnits", "userSpaceOnUse");
  gradient.append("stop").attr("offset", "0%").attr("stop-color", startColor);
  gradient.append("stop").attr("offset", "100%").attr("stop-color", endColor);
}

// Glow filter for connections
function createGlowFilter(svg) {
  const filter = svg.append("defs").append("filter").attr("id", "glow");
  filter.append("feGaussianBlur").attr("stdDeviation", "3").attr("result", "blur");
  const merge = filter.append("feMerge");
  merge.append("feMergeNode").attr("in", "blur");
  merge.append("feMergeNode").attr("in", "SourceGraphic");
}
```

### foreignObject Pattern for React-in-SVG
```typescript
// Mount React components inside D3 SVG nodes
nodeGroups.each(function(d) {
  const fo = d3.select(this).select("foreignObject");
  const container = document.createElement("div");
  container.style.cssText = "width:100%;height:100%";
  fo.node().appendChild(container);

  const root = createRoot(container);
  root.render(<NodeCard data={d} />);
  // IMPORTANT: track roots for cleanup
  reactRootsRef.current.push(root);
});
```

## Phase 6: Component Patterns

### Premium Stat Card
```tsx
function StatCard({ label, value, trend, color }: StatCardProps) {
  return (
    <div className="glass-card px-5 py-4 group">
      <div className="text-[11px] uppercase tracking-wider text-text-dim mb-1">
        {label}
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-display font-bold" style={{ color }}>
          {value}
        </span>
        {trend && (
          <span className={cn("text-xs font-mono", trend > 0 ? "text-green-400" : "text-red-400")}>
            {trend > 0 ? "↑" : "↓"}{Math.abs(trend)}%
          </span>
        )}
      </div>
    </div>
  );
}
```

### Premium Status Badge
```tsx
function StatusBadge({ state, label }: { state: string; label: string }) {
  const color = STATE_COLORS[state] ?? "#6b7280";
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: `${color}15`,
        color: color,
        border: `1px solid ${color}30`,
      }}>
      <span className="w-1.5 h-1.5 rounded-full animate-pulse"
        style={{ backgroundColor: color }} />
      {label}
    </span>
  );
}
```

## Phase 7: Responsive & Performance

### Performance Checklist
- [ ] `React.memo` on cards rendered inside D3 foreignObject
- [ ] `useMemo` for layout computations (D3 tree, color calculations)
- [ ] `useCallback` for event handlers passed to D3
- [ ] CSS `will-change: transform` on animated elements (remove after animation)
- [ ] `contain: layout style paint` on card containers
- [ ] Avoid re-mounting React roots on every D3 update — reuse existing roots

### Responsive Constraints
- Databricks Apps are desktop-focused demo tools: min 1024px width
- Use `clamp()` for font sizes that adapt: `clamp(12px, 1.2vw, 16px)`
- Tree visualizations: fit-to-view on mount, manual zoom beyond that

## Anti-Patterns (Things That WILL Ruin Your Design)

| Anti-Pattern | Why It's Bad | What To Do Instead |
|---|---|---|
| Uniform border-radius everywhere | Looks like a component library demo | Vary: 4px for inputs, 12px for cards, 16px for modals, 50% for avatars |
| Same shadow on every card | No visual hierarchy | Light shadow (surface), medium (elevated), deep (floating/selected) |
| All text same opacity | No information hierarchy | Primary 100%, secondary 70%, dim 45% |
| Animations on everything | Noisy, distracting | Animate entry/exit, state changes, and ONE signature interaction |
| Solid color backgrounds | Flat, lifeless | Add subtle noise texture, gradient overlays, or depth layers |
| Emoji as icons | Unprofessional, inconsistent | Use Lucide React icons (already in APX stack) |

## Examples

### Example: Data Visualization Dashboard
User says: "Build a monitoring dashboard for Lakebase branches"
Result: Applies "Glass Observatory" direction — tree visualization with glass-morphism node cards, gradient connections, glow filters, staggered entrance animations, real-time polling indicators.

### Example: Interactive Tree
User says: "Create a branch topology viewer"
Result: D3.js hierarchical tree with `d3.tree()` layout, SVG gradient links, foreignObject React cards, zoom/pan, animated transitions on data change, premium tooltip on hover.

### Example: Pitch Slide
User says: "Build an animated pitch slide for autoscaling"
Result: Full-viewport cinematic slide with SVG gauge animation, particle effects, staggered stat reveals, live data overlay from TanStack Query, keyboard navigation.

## Resources

- `references/design-tokens.md`: Complete CSS custom property system
- `references/animation-library.md`: Reusable @keyframes and transition patterns
- `references/d3-patterns.md`: D3.js v7 patterns for React integration
- `references/component-gallery.md`: Premium component implementations
