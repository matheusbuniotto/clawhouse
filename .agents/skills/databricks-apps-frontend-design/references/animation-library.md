# Animation Library — Reusable Motion Patterns

## Entry Animations

### Fade Up (Default entrance)
```css
@keyframes fade-up {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}
.animate-fade-up {
  animation: fade-up 0.5s var(--ease-out) forwards;
}
```

### Scale In (Cards, modals)
```css
@keyframes scale-in {
  from { opacity: 0; transform: scale(0.95); }
  to { opacity: 1; transform: scale(1); }
}
```

### Slide In Right (Drawers, panels)
```css
@keyframes slide-in-right {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}
```

### Blur In (Premium reveal)
```css
@keyframes blur-in {
  from { opacity: 0; filter: blur(8px); transform: scale(1.02); }
  to { opacity: 1; filter: blur(0); transform: scale(1); }
}
```

## Stagger System

```css
/* Apply to parent container */
.stagger-children > * {
  opacity: 0;
  animation: fade-up 0.5s var(--ease-out) forwards;
}

/* Generate delays for up to 12 children */
.stagger-children > *:nth-child(1)  { animation-delay: 0ms; }
.stagger-children > *:nth-child(2)  { animation-delay: 60ms; }
.stagger-children > *:nth-child(3)  { animation-delay: 120ms; }
.stagger-children > *:nth-child(4)  { animation-delay: 180ms; }
.stagger-children > *:nth-child(5)  { animation-delay: 240ms; }
.stagger-children > *:nth-child(6)  { animation-delay: 300ms; }
.stagger-children > *:nth-child(7)  { animation-delay: 360ms; }
.stagger-children > *:nth-child(8)  { animation-delay: 420ms; }
.stagger-children > *:nth-child(9)  { animation-delay: 480ms; }
.stagger-children > *:nth-child(10) { animation-delay: 540ms; }
.stagger-children > *:nth-child(11) { animation-delay: 600ms; }
.stagger-children > *:nth-child(12) { animation-delay: 660ms; }
```

## State Animations

### Pulse Glow (CREATING/UPDATING)
```css
@keyframes pulse-glow {
  0%, 100% {
    box-shadow: 0 4px 24px rgba(0,0,0,0.3);
    border-color: var(--state-color);
  }
  50% {
    box-shadow: 0 4px 24px rgba(0,0,0,0.3), 0 0 20px var(--state-color-glow);
    border-color: color-mix(in srgb, var(--state-color) 60%, white);
  }
}
```

### Fade Away (DELETING)
```css
@keyframes fade-away {
  to { opacity: 0.2; filter: grayscale(50%) blur(1px); transform: scale(0.98); }
}
```

### Desaturate (ARCHIVED)
```css
.archived {
  opacity: 0.45;
  filter: grayscale(40%) brightness(0.9);
  transition: all 0.3s;
}
.archived:hover {
  opacity: 0.7;
  filter: grayscale(20%) brightness(1);
}
```

## SVG/D3 Animations

### Connection Data Flow
```css
@keyframes flow-dots {
  from { stroke-dashoffset: 20; }
  to { stroke-dashoffset: 0; }
}
.svg-connection-flowing {
  stroke-dasharray: 8 12;
  animation: flow-dots 2s linear infinite;
}
```

### Node Enter (grow from parent)
```css
@keyframes node-enter {
  from { opacity: 0; transform: scale(0.5); }
  to { opacity: 1; transform: scale(1); }
}
```

### Link Draw (SVG path animation)
```typescript
// D3 pattern: animate path drawing
link.transition()
  .duration(600)
  .ease(d3.easeCubicOut)
  .attrTween("d", function(d) {
    const previous = this.getAttribute("d") || "";
    const current = linkGenerator(d);
    return d3.interpolatePath(previous, current);
  });
```

## Micro-Interactions

### Button Press
```css
.btn-press:active {
  transform: scale(0.97);
  transition: transform 0.1s;
}
```

### Card Hover Lift
```css
.hover-lift {
  transition: transform 0.3s var(--ease-out), box-shadow 0.3s var(--ease-out);
}
.hover-lift:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
}
```

### Focus Ring (Accessibility)
```css
.focus-ring:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px var(--bg-deep), 0 0 0 4px var(--state-info);
}
```

## Live Indicators

### Breathing Dot
```css
@keyframes breathe-dot {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.4); opacity: 0.5; }
}
.live-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--state-active);
  position: relative;
}
.live-dot::after {
  content: '';
  position: absolute;
  inset: -3px;
  border-radius: 50%;
  background: var(--state-active);
  animation: breathe-dot 2s ease-in-out infinite;
  opacity: 0.3;
}
```

### Polling Spinner
```css
@keyframes spin-subtle {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.polling-indicator {
  width: 14px; height: 14px;
  border: 2px solid var(--border-default);
  border-top-color: var(--state-info);
  border-radius: 50%;
  animation: spin-subtle 1s linear infinite;
}
```
