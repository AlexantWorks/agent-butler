import Combine
import Foundation

struct ColorPreset: Identifiable {
    let id = UUID()
    var name: String
    var color: RGBColor
}

struct ButlerCounts: Equatable {
    var waiting: Int = 0
    var running: Int = 0
    var shelved: Int = 0
}

enum ButlerLightState: String {
    case waiting
    case running
    case shelved
    case idle

    var title: String {
        switch self {
        case .waiting: L10n.t("Projects Need You")
        case .running: L10n.t("Projects Running")
        case .shelved: L10n.t("Projects Shelved")
        case .idle: L10n.t("No Status")
        }
    }
}

enum LightControlMode: String, CaseIterable, Identifiable {
    case butler
    case manual

    var id: String { rawValue }

    var title: String {
        switch self {
        case .butler: L10n.t("Butler Status")
        case .manual: L10n.t("Fixed Color")
        }
    }
}

final class AppModel: ObservableObject {
    @Published var selectedColor: RGBColor {
        didSet {
            UserDefaults.standard.set(Int(selectedColor.red), forKey: Defaults.red)
            UserDefaults.standard.set(Int(selectedColor.green), forKey: Defaults.green)
            UserDefaults.standard.set(Int(selectedColor.blue), forKey: Defaults.blue)
            scheduleApply()
        }
    }

    @Published var brightness: Double {
        didSet {
            UserDefaults.standard.set(brightness, forKey: Defaults.brightness)
            scheduleApply()
        }
    }

    @Published var controlMode: LightControlMode {
        didSet {
            UserDefaults.standard.set(controlMode.rawValue, forKey: Defaults.controlMode)
            lastAppliedButlerState = nil
            lastAppliedOutputColor = nil
            if controlMode == .butler {
                reloadButlerStatus(silent: true)
                applyButlerColorIfNeeded(force: true)
            } else {
                scheduleApply()
            }
        }
    }

    @Published var butlerStatusFilePath: String {
        didSet {
            UserDefaults.standard.set(butlerStatusFilePath, forKey: Defaults.butlerStatusFilePath)
        }
    }

    @Published var waitingColor: RGBColor {
        didSet {
            save(waitingColor, prefix: Defaults.waitingColor)
            applyButlerColorIfNeeded(force: true)
        }
    }

    @Published var runningColor: RGBColor {
        didSet {
            save(runningColor, prefix: Defaults.runningColor)
            applyButlerColorIfNeeded(force: true)
        }
    }

    @Published var shelvedColor: RGBColor {
        didSet {
            save(shelvedColor, prefix: Defaults.shelvedColor)
            applyButlerColorIfNeeded(force: true)
        }
    }

    @Published var scheduleEnabled: Bool {
        didSet {
            UserDefaults.standard.set(scheduleEnabled, forKey: Defaults.scheduleEnabled)
            enforceScheduleIfNeeded(force: true)
        }
    }

    @Published var activeStartHour: Int {
        didSet {
            UserDefaults.standard.set(activeStartHour, forKey: Defaults.activeStartHour)
            enforceScheduleIfNeeded(force: true)
        }
    }

    @Published var activeEndHour: Int {
        didSet {
            UserDefaults.standard.set(activeEndHour, forKey: Defaults.activeEndHour)
            enforceScheduleIfNeeded(force: true)
        }
    }

    @Published private(set) var butlerCounts = ButlerCounts()
    @Published private(set) var butlerMessage = L10n.t("No status file configured.")

