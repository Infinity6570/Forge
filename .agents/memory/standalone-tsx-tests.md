---
name: Standalone TSX tests
description: JSX runtime expectations when testing React components outside Vite.
---

Standalone tests run through `tsx --test` may transpile TSX with the classic JSX runtime even though the Vite app build uses its configured React transform. Components rendered in those tests should import the React namespace explicitly.

**Why:** A component that built and typechecked under Vite threw `React is not defined` when server-rendered by the standalone test runner.

**How to apply:** When a Node-based `tsx --test` file renders a `.tsx` component, retain an explicit `React` import unless the test runner is configured to use the automatic JSX runtime.
