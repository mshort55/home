#!/usr/bin/env python3
"""Refresh the three existing role/entry-point tables from repository contracts."""

from repository_checks import refresh_documentation

if __name__ == "__main__":
    refresh_documentation()
