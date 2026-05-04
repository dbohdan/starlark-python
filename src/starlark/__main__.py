"""Entry point for `python -m starlark`."""

if __name__ == "__main__":
    import sys

    from starlark.cmd import main
    sys.exit(main())
