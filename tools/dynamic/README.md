# Forge Dynamic Micro-Tools

Forge may install small reusable helpers in this directory when a task benefits
from a specialized data transformation. Each helper has a `.py` source file and
a `.json` tool descriptor; the assistant discovers validated descriptors on each
tool turn.

These are **not ordinary executable Python scripts**. Forge interprets a limited
`def run(data):` syntax in a short-lived process. Imports, shell access, network
access, filesystem access, and arbitrary Python execution are unavailable.
Dynamic helpers receive and return JSON-compatible values only, have bounded
input/output and execution steps, and are not allowed to overwrite existing
helpers. Remove a helper's matching `.py` and `.json` files to uninstall it.