    let led = BluetoothLEDController()
    let presets: [ColorPreset] = [
        ColorPreset(name: "Warm", color: RGBColor(red: 255, green: 148, blue: 80)),
        ColorPreset(name: "Focus", color: RGBColor(red: 92, green: 148, blue: 255)),
        ColorPreset(name: "Mint", color: RGBColor(red: 69, green: 224, blue: 154)),
        ColorPreset(name: "Violet", color: RGBColor(red: 146, green: 104, blue: 255)),
        ColorPreset(name: "Rose", color: RGBColor(red: 255, green: 92, blue: 139)),
        ColorPreset(name: "Cream", color: RGBColor(red: 255, green: 196, blue: 112))
    ]
    let probeColors: [ColorPreset] = [
        ColorPreset(name: "Red", color: RGBColor(red: 255, green: 0, blue: 0)),
        ColorPreset(name: "Orange", color: RGBColor(red: 255, green: 96, blue: 0)),
        ColorPreset(name: "Amber", color: RGBColor(red: 255, green: 176, blue: 0)),
        ColorPreset(name: "Yellow", color: RGBColor(red: 255, green: 255, blue: 0)),
        ColorPreset(name: "Lime", color: RGBColor(red: 128, green: 255, blue: 0)),
        ColorPreset(name: "Green", color: RGBColor(red: 0, green: 255, blue: 0)),
        ColorPreset(name: "Cyan", color: RGBColor(red: 0, green: 255, blue: 255)),
        ColorPreset(name: "Sky", color: RGBColor(red: 0, green: 128, blue: 255)),
        ColorPreset(name: "Blue", color: RGBColor(red: 0, green: 0, blue: 255)),
        ColorPreset(name: "Indigo", color: RGBColor(red: 72, green: 0, blue: 255)),
        ColorPreset(name: "Violet", color: RGBColor(red: 160, green: 0, blue: 255)),
        ColorPreset(name: "Magenta", color: RGBColor(red: 255, green: 0, blue: 255)),
        ColorPreset(name: "Rose", color: RGBColor(red: 255, green: 0, blue: 96)),
        ColorPreset(name: "Cream", color: RGBColor(red: 255, green: 196, blue: 112))
    ]

    private var cancellables: Set<AnyCancellable> = []
    private var applyTimer: Timer?
    private var butlerTimer: Timer?
    private var lastAppliedButlerState: ButlerLightState?
    private var lastAppliedOutputColor: RGBColor?
    private var hasSentScheduledOff = false
    private var isLoading = true

    var sourceColor: RGBColor {
        controlMode == .butler ? butlerColor : selectedColor
    }

    var outputColor: RGBColor {
        sourceColor.scaled(by: brightness)
    }

    var isButlerMode: Bool {
        controlMode == .butler
    }

    var butlerState: ButlerLightState {
        if butlerCounts.waiting > 0 { return .waiting }
        if butlerCounts.running > 0 { return .running }
        if butlerCounts.shelved > 0 { return .shelved }
        return .idle
    }

    var butlerColor: RGBColor {
        switch butlerState {
        case .waiting: waitingColor
        case .running: runningColor
        case .shelved: shelvedColor
        case .idle: selectedColor
        }
    }

    var isWhiteLikeSelection: Bool {
        let channels = [selectedColor.red, selectedColor.green, selectedColor.blue].map(Int.init)
        guard let minValue = channels.min(), let maxValue = channels.max() else { return false }
        return minValue >= 180 && maxValue - minValue <= 48
    }

    var defaultButlerStatusFilePath: String {
        Defaults.defaultButlerStatusFilePath
    }

    var isLightAllowedNow: Bool {
        !scheduleEnabled || Self.isWithinActiveHours(
            startHour: activeStartHour,
            endHour: activeEndHour,
            date: Date()
        )
    }

    var scheduleTitle: String {
        if !scheduleEnabled { return L10n.t("Always Available") }
        return isLightAllowedNow ? L10n.t("Currently Active") : L10n.t("Currently Off")
    }

    var scheduleDetail: String {
        if !scheduleEnabled { return L10n.t("Schedule is disabled.") }
        return String(
            format: L10n.t("%@ on, %@ off."),
            Self.hourLabel(activeStartHour),
            Self.hourLabel(activeEndHour)
        )
    }

    init() {
        selectedColor = RGBColor(
            red: UInt8(UserDefaults.standard.object(forKey: Defaults.red) as? Int ?? 146),
            green: UInt8(UserDefaults.standard.object(forKey: Defaults.green) as? Int ?? 104),
            blue: UInt8(UserDefaults.standard.object(forKey: Defaults.blue) as? Int ?? 255)
        )
        brightness = UserDefaults.standard.object(forKey: Defaults.brightness) as? Double ?? 1.0
        let savedMode = UserDefaults.standard.string(forKey: Defaults.controlMode)
            .flatMap(LightControlMode.init(rawValue:))
        let oldAutoFollow = UserDefaults.standard.object(forKey: Defaults.autoFollowButler) as? Bool ?? false
        controlMode = savedMode ?? (oldAutoFollow ? .butler : .manual)
        let savedButlerPath = UserDefaults.standard.string(forKey: Defaults.butlerStatusFilePath) ?? ""
        butlerStatusFilePath = savedButlerPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? Defaults.defaultButlerStatusFilePath
            : savedButlerPath
        waitingColor = Self.loadColor(prefix: Defaults.waitingColor) ?? RGBColor(red: 255, green: 96, blue: 0)
        runningColor = Self.loadColor(prefix: Defaults.runningColor) ?? RGBColor(red: 56, green: 160, blue: 255)
        shelvedColor = Self.loadColor(prefix: Defaults.shelvedColor) ?? RGBColor(red: 146, green: 104, blue: 255)
        scheduleEnabled = UserDefaults.standard.object(forKey: Defaults.scheduleEnabled) as? Bool ?? true
        activeStartHour = Self.clampedHour(UserDefaults.standard.object(forKey: Defaults.activeStartHour) as? Int ?? 17)
        activeEndHour = Self.clampedHour(UserDefaults.standard.object(forKey: Defaults.activeEndHour) as? Int ?? 0)

        led.objectWillChange
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in
                self?.objectWillChange.send()
            }
            .store(in: &cancellables)

