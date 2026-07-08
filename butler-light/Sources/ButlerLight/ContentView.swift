import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @EnvironmentObject private var model: AppModel
    @State private var isDevicePanelVisible = true

    var body: some View {
        HStack(spacing: 0) {
            if isDevicePanelVisible {
                devicePanel
                    .frame(width: 360)
                    .background(Color(nsColor: .controlBackgroundColor))
                Divider()
            } else {
                collapsedDeviceRail
                    .frame(width: 58)
                    .background(Color(nsColor: .controlBackgroundColor))
                Divider()
            }

            lightPanel
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .background(Color(nsColor: .windowBackgroundColor))
        }
        .frame(minWidth: 980, minHeight: 680)
    }

    private var devicePanel: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 8) {
                    Text(L10n.t("Butler Light"))
                        .font(.largeTitle.weight(.semibold))
                    statusRow
                }

                Spacer()

                Button {
                    isDevicePanelVisible = false
                } label: {
                    Label(L10n.t("Hide devices"), systemImage: "sidebar.left")
                }
                .labelStyle(.iconOnly)
                .help(L10n.t("Hide devices"))
            }

            HStack(spacing: 10) {
                Button {
                    model.led.restartScan()
                } label: {
                    Label(model.led.isScanning ? L10n.t("Rescan") : L10n.t("Scan"), systemImage: "magnifyingglass")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)

                if model.led.isScanning {
                    Button {
                        model.led.stopScan()
                    } label: {
                        Label(L10n.t("Stop Scan"), systemImage: "stop.circle")
                    }
                    .labelStyle(.iconOnly)
                    .controlSize(.large)
                    .help(L10n.t("Stop Scan"))
                }
            }

            Text(deviceCountLabel)
                .font(.caption)
                .foregroundStyle(.secondary)

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    if model.led.discoveredPeripherals.isEmpty {
                        Text(L10n.t("No devices"))
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.vertical, 8)
                    } else {
                        ForEach(model.led.discoveredPeripherals) { peripheral in
                            deviceRow(peripheral)
                        }
                    }
                }
            }

            Spacer()
        }
        .padding(22)
    }

    private var collapsedDeviceRail: some View {
        VStack(spacing: 18) {
            Button {
                isDevicePanelVisible = true
            } label: {
                Label(L10n.t("Show devices"), systemImage: "sidebar.left")
            }
            .labelStyle(.iconOnly)
            .help(L10n.t("Show devices"))

            Button {
                model.led.restartScan()
            } label: {
                Label(L10n.t("Scan"), systemImage: "magnifyingglass")
            }
            .labelStyle(.iconOnly)
            .help(model.led.isScanning ? L10n.t("Rescan") : L10n.t("Scan"))

            Image(systemName: model.led.canWrite ? "checkmark.circle.fill" : "antenna.radiowaves.left.and.right")
                .foregroundStyle(model.led.canWrite ? .green : .secondary)
                .help(model.led.canWrite ? L10n.t("Bound") : model.led.bluetoothState)

            Spacer()
        }
        .padding(.vertical, 20)
    }

    private var statusRow: some View {
        VStack(alignment: .leading, spacing: 4) {
            Label(model.led.bluetoothState, systemImage: "antenna.radiowaves.left.and.right")
                .font(.title3)
            Text(model.led.canWrite ? String(format: L10n.t("Bound to %@"), model.led.connectedPeripheralName) : model.led.lastMessage)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(3)
        }
    }

    private func deviceRow(_ peripheral: LEDPeripheral) -> some View {
        HStack(alignment: .center, spacing: 12) {
            Image(systemName: peripheral.isLikelyELK ? "lightbulb.led.fill" : "dot.radiowaves.left.and.right")
                .foregroundStyle(peripheral.isLikelyELK ? .yellow : .secondary)
                .frame(width: 22)

            VStack(alignment: .leading, spacing: 3) {
                Text(peripheral.name)
                    .font(.body.weight(peripheral.isLikelyELK ? .semibold : .regular))
                    .lineLimit(2)
                    .truncationMode(.middle)
                Text("RSSI \(peripheral.rssi)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer(minLength: 8)

            if model.led.connectedPeripheralID == peripheral.id && model.led.canWrite {
                Label(L10n.t("Bound"), systemImage: "checkmark.circle.fill")
                    .labelStyle(.iconOnly)
                    .foregroundStyle(.green)
                    .help(L10n.t("Bound"))
            } else {
                Button {
                    model.led.connect(to: peripheral.id)
                } label: {
                    Text(L10n.t("Bind"))
                }
                .controlSize(.small)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(peripheral.isLikelyELK ? Color.yellow.opacity(0.12) : Color(nsColor: .windowBackgroundColor))
        )
    }

    private var lightPanel: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(L10n.t("Light Control"))
                            .font(.largeTitle.weight(.semibold))
                        Text(String(format: L10n.t("Sending %@"), model.outputColor.hex))
                            .font(.title3.monospaced())
                            .foregroundStyle(.secondary)
                    }

                    Spacer()

                    RoundedRectangle(cornerRadius: 12)
                        .fill(model.outputColor.color)
                        .frame(width: 120, height: 120)
                        .overlay {
                            Text(model.outputColor.hex)
                                .font(.caption.monospaced().weight(.semibold))
                                .foregroundStyle(.white)
                                .shadow(radius: 3)
                        }
                }

                controlModePanel
                schedulePanel
                dimmerPanel

                if !model.isButlerMode {
                    colorWheelPanel
                    presetPanel
                    probePanel
                }

                powerControls
            }
            .padding(34)
        }
    }

    private var controlModePanel: some View {
        GroupBox(L10n.t("Control Mode")) {
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 12) {
                    Picker(L10n.t("Mode"), selection: $model.controlMode) {
                        ForEach(LightControlMode.allCases) { mode in
                            Text(mode.title).tag(mode)
                        }
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 260)

                    Spacer()
                    Text(model.isButlerMode ? model.butlerState.title : L10n.t("Fixed Color"))
                        .font(.body.weight(.semibold))
                        .foregroundStyle(.secondary)
                }

                if model.isButlerMode {
                    HStack(spacing: 10) {
                        TextField(model.defaultButlerStatusFilePath, text: $model.butlerStatusFilePath)
                            .textFieldStyle(.roundedBorder)

                        Button {
                            model.useDefaultButlerStatusFile()
                        } label: {
                            Label(L10n.t("Default"), systemImage: "arrow.uturn.backward")
                        }

                        Button {
                            chooseButlerStatusFile()
                        } label: {
                            Label(L10n.t("Choose"), systemImage: "folder")
                        }

                        Button {
                            model.reloadButlerStatus()
                        } label: {
                            Label(L10n.t("Reload"), systemImage: "arrow.clockwise")
                        }
                    }

                    HStack(spacing: 18) {
                        statusCount(title: L10n.t("Waiting"), count: model.butlerCounts.waiting, color: model.waitingColor)
                        statusCount(title: L10n.t("Running"), count: model.butlerCounts.running, color: model.runningColor)
                        statusCount(title: L10n.t("Shelved"), count: model.butlerCounts.shelved, color: model.shelvedColor)
                        Spacer()
                    }

                    Divider()

                    VStack(alignment: .leading, spacing: 10) {
                        statusColorRow(
                            title: L10n.t("Waiting Color"),
                            note: L10n.t("Used whenever any project needs you."),
                            color: Binding(
                                get: { model.waitingColor.color },
                                set: { model.waitingColor = RGBColor(color: $0) }
                            ),
                            swatch: model.waitingColor
                        )

                        statusColorRow(
                            title: L10n.t("Running Color"),
                            note: L10n.t("Used when projects are running and none need you."),
                            color: Binding(
                                get: { model.runningColor.color },
                                set: { model.runningColor = RGBColor(color: $0) }
                            ),
                            swatch: model.runningColor
                        )

                        statusColorRow(
                            title: L10n.t("Shelved Color"),
                            note: L10n.t("Used when only shelved projects remain."),
                            color: Binding(
                                get: { model.shelvedColor.color },
                                set: { model.shelvedColor = RGBColor(color: $0) }
                            ),
                            swatch: model.shelvedColor
                        )
                    }

                    Text(model.butlerMessage)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    Label(L10n.t("The light uses the fixed color below and does not read Butler status."), systemImage: "paintpalette")
                        .foregroundStyle(.secondary)
                }
            }
            .padding(8)
        }
    }

    private var schedulePanel: some View {
        GroupBox(L10n.t("Schedule")) {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Toggle(L10n.t("Use scheduled on/off"), isOn: $model.scheduleEnabled)
                    Spacer()
                    Text(model.scheduleTitle)
                        .font(.body.weight(.semibold))
                        .foregroundColor(model.isLightAllowedNow ? .secondary : .orange)
                }

                HStack(spacing: 18) {
                    Stepper("\(L10n.t("On")) \(String(format: "%02d:00", model.activeStartHour))", value: $model.activeStartHour, in: 0...23)
                    Stepper("\(L10n.t("Off")) \(String(format: "%02d:00", model.activeEndHour))", value: $model.activeEndHour, in: 0...23)
                    Spacer()
                }
                .disabled(!model.scheduleEnabled)

                Text(model.scheduleDetail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(8)
        }
    }

    private var colorWheelPanel: some View {
        GroupBox(L10n.t("Color Wheel")) {
            HStack(spacing: 18) {
                ColorPicker(
                    L10n.t("Color"),
                    selection: Binding(
                        get: { model.selectedColor.color },
                        set: { model.selectedColor = RGBColor(color: $0) }
                    )
                )
                .controlSize(.large)

                RoundedRectangle(cornerRadius: 8)
                    .fill(model.selectedColor.color)
                    .frame(width: 56, height: 38)

                VStack(alignment: .leading, spacing: 2) {
                    Text(model.selectedColor.hex)
                        .font(.body.monospaced())
                        .foregroundStyle(.secondary)
                    Text(L10n.t("Picked color"))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Spacer()
            }
            .padding(8)

            if model.isWhiteLikeSelection {
                Label(L10n.t("This strip does not have true white, so near-white colors may appear blue."), systemImage: "info.circle")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 8)
                    .padding(.bottom, 8)
            }
        }
    }

    private var dimmerPanel: some View {
        GroupBox(L10n.t("Dimmer")) {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Label(L10n.t("Brightness"), systemImage: "sun.max")
                    Spacer()
                    Text("\(Int(model.brightness * 100))%")
                        .font(.body.monospacedDigit())
                        .foregroundStyle(.secondary)
                }

                Slider(value: $model.brightness, in: 0.02...1.0)
            }
            .padding(8)
        }
    }

    private var presetPanel: some View {
        GroupBox(L10n.t("Presets")) {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 120), spacing: 12)], spacing: 12) {
                ForEach(model.presets) { preset in
                    Button {
                        model.usePreset(preset)
                    } label: {
                        HStack(spacing: 10) {
                            RoundedRectangle(cornerRadius: 6)
                                .fill(preset.color.color)
                                .frame(width: 26, height: 26)
                            Text(L10n.t(preset.name))
                            Spacer()
                        }
                        .padding(.vertical, 4)
                    }
                }
            }
            .padding(8)
        }
    }

    private var probePanel: some View {
        GroupBox(L10n.t("Palette Probe")) {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 92), spacing: 10)], spacing: 10) {
                ForEach(model.probeColors) { probe in
                    Button {
                        model.probe(probe)
                    } label: {
                        VStack(spacing: 6) {
                            RoundedRectangle(cornerRadius: 8)
                                .fill(probe.color.color)
                                .frame(height: 34)
                            Text(L10n.t(probe.name))
                                .font(.caption)
                                .lineLimit(1)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(6)
                    }
                    .help(String(format: L10n.t("Test %@ on the light"), L10n.t(probe.name)))
                }
            }
            .padding(8)
        }
    }

    private var powerControls: some View {
        HStack(spacing: 12) {
            Button {
                model.powerOn()
            } label: {
                Label(L10n.t("On"), systemImage: "power.circle.fill")
            }

            Button {
                model.powerOff()
            } label: {
                Label(L10n.t("Off"), systemImage: "power.circle")
            }

            Spacer()
        }
        .controlSize(.large)
        .disabled(!model.led.canWrite)
    }

    private func statusCount(title: String, count: Int, color: RGBColor) -> some View {
        HStack(spacing: 8) {
            Circle()
                .fill(color.color)
                .frame(width: 10, height: 10)
            Text(title)
            Text("\(count)")
                .font(.body.monospacedDigit().weight(.semibold))
        }
    }

    private var deviceCountLabel: String {
        let count = model.led.discoveredPeripherals.count
        if count == 1 {
            return L10n.t("1 device")
        }
        return String(format: L10n.t("%d devices"), count)
    }

    private func statusColorRow(
        title: String,
        note: String,
        color: Binding<Color>,
        swatch: RGBColor
    ) -> some View {
        HStack(spacing: 12) {
            ColorPicker(title, selection: color)
                .frame(width: 180, alignment: .leading)

            RoundedRectangle(cornerRadius: 6)
                .fill(swatch.color)
                .frame(width: 38, height: 28)

            Text(swatch.hex)
                .font(.body.monospaced())
                .foregroundStyle(.secondary)
                .frame(width: 86, alignment: .leading)

            Text(note)
                .font(.caption)
                .foregroundStyle(.secondary)

            Spacer()
        }
    }

    private func chooseButlerStatusFile() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [.json]
        if panel.runModal() == .OK,
           let url = panel.url {
            model.butlerStatusFilePath = url.path
            model.reloadButlerStatus()
        }
    }
}
