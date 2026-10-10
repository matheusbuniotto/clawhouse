# D3.js v7 Patterns for React Integration

## Tree Layout with Premium Styling

### Setup Pattern
```typescript
import * as d3 from "d3";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";

// Track React roots for cleanup
const reactRootsRef = useRef<Root[]>([]);

// Cleanup on unmount
useEffect(() => {
  return () => {
    reactRootsRef.current.forEach(root => { try { root.unmount(); } catch {} });
    reactRootsRef.current = [];
  };
}, []);
```

### SVG Defs for Premium Effects
```typescript
function setupSvgDefs(svg: d3.Selection<SVGSVGElement, unknown, null, undefined>) {
  const defs = svg.append("defs");

  // Glow filter
  const glow = defs.append("filter").attr("id", "glow");
  glow.append("feGaussianBlur").attr("stdDeviation", "3").attr("result", "blur");
  const merge = glow.append("feMerge");
  merge.append("feMergeNode").attr("in", "blur");
  merge.append("feMergeNode").attr("in", "SourceGraphic");

  // Ambient glow (softer, wider)
  const ambient = defs.append("filter").attr("id", "ambient-glow");
  ambient.append("feGaussianBlur").attr("stdDeviation", "6").attr("result", "blur");

  return defs;
}
```

### Link Gradients (Dynamic per Connection)
```typescript
function createLinkGradients(
  defs: d3.Selection<SVGDefsElement, unknown, null, undefined>,
  links: d3.HierarchyPointLink<TreeDatum>[],
  getColor: (node: TreeDatum) => string,
) {
  // Remove old gradients
  defs.selectAll("linearGradient.link-grad").remove();

  links.forEach((link, i) => {
    const gradient = defs.append("linearGradient")
      .attr("class", "link-grad")
      .attr("id", `link-grad-${i}`)
      .attr("gradientUnits", "userSpaceOnUse")
      .attr("x1", link.source.x).attr("y1", link.source.y)
      .attr("x2", link.target.x).attr("y2", link.target.y);

    gradient.append("stop")
      .attr("offset", "0%")
      .attr("stop-color", getColor(link.source.data))
      .attr("stop-opacity", 0.6);

    gradient.append("stop")
      .attr("offset", "100%")
      .attr("stop-color", getColor(link.target.data))
      .attr("stop-opacity", 0.8);
  });
}
```

### Tree Layout with foreignObject React Cards
```typescript
const NODE_WIDTH = 240;
const NODE_HEIGHT = 80;
const H_SPACING = 280;
const V_SPACING = 160;

function renderTree(treeData: TreeDatum) {
  // Create hierarchy
  const root = d3.hierarchy<TreeDatum>(treeData);
  const layout = d3.tree<TreeDatum>()
    .nodeSize([H_SPACING, V_SPACING])
    .separation((a, b) => a.parent === b.parent ? 1 : 1.15);
  layout(root);

  // Link generator (top-down tree)
  const linkGen = d3.linkVertical<d3.HierarchyPointLink<TreeDatum>, d3.HierarchyPointNode<TreeDatum>>()
    .x(d => d.x)
    .y(d => d.y);

  // ... render links and nodes with transitions
}
```

### Animated Data Updates (Key Pattern)
```typescript
// ENTER: New nodes grow from parent position
nodeEnter
  .attr("transform", d => {
    const parent = prevPositions.get(d.parent?.data.id ?? "");
    const startX = parent?.x ?? d.x;
    const startY = parent?.y ?? d.y;
    return `translate(${startX},${startY})`;
  })
  .attr("opacity", 0);

// UPDATE + ENTER merged: transition to final position
nodeMerge
  .transition()
  .duration(400)
  .ease(d3.easeCubicOut)
  .attr("transform", d => `translate(${d.x},${d.y})`)
  .attr("opacity", 1);

// EXIT: Fade out
nodeExit
  .transition()
  .duration(300)
  .attr("opacity", 0)
  .remove();
```

### Zoom & Pan Setup
```typescript
const zoom = d3.zoom<SVGSVGElement, unknown>()
  .scaleExtent([0.2, 4])
  .on("zoom", (event) => {
    g.attr("transform", event.transform.toString());
  });

svg.call(zoom);
svg.on("dblclick.zoom", null); // Disable double-click zoom on background

// Fit to view
function fitToView() {
  const bounds = g.node()!.getBBox();
  const { clientWidth: w, clientHeight: h } = container;
  const scale = Math.min(
    (w - 80) / bounds.width,
    (h - 80) / bounds.height,
    1.5 // max scale
  );
  const tx = w / 2 - (bounds.x + bounds.width / 2) * scale;
  const ty = 40 - bounds.y * scale;
  svg.transition().duration(500)
    .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
}
```

## Performance Tips

1. **Reuse React roots** — Don't `createRoot` on every data update. Track by node ID and only create for new nodes.
2. **Use `key` function in D3 data joins** — `data(nodes, d => d.id)` ensures proper enter/update/exit.
3. **Debounce ResizeObserver** — Don't re-render tree on every pixel of window resize.
4. **Limit gradient count** — For large trees, share gradients by color pair rather than creating one per link.
5. **Use `will-change: transform`** during animation, remove after.
