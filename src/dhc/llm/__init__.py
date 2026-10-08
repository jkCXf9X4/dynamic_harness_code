"""LLM provider plumbing.

Everything touching a model provider: the provider abstraction (with the
mock path and context-rot detection), the pluggable driver, prompt
shaping, and deterministic fabrication behind the provider interface.
"""
