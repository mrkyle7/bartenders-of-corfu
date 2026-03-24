#!/bin/bash
uv run pytest -v --tb=long 2>&1 | tail -200