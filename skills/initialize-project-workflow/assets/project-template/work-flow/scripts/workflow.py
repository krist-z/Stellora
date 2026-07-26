from pathlib import Path
import runpy
import sys


def main() -> None:
    cli = Path(__file__).resolve().parent / "_runtime" / "workflow_cli.py"
    # ``runpy`` preserves this wrapper's import path.  Put the bundled runtime
    # directory first so the project copy can import ``workflow_core`` without
    # relying on the distribution checkout or a globally installed skill.
    sys.path.insert(0, str(cli.parent))
    sys.argv = [str(cli), *sys.argv[1:]]
    runpy.run_path(str(cli), run_name="__main__")


if __name__ == "__main__":
    main()
