"""Construction « à blanc » de toute l'interface avec des widgets factices (pas de fenêtre) :
attrape les erreurs de nom / d'argument dans le code de l'UI sans écran ni Tk."""
import importlib
import sys
import types

import pytest


class _Var:
    def __init__(self, master=None, value=None, name=None):
        self._v = value
        self._cbs = []

    def get(self):
        return self._v

    def set(self, v):
        self._v = v
        for cb in list(self._cbs):
            cb("", "", "write")

    def trace_add(self, mode, cb):
        self._cbs.append(cb)


class _Widget:
    _after: list = []

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self._tabs = {}
        self._text = ""

    def __getattr__(self, name):
        return lambda *a, **k: None

    # méthodes dont le résultat compte
    def after(self, ms, fn=None, *args):
        if fn:
            _Widget._after.append(fn)

    def winfo_exists(self):
        return True

    def curselection(self):
        return (0,)

    def get(self, *a):
        if self._tabs:
            return next(iter(self._tabs))
        return "▶ Test"

    def yview(self, *a):
        return (0.0, 1.0)

    def add(self, name):
        self._tabs[name] = _Widget()
        return self._tabs[name]

    def tab(self, name):
        return self._tabs.setdefault(name, _Widget())

    def bbox(self, *a):
        return (0, 0, 10, 10)

    def __getitem__(self, key):           # widget["menu"] (OptionMenu)…
        return _Widget()


def _fake_modules():
    tk = types.ModuleType("tkinter")
    for n in ("Frame", "Canvas", "Scrollbar", "Label", "Checkbutton", "Entry", "OptionMenu", "Listbox", "Tk",
              "Toplevel", "Button"):
        setattr(tk, n, type(n, (_Widget,), {}))
    tk.StringVar = tk.BooleanVar = tk.IntVar = tk.Variable = _Var
    tk._default_root = _Widget()
    tk.END = "end"
    cc = types.ModuleType("tkinter.colorchooser")
    cc.askcolor = lambda *a, **k: (None, "#123456")
    fd = types.ModuleType("tkinter.filedialog")
    fd.asksaveasfilename = lambda *a, **k: ""
    tk.colorchooser, tk.filedialog = cc, fd
    ctk = types.ModuleType("customtkinter")
    for n in ("CTk", "CTkToplevel", "CTkFrame", "CTkLabel", "CTkButton", "CTkEntry", "CTkSwitch",
              "CTkSegmentedButton", "CTkTabview", "CTkScrollableFrame", "CTkTextbox", "CTkCheckBox",
              "CTkOptionMenu", "CTkImage", "CTkFont", "CTkScrollbar"):
        setattr(ctk, n, type(n, (_Widget,), {}))
    ctk.set_appearance_mode = lambda *a: None
    return {"tkinter": tk, "tkinter.colorchooser": cc, "tkinter.filedialog": fd, "customtkinter": ctk}


@pytest.fixture()
def ui(monkeypatch, tmp_path):
    monkeypatch.setenv("COCOTO_DATA", str(tmp_path))
    for name, mod in _fake_modules().items():
        monkeypatch.setitem(sys.modules, name, mod)
    for m in [m for m in list(sys.modules) if m.startswith("cocoto.ui")]:
        monkeypatch.delitem(sys.modules, m)
    app_mod = importlib.import_module("cocoto.ui.app")
    widgets = importlib.import_module("cocoto.ui.widgets")
    windows = importlib.import_module("cocoto.ui.windows")
    answers = {"ask": "Test", "yesno": True}
    monkeypatch.setattr(widgets, "popup_info", lambda *a, **k: True)
    monkeypatch.setattr(widgets, "popup_error", lambda *a, **k: True)
    monkeypatch.setattr(widgets, "popup_yesno", lambda *a, **k: answers["yesno"])
    monkeypatch.setattr(widgets, "popup_ask", lambda *a, **k: answers["ask"])
    from cocoto import dashboard, remote
    monkeypatch.setattr(dashboard, "start_loop", lambda *a, **k: None)
    monkeypatch.setattr(remote, "start_remote", lambda *a, **k: False)
    from cocoto.controller import Controller
    c = Controller()
    monkeypatch.setattr(c, "start_autosave", lambda: None)
    _Widget._after = []
    app = app_mod.App(c)
    for _ in range(30):                  # callbacks after() : pages construites une à une, horloge…
        pending, _Widget._after = _Widget._after, []
        for fn in pending:
            fn()
    return app, c, windows, answers


def test_build_whole_ui(ui):
    app, c, windows, answers = ui
    assert set(app.frames) == {"TH", "BH"}
    for mode in ("TH", "BH"):            # toutes les pages ont été construites en tâche de fond
        assert set(app.frames[mode]) == {"config", "heroes", "upgrade", "stats", "profile"}
    assert app._system_page is not None
    for page in ("config", "heroes", "upgrade", "stats", "profile", "system"):
        app.show_page(page)
    assert "gold" in [k for k, *_ in app.binders["TH"].items]
    app.switch_mode("BH")
    app.switch_mode("TH")
    app._refresh_status()
    app._tick()
    windows.open_logs(app, c)
    windows.open_dashboard(app, c)
    windows.open_donate_units(app, c)
    windows.theme_dialog(app, c.settings)


def test_profiles_through_ui(ui):
    app, c, windows, answers = ui
    c.cfg["TH"].set("gold", "777000")
    app._p_create("TH")                       # nom « Test » (popup factice)
    assert "Test" in c.profiles["TH"].names()
    c.cfg["TH"].set("gold", "1")
    app._p_load("TH")
    assert c.cfg["TH"].text("gold") == "777000"
    gold_var = [v for k, v, *_ in app.binders["TH"].items if k == "gold"][0]
    assert gold_var.get() == "777000"        # l'UI a suivi le chargement du profil
    app._p_share("TH")
    app._p_save("TH")


def test_start_refused_without_game(ui):
    app, c, windows, answers = ui
    c.settings.set("backend", "adb")
    c.settings.set("adb_path", "/nonexistent/adb")
    import shutil
    if shutil.which("adb"):
        pytest.skip("adb installé : le test de refus n'est pas déterministe")
    err = c.start("TH")
    assert err and "adb" in err.lower()
    assert not c.state.running
