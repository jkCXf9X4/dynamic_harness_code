"""LLM provider plumbing.

Everything touching a model provider: the provider abstraction (with the
mock path and context-rot detection), the pluggable driver, and prompt
shaping. Since decision 0017 this package is a pure provider leaf — the
default agent (the fabrication kit that wraps a driver into a workspace
decide) lives in ``dhc.tooling.fabrication``, and the framework never
imports this package.
"""
