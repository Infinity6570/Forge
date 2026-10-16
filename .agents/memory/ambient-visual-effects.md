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

When an agent task is active, make the ambient sphere, orbits, and particle network visibly more energetic; restore the idle animation when work ends. Keep the reduced-motion variant static while updating its appearance to reflect state changes.

**Why:** The user wants the backdrop to react to agent work rather than remain a passive decoration.

**How to apply:** Drive renderer activity from the authoritative task/generation state, including while a task is pending. Smoothly intensify and settle visual properties without creating a separate RAF loop or forcing non-Sci-Fi themes to show the canvas.
