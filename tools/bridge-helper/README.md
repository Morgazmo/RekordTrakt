# Bridge helper

`rekordtrakt-bridge.exe` is a small companion the app runs. It uses Windows MIDI Services to:

- create and remove the loopback pair RekordTrakt talks to Rekordbox through (`RekordTrakt App` ↔ `RekordTrakt Bridge`), so you don't need the MIDI Settings tools;
- tell the app which physical device each MIDI port belongs to, so two identical controllers keep their places when Windows renumbers them.

Each run prints one JSON object.

```
rekordtrakt-bridge check
rekordtrakt-bridge create [--name-a NAME] [--name-b NAME] [--id-a ID] [--id-b ID]
rekordtrakt-bridge remove --association GUID
rekordtrakt-bridge list
rekordtrakt-bridge ports
```

The exit code is 0 on success and 1 otherwise.

- `check` reports the Windows build, whether the MIDI service and the loopback transport are available, and `usable`.
- `list` gives the active loopback pairs (association id, endpoint names, muted) and the pairs saved by MIDI Settings. The app finds its pair there and never removes a saved one. Pairs made by `create` last until the MIDI service restarts (normally a reboot).
- `ports` lists every MIDI input port with its Windows name and number and the device it belongs to (`unit`: the USB device's instance id, which carries its serial number when it has one).

## Requirements

- Windows 11 25H2 (build 26200) or later, which includes Windows MIDI Services.
- To build: the .NET 10 SDK. Users need nothing extra: the published helper is self-contained.

## The MIDI API package

`Windows.Devices.Midi2` isn't on nuget.org yet. Get `Windows.Devices.Midi2.0.99.92-preview.11.nupkg` from the [microsoft/MIDI release](https://github.com/microsoft/MIDI/releases) `inbox-preview-11` and put it in `local-packages/` (98 MB, ignored by git). SHA-256:

```
13afc6e6da2adac309ab8c174352f46f1c0ebe2d79e65475bd6274defb73df74
```

The package's `Windows.Devices.Midi2.dll` (MIT) ships next to the helper, which loads it directly: nothing needs registering.

## Build

`installer/build.py` publishes the helper as part of the installer. To build it on its own:

```bash
dotnet build -c Release -p:Platform=x64
dotnet publish -c Release -r win-x64 --self-contained true -p:Platform=x64 -p:PublishSingleFile=true -p:PublishTrimmed=true -p:DebugType=none -o bin/publish/win-x64
```

The published build is trimmed, so the helper writes JSON with `JsonObject`: reflection-based `JsonSerializer` doesn't work there.
