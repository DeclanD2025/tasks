import Foundation
import SwiftUI
import SwiftData

@main
struct OrionCompanionApp: App {
    @State private var store = CompanionStore()
    @State private var appLock = AppLockStore()
    private let modelContainer: ModelContainer

    init() {
        self.modelContainer = Self.makeModelContainer()
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(store)
                .environment(appLock)
                .modelContainer(modelContainer)
        }
    }

    private static func makeModelContainer() -> ModelContainer {
        let schema = Schema([LocalSyncRecord.self, CaptureDraft.self])
        do {
            let supportURL = try FileManager.default.url(
                for: .applicationSupportDirectory,
                in: .userDomainMask,
                appropriateFor: nil,
                create: true
            )
            try FileManager.default.createDirectory(
                at: supportURL,
                withIntermediateDirectories: true
            )
            let storeURL = supportURL.appendingPathComponent("orion-companion.store")
            let configuration = ModelConfiguration(schema: schema, url: storeURL)
            return try ModelContainer(for: schema, configurations: [configuration])
        } catch {
            fatalError("Unable to initialize ORION local cache: \(error)")
        }
    }
}
