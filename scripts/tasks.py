import shutil
import zipapp as zapp
from pathlib import Path


def clean():
    """Remove built files and caches."""
    # Remove top-level build artifacts.
    for name in ("build", "dist", "starlark-python.pyz", "starlark.pyz"):
        p = Path(name)

        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file():
            p.unlink(missing_ok=True)

    # Remove all `__pycache__` directories.
    for pycache in Path(".").rglob("__pycache__"):
        if pycache.is_dir():
            shutil.rmtree(pycache, ignore_errors=True)

    # Remove Pytest and Ruff caches.
    for cache_dir in (".pytest_cache", ".ruff_cache"):
        p = Path(cache_dir)

        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)


def zipapp():
    """Build the starlark-python.pyz zipapp."""
    zipapp_dir = Path("build/zipapp")
    output_file = Path("starlark-python.pyz")

    # Clean previous build.
    if zipapp_dir.exists():
        shutil.rmtree(zipapp_dir, ignore_errors=True)

    if output_file.exists():
        output_file.unlink()

    # Prepare a source directory.
    zipapp_dir.mkdir(parents=True, exist_ok=True)

    # Copy the Starlark package into the zipapp source dir.
    src_starlark = Path("src/starlark")
    dest_starlark = zipapp_dir / "starlark"
    shutil.copytree(src_starlark, dest_starlark)

    # Write a `__main__.py` entry point.
    main_py = zipapp_dir / "__main__.py"
    main_py.write_text("import sys\nfrom starlark.cmd import main\nsys.exit(main())\n")

    # Create the zipapp.
    zapp.create_archive(
        str(zipapp_dir),
        str(output_file),
        interpreter="/usr/bin/env python3",
    )

    print(f"Built ./{output_file}")

    # Show human-readable size (like `du -h`).
    size = output_file.stat().st_size

    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024:
            print(f"{size:.1f} {unit}")
            break

        size /= 1024
    else:
        print(f"{size:.1f} TiB")
