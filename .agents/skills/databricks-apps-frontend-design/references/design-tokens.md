# Design Tokens — Complete CSS Custom Property System

## Surface Hierarchy (7 levels of depth)

```css
:root {
  /* Void → Deep → Surface → Elevated → Floating → Highlight → Accent */
  --bg-void:      #050508;   /* Behind everything */
  --bg-deep:      #0A0A0F;   /* App background */
  --bg-surface:   #1A1A2E;   /* Cards, panels */
  --bg-elevated:  #252540;   /* Hover states, elevated cards */
  --bg-floating:  #2D2D4A;   /* Dropdowns, tooltips, modals */
  --bg-highlight: #353560;   /* Active/selected states */
  --bg-accent:    #3D3D70;   /* Hover on active elements */
}
```

## Glass Surfaces (5 variants)

```css
:root {
  --glass-thin:   rgba(26, 26, 46, 0.4);   /* Overlays, backdrops */
  --glass-light:  rgba(26, 26, 46, 0.6);   /* Side panels */
  --glass-medium: rgba(26, 26, 46, 0.75);  /* Cards */
  --glass-heavy:  rgba(26, 26, 46, 0.88);  /* Primary cards */
  --glass-solid:  rgba(26, 26, 46, 0.95);  /* Modals, drawers */
}
```

## Text Hierarchy (5 levels)

```css
:root {
  --text-primary:   #FAFAFA;   /* Headings, primary content */
  --text-secondary: #A0A0B0;   /* Body text, descriptions */
  --text-tertiary:  #7B7B8E;   /* Captions, timestamps */
  --text-dim:       #5A5A6E;   /* Disabled, placeholders */
  --text-ghost:     #3A3A4E;   /* Barely visible, decorative */
}
```

## State Colors (with alpha variants)

```css
:root {
  --state-active:       #22c55e;
  --state-active-10:    rgba(34, 197, 94, 0.1);
  --state-active-20:    rgba(34, 197, 94, 0.2);
  --state-active-glow:  rgba(34, 197, 94, 0.3);

  --state-info:         #3b82f6;
  --state-info-10:      rgba(59, 130, 246, 0.1);
  --state-info-20:      rgba(59, 130, 246, 0.2);
  --state-info-glow:    rgba(59, 130, 246, 0.3);

  --state-warning:      #f59e0b;
  --state-warning-10:   rgba(245, 158, 11, 0.1);
  --state-warning-20:   rgba(245, 158, 11, 0.2);

  --state-error:        #ef4444;
  --state-error-10:     rgba(239, 68, 68, 0.1);
  --state-error-20:     rgba(239, 68, 68, 0.2);
  --state-error-glow:   rgba(239, 68, 68, 0.3);

  --state-muted:        #6b7280;
  --state-muted-10:     rgba(107, 114, 128, 0.1);
}
```

## Databricks Brand

```css
:root {
  --db-red:         #FF3621;
  --db-red-10:      rgba(255, 54, 33, 0.1);
  --db-red-glow:    rgba(255, 54, 33, 0.25);
  --db-teal:        #00D4AA;
  --db-teal-10:     rgba(0, 212, 170, 0.1);
  --db-teal-glow:   rgba(0, 212, 170, 0.25);
}
```

## Shadow Scale (5 levels)

```css
:root {
  --shadow-xs:  0 1px 3px rgba(0,0,0,0.2);
  --shadow-sm:  0 2px 8px rgba(0,0,0,0.25);
  --shadow-md:  0 4px 24px rgba(0,0,0,0.35);
  --shadow-lg:  0 8px 40px rgba(0,0,0,0.5);
  --shadow-xl:  0 16px 64px rgba(0,0,0,0.6);
  --shadow-glow: 0 0 30px var(--glow-color, rgba(59,130,246,0.2));
}
```

## Border System

```css
:root {
  --border-subtle:   rgba(255, 255, 255, 0.04);
  --border-default:  rgba(255, 255, 255, 0.08);
  --border-emphasis: rgba(255, 255, 255, 0.14);
  --border-strong:   rgba(255, 255, 255, 0.22);
}
```

## Radius Scale

```css
:root {
  --radius-xs:  4px;   /* Tags, small badges */
  --radius-sm:  8px;   /* Buttons, inputs */
  --radius-md:  12px;  /* Cards, panels */
  --radius-lg:  16px;  /* Modals, large cards */
  --radius-xl:  24px;  /* Hero sections, special elements */
  --radius-full: 9999px; /* Pills, avatars */
}
```

## Motion Timing

```css
:root {
  --ease-out:    cubic-bezier(0.16, 1, 0.3, 1);    /* Entrances */
  --ease-in-out: cubic-bezier(0.4, 0, 0.2, 1);     /* State changes */
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1); /* Bouncy */
  --ease-smooth: cubic-bezier(0.25, 0.1, 0.25, 1);  /* Subtle */

  --duration-fast:    150ms;
  --duration-normal:  300ms;
  --duration-slow:    500ms;
  --duration-enter:   400ms;
  --duration-exit:    250ms;
}
```
