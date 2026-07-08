// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "ButlerLight",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "ButlerLight", targets: ["ButlerLight"])
    ],
    targets: [
        .executableTarget(name: "ButlerLight")
    ]
)
