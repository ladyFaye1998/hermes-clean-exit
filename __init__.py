"""Hermes Agent entry point for Clean Exit."""


def register(ctx):
    from .clean_exit.plugin import register as register_clean_exit
    register_clean_exit(ctx)
