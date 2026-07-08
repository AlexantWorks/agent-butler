import AppKit
import SwiftUI

struct RGBColor: Codable, Equatable, Hashable {
    var red: UInt8
    var green: UInt8
    var blue: UInt8

    static let white = RGBColor(red: 255, green: 255, blue: 255)
    static let green = RGBColor(red: 47, green: 210, blue: 106)
    static let amber = RGBColor(red: 255, green: 176, blue: 32)
    static let redAlert = RGBColor(red: 255, green: 67, blue: 67)
    static let reviewBlue = RGBColor(red: 56, green: 160, blue: 255)

    var color: Color {
        Color(nsColor: nsColor)
    }

    var nsColor: NSColor {
        NSColor(
            calibratedRed: CGFloat(red) / 255.0,
            green: CGFloat(green) / 255.0,
            blue: CGFloat(blue) / 255.0,
            alpha: 1.0
        )
    }

    var hex: String {
        String(format: "#%02X%02X%02X", red, green, blue)
    }

    func scaled(by brightness: Double) -> RGBColor {
        let value = max(0.02, min(1.0, brightness))
        return RGBColor(
            red: UInt8(Self.clamp(round(Double(red) * value))),
            green: UInt8(Self.clamp(round(Double(green) * value))),
            blue: UInt8(Self.clamp(round(Double(blue) * value)))
        )
    }

    init(red: UInt8, green: UInt8, blue: UInt8) {
        self.red = red
        self.green = green
        self.blue = blue
    }

    init(color: Color) {
        let nsColor = NSColor(color).usingColorSpace(.deviceRGB) ?? .white
        red = UInt8(Self.clamp(round(nsColor.redComponent * 255.0)))
        green = UInt8(Self.clamp(round(nsColor.greenComponent * 255.0)))
        blue = UInt8(Self.clamp(round(nsColor.blueComponent * 255.0)))
    }

    static func interpolate(from start: RGBColor, to end: RGBColor, amount: Double) -> RGBColor {
        let t = max(0.0, min(1.0, amount))
        return RGBColor(
            red: UInt8(clamp(round(Double(start.red) + (Double(end.red) - Double(start.red)) * t))),
            green: UInt8(clamp(round(Double(start.green) + (Double(end.green) - Double(start.green)) * t))),
            blue: UInt8(clamp(round(Double(start.blue) + (Double(end.blue) - Double(start.blue)) * t)))
        )
    }

    private static func clamp(_ value: Double) -> Double {
        max(0.0, min(255.0, value))
    }
}
