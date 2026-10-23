---
name: Usage chart rendering
description: Rendering constraint discovered for charts embedded in Forge's React/Vite UI.
---

For Forge's embedded daily usage graph, use the inline SVG implementation unless the Recharts runtime issue is diagnosed. Recharts 2.15.4 triggered an invalid hook call in the Vite browser preview even though React and ReactDOM were both 19.1.0 and Vite had `resolve.dedupe` enabled.

**Why:** The runtime error was isolated to Recharts rendering and disappeared after replacing it with SVG; leaving the library in place would make the telemetry panel fail at runtime despite a successful typecheck and build.

**How to apply:** Before reintroducing Recharts in Forge's live UI, reproduce the issue in a minimal component and verify that the hook dispatcher is shared. The current SVG chart supports responsive sizing, per-model stacks, and pointer/keyboard details.
