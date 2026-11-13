# -*- coding: utf-8 -*-
"""KeyTapper self-test / 自检脚本.

Run from the repository root:  python tests/selftest.py

It sends real key events, but only F13 / F14 / F15 (and Shift held with F13), which normally have
nothing bound to them, and it briefly opens the real window. It uses a config file in a temporary
directory and never reads or writes your own config.json. Administrator rights are not needed.
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import keytapper as kt  # noqa: E402

kt.beep = lambda *a: None          # keep the test silent
F13, F14, F15, SHIFT = 124, 125, 126, 16


def check(cond, what):
    if not cond:
        raise SystemExit("FAILED: " + what)
    print("ok  ", what)


def run_job(job, timeout=5):
    t = kt.Tapper()
    t.start(job)
    t.thread.join(timeout)
    check(not t.alive(), "job finished within %s s" % timeout)
    return t


def test_engine():
    steps = [{"mods": [SHIFT], "key": F13, "gap_ms": 100}, {"mods": [], "key": F14, "gap_ms": 50},
             {"mods": [], "key": F15, "gap_ms": 50}]
    for scancode in (True, False):
        kt.SEND_SCANCODE = scancode
        check(kt.send_key(F15) == 1 and kt.send_key(F15, up=True) == 1,
              "SendInput accepts events (%s mode)" % ("scan code" if scancode else "virtual key"))
        t = run_job({"steps": steps, "hold_ms": 5, "jitter_ms": 0, "delay_s": 0, "duration_s": 0, "max_rounds": 3})
        check(t.count == 9 and t.rounds == 3, "3 rounds of 3 steps -> 9 presses")
        check(abs((t.t_end - t.t_begin) - 0.555) < 0.06, "round timing within tolerance (%.3f s)" % (t.t_end - t.t_begin))
        check(not kt.is_down(SHIFT), "modifier released afterwards")
    kt.SEND_SCANCODE = True

    t = run_job({"steps": steps[2:], "hold_ms": 5, "jitter_ms": 0, "delay_s": 0.2, "duration_s": 0.5, "max_rounds": 0})
    check(9 <= t.count <= 12, "duration limit: about 10 presses in 0.5 s at 50 ms (got %d)" % t.count)
    check(abs((t.t_end - t.t_begin) - 0.5) < 0.04, "duration limit respected")

    t = kt.Tapper()
    t.start({"steps": steps[2:], "hold_ms": 5, "jitter_ms": 0, "delay_s": 5, "duration_s": 0, "max_rounds": 0})
    time.sleep(0.1)
    t.stop()
    t.thread.join(1)
    check(not t.alive() and t.count == 0, "stopping during the countdown sends nothing")


def test_presets_and_ui(tmp):
    good = kt.sanitize_preset({"steps": [{"key": 65}, {"key": 66, "mods": [16, 999], "times": 5000,
                                                       "interval": 2, "unit": "秒"}], "interval": 250})
    check(good["steps"][0]["times"] == 1 and good["steps"][0]["interval"] is None, "missing step fields get defaults")
    check(good["steps"][1]["mods"] == [16] and good["steps"][1]["times"] == 999, "unknown modifiers dropped, times clamped")
    for bad in ({"steps": [{"key": 9999}]}, {"foo": 1}, [1, 2], {"steps": "x"}):
        try:
            kt.sanitize_preset(bad)
        except ValueError:
            continue
        raise SystemExit("FAILED: invalid preset accepted: %r" % (bad,))
    print("ok   invalid presets rejected")

    cfg_path = os.path.join(tmp, "config.json")
    app = kt.App(cfg_path, admin=False)
    pump = lambda sec: [(app.root.update(), time.sleep(0.01)) for _ in range(int(sec * 100))]
    pump(0.3)                      # let the window map and paint once before timing anything
    check(app.cfg["steps"] == [] and app.cfg["presets"] == {}, "fresh config starts empty")

    app.cfg["steps"] = [{"mods": [], "key": 65, "times": 1, "interval": 5, "unit": "秒"},
                        {"mods": [16], "key": 66, "times": 3, "interval": None, "unit": "毫秒"}]
    app.v_interval.set("100")
    app.v_interval_unit.set("毫秒")
    app._refresh_steps()
    app._collect()
    check([s["gap_ms"] for s in app.build_job()["steps"]] == [5000, 100, 100, 100],
          "build_job expands repeat counts and resolves default intervals")

    snap = app._snapshot()
    app.cfg["presets"]["demo"] = snap
    app._set_current_preset("demo")
    out = os.path.join(tmp, "exported.json")
    app.export_to(out, "demo", snap)
    app.cfg["steps"] = []
    app._refresh_steps()
    name = app.import_from(out)
    check(name == "demo (2)" and len(app.cfg["steps"]) == 2 and app.cfg["steps"][1]["times"] == 3,
          "export -> import round trip, name de-duplicated")
    example = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "examples", "abc-loop.json")
    check(app.import_from(example) == "ABC 循环" and len(app.cfg["steps"]) == 3, "bundled example preset imports")
    with open(os.path.join(tmp, "bad.json"), "w", encoding="utf-8") as f:
        f.write("not json")
    try:
        app.import_from(os.path.join(tmp, "bad.json"))
        raise SystemExit("FAILED: malformed file imported")
    except ValueError:
        print("ok   malformed file rejected on import")

    app.tree.selection_set(app.tree.get_children()[0])
    app.copy_step()
    check(len(app.cfg["steps"]) == 4 and app.cfg["steps"][1]["key"] == app.cfg["steps"][0]["key"], "duplicate step")
    app.del_step()
    check(len(app.cfg["steps"]) == 3, "delete step")

    # a real run through the UI: F13 twice then F14, five rounds
    app.cfg["steps"] = [{"mods": [], "key": F13, "times": 2, "interval": 120, "unit": "毫秒"},
                        {"mods": [], "key": F14, "times": 1, "interval": 120, "unit": "毫秒"}]
    app._refresh_steps()
    app.v_stop.set("rounds")
    app.v_rounds.set("5")
    app._sync_stop_mode()
    app.start()
    pump(0.05)
    check(app.ui_running and str(app.step_btns["add"].cget("state")) == "disabled", "inputs locked while running")
    deadline = time.time() + 10
    while app.tapper.alive() and time.time() < deadline:
        pump(0.05)
    pump(0.15)
    check(app.tapper.count == 15 and app.tapper.rounds == 5, "UI run: 5 rounds -> 15 presses")
    check(not app.ui_running and str(app.step_btns["add"].cget("state")) == "normal", "inputs unlocked after the run")

    app.on_close()
    with open(cfg_path, encoding="utf-8") as f:
        saved = json.load(f)
    check(set(saved["presets"]) == {"demo", "demo (2)", "ABC 循环"} and saved["window"].startswith("+"),
          "config saved on close")


if __name__ == "__main__":
    test_engine()
    with tempfile.TemporaryDirectory() as tmp:
        test_presets_and_ui(tmp)
    print("\nALL OK")
