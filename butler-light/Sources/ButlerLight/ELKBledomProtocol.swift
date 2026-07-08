import Foundation

enum ELKBledomProtocol {
    static let primaryServiceUUID = "FFF0"
    static let primaryWriteCharacteristicUUID = "FFF3"
    static let primaryNotifyCharacteristicUUID = "FFF4"

    static let alternateServiceUUID = "FFE5"
    static let alternateWriteCharacteristicUUID = "FFE9"
    static let bjWriteCharacteristicUUID = "EE01"

    static func powerOn() -> [UInt8] {
        [0x7E, 0x04, 0x04, 0x01, 0x00, 0x00, 0x00, 0x00, 0xEF]
    }

    static func powerOff() -> [UInt8] {
        [0x7E, 0x04, 0x04, 0x00, 0x00, 0x00, 0xFF, 0x00, 0xEF]
    }

    static func setColor(_ color: RGBColor) -> [UInt8] {
        [0x7E, 0x07, 0x05, 0x03, color.red, color.green, color.blue, 0x10, 0xEF]
    }

    static func setCommunityColor(_ color: RGBColor) -> [UInt8] {
        [0x7E, 0x00, 0x05, 0x03, color.red, color.green, color.blue, 0x00, 0xEF]
    }

    static func hexString(for bytes: [UInt8]) -> String {
        bytes.map { String(format: "%02X", $0) }.joined(separator: " ")
    }
}