        butlerTimer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: true) { [weak self] _ in
            DispatchQueue.main.async {
                self?.automationTick()
            }
        }

        isLoading = false
        automationTick()
    }

    deinit {
        applyTimer?.invalidate()
        butlerTimer?.invalidate()
    }

    func applyCurrentColor() {
        guard led.canWrite else { return }
        guard isLightAllowedNow else {
            sendScheduledOffIfNeeded(force: false)
            return
        }
        hasSentScheduledOff = false
        led.apply(color: outputColor)
    }

    func usePreset(_ preset: ColorPreset) {
        selectedColor = preset.color
    }

    func probe(_ preset: ColorPreset) {
        selectedColor = preset.color
        applyCurrentColor()
    }

    func powerOn() {
        if scheduleEnabled && !isLightAllowedNow {
            scheduleEnabled = false
            UserDefaults.standard.set(false, forKey: Defaults.scheduleEnabled)
        }
        hasSentScheduledOff = false
        led.powerOn()
        applyCurrentColor()
    }

    func powerOff() {
        led.powerOff()
        hasSentScheduledOff = true
    }

    func reloadButlerStatus(silent: Bool = false) {
        guard controlMode == .butler || !silent else { return }
        let trimmedPath = resolvedButlerStatusFilePath()

        do {
            let url = URL(fileURLWithPath: NSString(string: trimmedPath).expandingTildeInPath)
            let data = try Data(contentsOf: url)
            let counts = try Self.parseButlerCounts(from: data)
            butlerCounts = counts
            butlerMessage = String(
                format: L10n.t("Loaded %d waiting, %d running, %d shelved."),
                counts.waiting,
                counts.running,
                counts.shelved
            )
            applyButlerColorIfNeeded()
        } catch {
            if !silent {
                butlerMessage = String(format: L10n.t("Could not read status file: %@"), error.localizedDescription)
            }
        }
    }

    func useDefaultButlerStatusFile() {
        butlerStatusFilePath = Defaults.defaultButlerStatusFilePath
        reloadButlerStatus()
    }

    func applyButlerColorIfNeeded(force: Bool = false) {
        guard !isLoading, controlMode == .butler, butlerState != .idle else { return }
        let color = outputColor
        guard force
                || lastAppliedButlerState != butlerState
                || lastAppliedOutputColor != color else {
            return
        }
        lastAppliedButlerState = butlerState
        lastAppliedOutputColor = color
        applyCurrentColor()
    }

    private func automationTick() {
        enforceScheduleIfNeeded(force: false)
        if controlMode == .butler {
            reloadButlerStatus(silent: true)
        }
    }

    private func enforceScheduleIfNeeded(force: Bool) {
        guard !isLoading else { return }
        if isLightAllowedNow {
            if hasSentScheduledOff || force {
                hasSentScheduledOff = false
                applyCurrentColor()
            }
        } else {
            sendScheduledOffIfNeeded(force: force)
        }
    }

    private func sendScheduledOffIfNeeded(force: Bool) {
        guard led.canWrite, force || !hasSentScheduledOff else { return }
        led.powerOff()
        hasSentScheduledOff = true
    }

    private func scheduleApply() {
        guard !isLoading else { return }
        applyTimer?.invalidate()
        applyTimer = Timer.scheduledTimer(withTimeInterval: 0.28, repeats: false) { [weak self] _ in
            DispatchQueue.main.async {
                self?.applyCurrentColor()
            }
        }
    }

    private func resolvedButlerStatusFilePath() -> String {
        let trimmedPath = butlerStatusFilePath.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmedPath.isEmpty {
            butlerStatusFilePath = Defaults.defaultButlerStatusFilePath
            return Defaults.defaultButlerStatusFilePath
        }
        return trimmedPath
    }

    private func save(_ color: RGBColor, prefix: String) {
        UserDefaults.standard.set(Int(color.red), forKey: "\(prefix)Red")
        UserDefaults.standard.set(Int(color.green), forKey: "\(prefix)Green")
        UserDefaults.standard.set(Int(color.blue), forKey: "\(prefix)Blue")
    }

    private static func loadColor(prefix: String) -> RGBColor? {
        guard let red = UserDefaults.standard.object(forKey: "\(prefix)Red") as? Int,
              let green = UserDefaults.standard.object(forKey: "\(prefix)Green") as? Int,
              let blue = UserDefaults.standard.object(forKey: "\(prefix)Blue") as? Int else {
            return nil
        }

        return RGBColor(red: UInt8(red), green: UInt8(green), blue: UInt8(blue))
    }

    private static func parseButlerCounts(from data: Data) throws -> ButlerCounts {
        let object = try JSONSerialization.jsonObject(with: data)
        if let dictionary = object as? [String: Any] {
            return counts(from: dictionary)
        }

        if let array = object as? [[String: Any]] {
            return counts(fromItems: array)
        }

        return ButlerCounts()
    }

    private static func counts(from dictionary: [String: Any]) -> ButlerCounts {
        if let countsDictionary = dictionary["counts"] as? [String: Any] {
            return counts(from: countsDictionary)
        }

        if let items = (dictionary["items"] ?? dictionary["projects"] ?? dictionary["tasks"]) as? [[String: Any]] {
            return counts(fromItems: items)
        }

        return ButlerCounts(
            waiting: intValue(in: dictionary, keys: ["waiting", "waitingForYou", "wait", "pending", "needsInput", "等你", "待处理"]),
            running: intValue(in: dictionary, keys: ["running", "active", "inProgress", "processing", "跑着", "在跑", "运行中"]),
            shelved: intValue(in: dictionary, keys: ["shelved", "paused", "blocked", "stalled", "onHold", "搁置", "被搁置", "暂停"])
        )
    }

    private static func counts(fromItems items: [[String: Any]]) -> ButlerCounts {
        items.reduce(into: ButlerCounts()) { counts, item in
            let rawStatus = (item["status"] ?? item["state"] ?? item["kind"] ?? item["bucket"]) as? String ?? ""
            let status = rawStatus.lowercased()
            if ["waiting", "waitingforyou", "wait", "pending", "needsinput", "等你", "待处理"].contains(status) {
                counts.waiting += 1
            } else if ["running", "active", "inprogress", "processing", "跑着", "在跑", "运行中"].contains(status) {
                counts.running += 1
            } else if ["shelved", "paused", "blocked", "stalled", "onhold", "搁置", "被搁置", "暂停"].contains(status) {
                counts.shelved += 1
            }
        }
    }

    private static func intValue(in dictionary: [String: Any], keys: [String]) -> Int {
        for key in keys {
            if let value = dictionary[key] as? Int {
                return value
            }

            if let value = dictionary[key] as? Double {
                return Int(value)
            }

            if let value = dictionary[key] as? String,
               let intValue = Int(value) {
                return intValue
            }
        }

        return 0
    }

    private static func clampedHour(_ hour: Int) -> Int {
        min(23, max(0, hour))
    }

    private static func isWithinActiveHours(startHour: Int, endHour: Int, date: Date) -> Bool {
        let hour = Calendar.current.component(.hour, from: date)
        if startHour == endHour { return true }
        if startHour < endHour {
            return hour >= startHour && hour < endHour
        }
        return hour >= startHour || hour < endHour
    }

    private static func hourLabel(_ hour: Int) -> String {
        String(format: "%02d:00", clampedHour(hour))
    }
}

private enum Defaults {
    static let red = "selectedColorRed"
    static let green = "selectedColorGreen"
    static let blue = "selectedColorBlue"
    static let brightness = "brightness"
    static let controlMode = "controlMode"
    static let autoFollowButler = "autoFollowButler"
    static let butlerStatusFilePath = "butlerStatusFilePath"
    static let defaultButlerStatusFilePath = "~/.claude-monitor/butler-light-status.json"
    static let waitingColor = "waitingColor"
    static let runningColor = "runningColor"
    static let shelvedColor = "shelvedColor"
    static let scheduleEnabled = "scheduleEnabled"
    static let activeStartHour = "activeStartHour"
    static let activeEndHour = "activeEndHour"
}
