"""RekordTrakt command line, for running from source (the installed app is RekordTrakt.exe).

  python -m rekordtrakt app [--debug]   the tray app: translator in the background, debug window, start at login
  python -m rekordtrakt identify        record which MIDI port is which unit (press a control on each)
  python -m rekordtrakt build           compile the bridge mapping (the whole action registry)
  python -m rekordtrakt install [--force]  install the bridge mapping and disable the controllers' direct mappings,
                                        as one step (--force replaces a bridge file someone edited by hand)
  python -m rekordtrakt run [-v]        run the translator in this console (Ctrl+C to stop)
  python -m rekordtrakt bridge          find the bridge ports, or create them (Windows MIDI Services)
  python -m rekordtrakt status          what's installed and connected
  python -m rekordtrakt uninstall       manual fallback: re-enable the direct mappings, remove the bridge mapping
"""
import argparse
import sys
import time

from rekordtrakt import paths
from rekordtrakt import rig as rig_mod
from rekordtrakt.bridge import install as rb_install
from rekordtrakt.bridge import ports as bridge_ports
from rekordtrakt.bridge.compiler import write_bridge
from rekordtrakt.rekordbox import registry
from rekordtrakt.service import FAILED, Translator, bridge_status, make_engine, preflight, read_rekordbox

BUILD_DIR = paths.DATA_DIR / "bridge"


def cmd_build(rig):
    port = rig["bridge"]["rekordbox_port"]
    csv_path, manifest = write_bridge(BUILD_DIR, port, registry.full_actions())
    print(f"Built {csv_path}: {len(manifest['entries'])} function/deck entries (registry v{registry.VERSION})")
    return csv_path


def cmd_install(rig, force=False):
    csv_path = cmd_build(rig)
    try:
        rb_install.apply(csv_path, [f"{d['port']}.midi.csv" for d in rig["devices"].values()],
                         overwrite_user_edit=force)
    except rb_install.InstallConflict as e:
        print(f"Not installed: {e}. Run 'python -m rekordtrakt install --force' to replace them.")
        return 1
    return 0


def cmd_uninstall(rig):
    for d in rig["devices"].values():
        rb_install.enable(f"{d['port']}.midi.csv")
    name = f"{rig['bridge']['rekordbox_port']}.midi.csv"
    try:
        rb_install.restore(name)
    except LookupError as e:
        print(e)


def cmd_status(rig):
    from rekordtrakt.midi import winmm
    status = bridge_status(rig, read_rekordbox(rig), make_engine(rig, None, None).uses())
    inputs = winmm.input_names()
    for pos, d in rig["devices"].items():
        print(f"{pos:9s} {d['type']:6s} '{d['port']}' {'connected' if d['port'] in inputs else 'NOT CONNECTED'}")
    b = rig["bridge"]
    print(f"bridge    app '{b['app_port']}' {'ok' if b['app_port'] in inputs else 'MISSING'}, "
          f"Rekordbox '{b['rekordbox_port']}' {'ok' if b['rekordbox_port'] in inputs else 'MISSING'}")
    print(f"Rekordbox {'running' if rb_install.rekordbox_running() else 'not running'}")
    print(f"bridge mapping: {status['state']} ({status['entries']} entries installed; registry v{status['version']})")
    for p in preflight(rig, status) or ["mappings: ok"]:
        print(p)


def cmd_bridge(rig):
    from rekordtrakt.midi import winmm
    b = rig["bridge"]
    result = bridge_ports.ensure_pair(b["app_port"], b["rekordbox_port"], winmm)
    print(f"bridge {result['state']}: {result['message']}")
    return 0 if result["ok"] else 1


def cmd_run(rig, verbose):
    from rekordtrakt.midi import winmm
    from rekordtrakt.shell import instance
    if instance.is_running():
        print("The RekordTrakt app is running (tray icon). Quit it first, or use its debug window.")
        return 1
    translator = Translator(winmm, load_rig=lambda: rig, log=print, verbose=verbose,
                            port_units=bridge_ports.port_units)
    translator.start()
    try:
        while translator.alive:
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopping: releasing everything and turning LEDs off.")
    finally:
        translator.stop()
    st = translator.stats
    if st:
        print(f"Controller messages {st['events']}, Rekordbox feedback {st['feedback']}, sent {st['sent']}, "
              f"longest queue wait {st['max_queue_ms']:.1f} ms")
    return 1 if translator.state == FAILED else 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["app"]:
        from rekordtrakt.shell.app import main as app_main
        return app_main(argv[1:])
    p = argparse.ArgumentParser(prog="rekordtrakt", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["app", "identify", "build", "install", "run", "bridge", "status", "uninstall"])
    p.add_argument("-v", "--verbose", action="store_true", help="log every event and action (run)")
    p.add_argument("--force", action="store_true", help="install: replace a bridge mapping edited by hand")
    args = p.parse_args(argv)
    if args.command == "identify":
        from rekordtrakt.midi import winmm
        rig_mod.identify(winmm)
        return 0
    rig = rig_mod.load()
    return {"build": lambda: cmd_build(rig), "install": lambda: cmd_install(rig, args.force),
            "status": lambda: cmd_status(rig),
            "uninstall": lambda: cmd_uninstall(rig), "bridge": lambda: cmd_bridge(rig),
            "run": lambda: cmd_run(rig, args.verbose)}[args.command]()


if __name__ == "__main__":
    sys.exit(main())
