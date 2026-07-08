# Butler Light

Butler Light is an optional native macOS companion for Butler. It connects to an ELK-BLEDOM-compatible LED strip and turns Butler's local project state into a room-visible status light.

## What It Does

- Scans nearby BLE devices and highlights likely ELK-BLEDOM strips.
- Binds to one strip and writes RGB commands over BLE.
- Supports two mutually exclusive modes:
  - **Butler Status**: reads Butler's local status JSON and applies a color by priority.
  - **Fixed Color**: ignores Butler and uses the color picker directly.
- Lets you choose colors for Waiting, Running, and Shelved.
- Includes a simple schedule, defaulting to 17:00 on and 00:00 off.
- Uses RGB scaling for brightness because many low-cost strips do not support real brightness or true white.

## Status File

Butler writes this file automatically:

```text
~/.claude-monitor/butler-light-status.json
```

The priority is:

1. Waiting
2. Running
3. Shelved

The compact format is:

```json
{
  "waiting": 10,
  "running": 1,
  "shelved": 4
}
```

For compatibility, `counts`, `items`, and localized Chinese status keys are also accepted.

## Build

Requires macOS 13+ and Xcode Command Line Tools.

```bash
swift build
```

Create a local `.app` bundle:

```bash
./scripts/package_app.sh
open "dist/Butler Light.app"
```

On first launch, macOS will ask for Bluetooth permission. If Gatekeeper blocks the app, use right-click → Open once.

## Protocol Notes

- Primary service: `FFF0`
- Primary write characteristic: `FFF3`
- RGB command: `7E 07 05 03 RR GG BB 10 EF`

Some ELK-BLEDOM-compatible strips have limited color hardware. Near-white may appear blue; that is a strip limitation, not a software calibration issue.

## Privacy

Butler Light does not use the network. It only reads Butler's local JSON file and talks to the LED strip over local Bluetooth.
