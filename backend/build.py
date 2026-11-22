"""Optional frontend build step for Vercel.

The repository already ships a prebuilt frontend in openui/dist (that is what
upstream Docker images use). Set OPENUI_BUILD_FRONTEND=1 in the Vercel project to
rebuild it from ../frontend during the deployment instead; the output lands in
openui/dist (frontend's ``postbuild`` copies it there). If the build can't run,
the committed openui/dist is used.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
frontend = root.parent / "frontend"
dist = root / "openui" / "dist"


def main() -> int:
    if os.getenv("OPENUI_BUILD_FRONTEND", "").lower() not in ("1", "true", "yes"):
        print("OPENUI_BUILD_FRONTEND not set: using committed openui/dist")
        return 0 if (dist / "index.html").exists() else 1
    if not frontend.exists() or shutil.which("pnpm") is None:
        print("frontend/ or pnpm not available: using committed openui/dist")
        return 0 if (dist / "index.html").exists() else 1
    subprocess.run(["pnpm", "install", "--frozen-lockfile", "--ignore-scripts"], cwd=frontend, check=True)
    subprocess.run(["pnpm", "build"], cwd=frontend, check=True)
    print("Frontend built into", dist)
    return 0


if __name__ == "__main__":
    sys.exit(main())
