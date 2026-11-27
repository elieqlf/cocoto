"""Point d'entrée : python -m cocoto [--instance N] [--headless TH|BH] [--start TH|BH]

--start : ouvre l'interface et lance le bot tout de suite (sans clic)."""
from __future__ import annotations

import os
import sys
import threading
import traceback

from . import paths
from .logger import log


def _instance_lock() -> object | None:
    """Un seul Cocoto par instance (verrou fichier, ou mutex nommé sous Windows)."""
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.CreateMutexW(None, False, f"Cocoto_instance_{paths.INSTANCE}")
        if ctypes.windll.kernel32.GetLastError() == 183:   # ERROR_ALREADY_EXISTS
            return None
        return h
    import fcntl
    f = open(paths.data_path("instance.lock"), "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return f


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    threading.excepthook = lambda a: log(f"⚠️ Erreur dans le thread {a.thread.name if a.thread else '?'} : "
                                         f"{''.join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback))}")
    lock = _instance_lock()
    if lock is None:
        print(f"Cocoto instance {paths.INSTANCE} tourne déjà.")
        return 1
    log("=" * 60)
    log(f"Lancement de Cocoto {paths.VERSION} (instance {paths.INSTANCE}) — données : {paths.user_dir()}")
    if not os.path.isdir(paths.img_dir()):
        log("⚠️ Dossier assets/img absent : lance d'abord tools/extract_assets.py sur ton CoCoBot.exe")
    from .controller import Controller
    controller = Controller()
    if "--headless" in argv:
        i = argv.index("--headless")
        mode = argv[i + 1].upper() if i + 1 < len(argv) else "TH"
        from .logger import subscribe
        subscribe(print)
        err = controller.start(mode)
        if err:
            print(err)
            return 2
        try:
            controller.state.thread.join()
        except KeyboardInterrupt:
            controller.stop()
            controller.state.thread.join(30)
        return 0
    autostart = None
    if "--start" in argv:
        i = argv.index("--start")
        autostart = argv[i + 1].upper() if i + 1 < len(argv) and not argv[i + 1].startswith("-") else "TH"
    from .ui.app import run
    run(controller, autostart)
    return 0


if __name__ == "__main__":
    sys.exit(main())
