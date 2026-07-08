import CoreBluetooth
import Foundation

struct LEDPeripheral: Identifiable, Equatable {
    let id: UUID
    var name: String
    var rssi: Int
    var isLikelyELK: Bool
}

final class BluetoothLEDController: NSObject, ObservableObject {
    @Published private(set) var bluetoothState = L10n.t("Starting")
    @Published private(set) var isScanning = false
    @Published private(set) var discoveredPeripherals: [LEDPeripheral] = []
    @Published private(set) var connectedPeripheralID: UUID?
    @Published private(set) var connectedPeripheralName = ""
    @Published private(set) var canWrite = false
    @Published private(set) var lastMessage = L10n.t("Ready")

    private lazy var centralManager = CBCentralManager(delegate: self, queue: .main)
    private var peripheralMap: [UUID: CBPeripheral] = [:]
    private var connectedPeripheral: CBPeripheral?
    private var writeCharacteristic: CBCharacteristic?

    override init() {
        super.init()
        _ = centralManager
    }

    func startScan() {
        guard centralManager.state == .poweredOn else {
            lastMessage = L10n.t("Bluetooth is not powered on.")
            return
        }

        discoveredPeripherals.removeAll()
        peripheralMap.removeAll(keepingCapacity: true)
        retrieveAlreadyConnectedPeripherals()
        isScanning = true
        lastMessage = L10n.t("Scanning for ELK-BLEDOM...")
        centralManager.scanForPeripherals(
            withServices: nil,
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: true]
        )
    }

    func restartScan() {
        centralManager.stopScan()
        isScanning = false
        startScan()
    }

    func stopScan() {
        centralManager.stopScan()
        isScanning = false
        lastMessage = L10n.t("Scan stopped.")
    }

    func connect(to peripheralID: UUID) {
        guard let peripheral = peripheralMap[peripheralID] else {
            lastMessage = L10n.t("That device is no longer available.")
            return
        }

        stopScan()
        canWrite = false
        writeCharacteristic = nil
        connectedPeripheral = peripheral
        connectedPeripheralID = peripheral.identifier
        connectedPeripheralName = peripheral.name ?? "ELK-BLEDOM"
        lastMessage = String(format: L10n.t("Connecting to %@..."), connectedPeripheralName)
        centralManager.connect(peripheral)
    }

    func disconnect() {
        guard let connectedPeripheral else { return }
        centralManager.cancelPeripheralConnection(connectedPeripheral)
    }

    func powerOn() {
        send(ELKBledomProtocol.powerOn())
    }

    func powerOff() {
        send(ELKBledomProtocol.powerOff())
    }

    func apply(color: RGBColor) {
        send(ELKBledomProtocol.setColor(color))
        send(ELKBledomProtocol.setCommunityColor(color))
    }

    private func send(_ bytes: [UInt8]) {
        guard let connectedPeripheral, let writeCharacteristic else {
            lastMessage = L10n.t("Connect to a writable ELK-BLEDOM device first.")
            return
        }

        let data = Data(bytes)
        let type: CBCharacteristicWriteType = writeCharacteristic.properties.contains(.writeWithoutResponse)
            ? .withoutResponse
            : .withResponse
        connectedPeripheral.writeValue(data, for: writeCharacteristic, type: type)
        lastMessage = String(format: L10n.t("Wrote %@"), ELKBledomProtocol.hexString(for: bytes))
    }

    private func upsert(peripheral: CBPeripheral, name: String, rssi: Int, isLikelyELK: Bool) {
        peripheralMap[peripheral.identifier] = peripheral

        let item = LEDPeripheral(
            id: peripheral.identifier,
            name: name,
            rssi: rssi,
            isLikelyELK: isLikelyELK
        )

        if let index = discoveredPeripherals.firstIndex(where: { $0.id == peripheral.identifier }) {
            discoveredPeripherals[index] = item
        } else {
            discoveredPeripherals.append(item)
        }

        discoveredPeripherals.sort {
            if $0.isLikelyELK != $1.isLikelyELK {
                return $0.isLikelyELK && !$1.isLikelyELK
            }
            return $0.rssi > $1.rssi
        }
    }

    private func retrieveAlreadyConnectedPeripherals() {
        let serviceUUIDs = [
            CBUUID(string: ELKBledomProtocol.primaryServiceUUID),
            CBUUID(string: ELKBledomProtocol.alternateServiceUUID)
        ]
        centralManager.retrieveConnectedPeripherals(withServices: serviceUUIDs).forEach { peripheral in
            upsert(
                peripheral: peripheral,
                name: peripheral.name ?? L10n.t("Connected BLE Device"),
                rssi: 0,
                isLikelyELK: true
            )
        }
    }
}

