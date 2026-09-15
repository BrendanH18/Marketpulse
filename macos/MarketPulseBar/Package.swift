// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "MarketPulseBar",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "MarketPulseBar",
            path: "Sources/MarketPulseBar"
        )
    ]
)
