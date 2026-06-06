#!/usr/bin/env python3
"""flowcv — control a FlowCV resume from the command line.

Thin entry point; the implementation lives in the `flowcvcli` package
(config, client, content, personal, customization, resume, cli). For library
use: `from flowcvcli import FlowCV`.
"""
from flowcvcli.cli import main

if __name__ == "__main__":
    main()