extension BluetoothLEDController: CBCentralManagerDelegate {
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {
        case .unknown:
            bluetoothState = L10n.t("Unknown")
        case .resetting:
            bluetoothState = L10n.t("Resetting")
        case .unsupported:
            bluetoothState = L10n.t("Unsupported")
        case .unauthorized:
            bluetoothState = L10n.t("Unauthorized")
        case .poweredOff:
            bluetoothState = L10n.t("Powered off")
        case .poweredOn:
            bluetoothState = L10n.t("Powered on")
            startScan()
        @unknown default:
            bluetoothState = L10n.t("Unknown")
        }
    }

    func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String: Any],
        rssi RSSI: NSNumber
    ) {
        let advertisedName = advertisementData[CBAdvertisementDataLocalNameKey] as? String
        let name = advertisedName ?? peripheral.name ?? L10n.t("Unknown BLE Device")
        let advertisedServices = advertisementData[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID] ?? []
        let serviceIDs = advertisedServices.map { $0.uuidString.uppercased() }
        let isLikelyELK = name.localizedCaseInsensitiveContains("ELK-BLEDOM")
            || serviceIDs.contains(ELKBledomProtocol.primaryServiceUUID)
            || serviceIDs.contains(ELKBledomProtocol.alternateServiceUUID)

        upsert(
            peripheral: peripheral,
            name: name,
            rssi: RSSI.intValue,
            isLikelyELK: isLikelyELK
        )
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        connectedPeripheral = peripheral
        connectedPeripheralID = peripheral.identifier
        connectedPeripheralName = peripheral.name ?? connectedPeripheralName
        peripheral.delegate = self
        lastMessage = L10n.t("Connected. Discovering services...")
        peripheral.discoverServices([
            CBUUID(string: ELKBledomProtocol.primaryServiceUUID),
            CBUUID(string: ELKBledomProtocol.alternateServiceUUID)
        ])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        canWrite = false
        connectedPeripheralID = nil
        connectedPeripheral = nil
        lastMessage = String(format: L10n.t("Connection failed: %@"), error?.localizedDescription ?? L10n.t("unknown error"))
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        canWrite = false
        writeCharacteristic = nil
        connectedPeripheralID = nil
        connectedPeripheral = nil
        connectedPeripheralName = ""
        lastMessage = error.map { String(format: L10n.t("Disconnected: %@"), $0.localizedDescription) } ?? L10n.t("Disconnected.")
    }
}

extension BluetoothLEDController: CBPeripheralDelegate {
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        if let error {
            lastMessage = String(format: L10n.t("Service discovery failed: %@"), error.localizedDescription)
            return
        }

        guard let services = peripheral.services, !services.isEmpty else {
            lastMessage = L10n.t("No ELK-BLEDOM services found.")
            return
        }

        let characteristics = [
            CBUUID(string: ELKBledomProtocol.primaryWriteCharacteristicUUID),
            CBUUID(string: ELKBledomProtocol.primaryNotifyCharacteristicUUID),
            CBUUID(string: ELKBledomProtocol.alternateWriteCharacteristicUUID),
            CBUUID(string: ELKBledomProtocol.bjWriteCharacteristicUUID)
        ]

        services.forEach { service in
            peripheral.discoverCharacteristics(characteristics, for: service)
        }
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didDiscoverCharacteristicsFor service: CBService,
        error: Error?
    ) {
        if let error {
            lastMessage = String(format: L10n.t("Characteristic discovery failed: %@"), error.localizedDescription)
            return
        }

        service.characteristics?.forEach { characteristic in
            let uuid = characteristic.uuid.uuidString.uppercased()
            if uuid == ELKBledomProtocol.primaryNotifyCharacteristicUUID {
                peripheral.setNotifyValue(true, for: characteristic)
            }

            if writePriority(for: uuid) != nil,
               shouldUseWriteCharacteristic(characteristic) {
                writeCharacteristic = characteristic
                canWrite = true
                lastMessage = String(format: L10n.t("Ready to write on %@."), uuid)
            }
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        if let error {
            lastMessage = String(format: L10n.t("Write failed: %@"), error.localizedDescription)
        }
    }

    private func shouldUseWriteCharacteristic(_ characteristic: CBCharacteristic) -> Bool {
        let newPriority = writePriority(for: characteristic.uuid.uuidString.uppercased()) ?? Int.max
        let currentPriority = writeCharacteristic
            .flatMap { writePriority(for: $0.uuid.uuidString.uppercased()) } ?? Int.max
        return newPriority < currentPriority
    }

    private func writePriority(for uuid: String) -> Int? {
        switch uuid {
        case ELKBledomProtocol.primaryWriteCharacteristicUUID:
            return 0
        case ELKBledomProtocol.alternateWriteCharacteristicUUID:
            return 1
        case ELKBledomProtocol.bjWriteCharacteristicUUID:
            return 2
        default:
            return nil
        }
    }
}
