import os
import sys

LAYER_SHELL_LIBS = (
    "/usr/lib/libgtk4-layer-shell.so",
    "/usr/lib64/libgtk4-layer-shell.so",
    "/usr/lib/x86_64-linux-gnu/libgtk4-layer-shell.so",
    "/usr/lib/libgtk4-layer-shell.so.0",
    "/usr/lib/x86_64-linux-gnu/libgtk4-layer-shell.so.0",
)


def ensure_layer_shell_preload():
    """gtk4-layer-shell must be loaded before libwayland-client.

    From Python the only way is LD_PRELOAD, so the process re-executes itself once.
    """
    if os.environ.get("BIGSCREEN_PRELOADED") or os.environ.get("BIGSCREEN_NO_LAYER_SHELL"):
        return
    lib = next((p for p in LAYER_SHELL_LIBS if os.path.exists(p)), None)
    if not lib:
        return
    preload = " ".join(filter(None, [lib, os.environ.get("LD_PRELOAD", "")]))
    os.execve(sys.executable, sys.orig_argv, dict(os.environ, LD_PRELOAD=preload, BIGSCREEN_PRELOADED="1"))


def main():
    ensure_layer_shell_preload()
    # The library is loaded by now; games and apps must not inherit the preload
    os.environ.pop("LD_PRELOAD", None)
    os.environ.pop("BIGSCREEN_PRELOADED", None)
    from .app import BigScreenApp
    return BigScreenApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
