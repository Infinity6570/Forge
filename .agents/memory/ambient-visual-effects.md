---
name: Ambient visual effects
description: Accessibility and readability decisions for Forge's decorative Sci-Fi background and glass panels.
---

Keep ambient particle and wave decoration scoped to Sci-Fi and the Cyber FX preference. Reduced-motion users receive static artwork rather than a continuous animation.

**Why:** The animated background should enhance Forge without compromising long-form chat readability or changing the clean Minimalist themes.

**How to apply:** Keep decorative layers non-interactive. The canvas must sit above the solid page background, not at a negative z-index, with the transparent app shell above it. Glass belongs on outer composited panels, not nested text surfaces; retain enough contrast and canvas brightness for the sphere and orbits to remain visible.

The user explicitly requires the clinic-style rotating sphere, satellite rings, linked particles, waves, mouse response, and click ripples to be visibly present throughout Forge's Sci-Fi interface.

**Why:** The user repeatedly reported that the effects were still invisible. Merely running a hidden canvas is not success.

**How to apply:** Verify the composed app visually, not just canvas pixels. Preserve FX off, reduced-motion static artwork, and hidden-tab pause behavior. Compositor hints and desynchronized Canvas 2D do not guarantee hardware rasterization or a particular frame rate.
