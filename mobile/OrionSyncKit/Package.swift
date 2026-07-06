// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "OrionSyncKit",
    platforms: [
        .iOS(.v17),
        .macOS(.v14)
    ],
    products: [
        .library(name: "OrionSyncKit", targets: ["OrionSyncKit"]),
        .executable(name: "orion-sync-helper", targets: ["OrionSyncHelper"])
    ],
    targets: [
        .target(name: "OrionSyncKit"),
        .executableTarget(
            name: "OrionSyncHelper",
            dependencies: ["OrionSyncKit"]
        ),
        .testTarget(
            name: "OrionSyncKitTests",
            dependencies: ["OrionSyncKit"]
        )
    ]
)
