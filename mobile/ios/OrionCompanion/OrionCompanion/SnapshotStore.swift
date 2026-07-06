import CloudKit
import Foundation
import LocalAuthentication
import Observation
import OrionSyncKit
import Security
import SwiftData

@MainActor
@Observable
final class CompanionStore {
    var snapshot: MobileSnapshot
    var syncStatus = SyncStatus()
    var lastImportError: String?

    private let syncClient = CloudKitSyncClient()
    private let deviceID: String

    init() {
        self.snapshot = Self.loadBundledSnapshot()
        self.deviceID = DeviceIdentity.current()
    }

    func importSnapshot(from url: URL) {
        let scoped = url.startAccessingSecurityScopedResource()
        defer {
            if scoped {
                url.stopAccessingSecurityScopedResource()
            }
        }

        do {
            let data = try Data(contentsOf: url)
            snapshot = try JSONDecoder().decode(MobileSnapshot.self, from: data)
            lastImportError = nil
        } catch {
            lastImportError = error.localizedDescription
        }
    }

    func refreshCloudKitStatus() async {
        do {
            let status = try await syncClient.accountStatus()
            syncStatus.accountState = CloudKitAccountState(status)
            syncStatus.lastCheckedAt = .now
            syncStatus.lastError = nil
        } catch {
            syncStatus.accountState = .couldNotDetermine
            syncStatus.lastCheckedAt = .now
            syncStatus.lastError = error.localizedDescription
        }
    }

    func syncNow(modelContext: ModelContext) async {
        await refreshCloudKitStatus()
        guard syncStatus.isReady else { return }

        do {
            let descriptor = FetchDescriptor<CaptureDraft>(
                predicate: #Predicate { $0.status == "pending" },
                sortBy: [SortDescriptor(\.createdAt, order: .forward)]
            )
            let drafts = try modelContext.fetch(descriptor)
            syncStatus.pendingCount = drafts.count
            for draft in drafts {
                try await pushCaptureDraft(draft, modelContext: modelContext)
            }
            syncStatus.lastSyncedAt = .now
            syncStatus.lastError = nil
        } catch {
            syncStatus.lastError = error.localizedDescription
        }
    }

    func capture(_ text: String, modelContext: ModelContext) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        let draft = CaptureDraft(text: trimmed)
        modelContext.insert(draft)
        syncStatus.pendingCount += 1

        guard syncStatus.isReady else {
            try? modelContext.save()
            return
        }

        do {
            try await pushCaptureDraft(draft, modelContext: modelContext)
            syncStatus.lastSyncedAt = .now
            syncStatus.lastError = nil
        } catch {
            draft.lastError = error.localizedDescription
            syncStatus.lastError = error.localizedDescription
        }
    }

    private func pushCaptureDraft(
        _ draft: CaptureDraft,
        modelContext: ModelContext
    ) async throws {
        let envelope = captureEnvelope(for: draft)
        let outboxRecord = OrionOutboxRecord(
            outboxID: 0,
            recordType: envelope.recordType,
            recordName: envelope.recordName,
            operation: .upsert,
            payload: envelope
        )
        _ = try await syncClient.push([outboxRecord])
        draft.status = "sent"
        draft.lastError = nil
        modelContext.insert(LocalSyncRecord(envelope: envelope))
        try? modelContext.save()
        syncStatus.pendingCount = max(0, syncStatus.pendingCount - 1)
    }

    private func captureEnvelope(for draft: CaptureDraft) -> OrionSyncEnvelope {
        OrionSyncEnvelope(
            schemaVersion: 1,
            recordType: "CaptureInboxItem",
            recordName: draft.recordName,
            sourceDeviceID: deviceID,
            updatedAt: draft.createdAt,
            payload: .object([
                "text": .string(draft.text),
                "source": .string("ios"),
                "status": .string("new"),
                "createdAt": .string(Self.iso8601.string(from: draft.createdAt))
            ])
        )
    }

    private static func loadBundledSnapshot() -> MobileSnapshot {
        guard let url = Bundle.main.url(
            forResource: "orion-mobile-snapshot.sample",
            withExtension: "json"
        ) else {
            return .empty
        }

        do {
            let data = try Data(contentsOf: url)
            return try JSONDecoder().decode(MobileSnapshot.self, from: data)
        } catch {
            return .empty
        }
    }

    private static let iso8601: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()
}

@MainActor
@Observable
final class AppLockStore {
    var isLocked = true
    var lastError: String?

    func unlock() async {
        let context = LAContext()
        let result: Result<Bool, Error> = await withCheckedContinuation { continuation in
            context.evaluatePolicy(
                .deviceOwnerAuthentication,
                localizedReason: "Unlock ORION"
            ) { success, error in
                if let error {
                    continuation.resume(returning: .failure(error))
                } else {
                    continuation.resume(returning: .success(success))
                }
            }
        }

        switch result {
        case .success(true):
            isLocked = false
            lastError = nil
        case .success(false):
            lastError = "Authentication was not accepted."
        case .failure(let error):
            lastError = error.localizedDescription
        }
    }

    func lock() {
        isLocked = true
    }
}

private enum DeviceIdentity {
    private static let service = "com.declandundas.orion.ios"
    private static let account = "device-id"

    static func current() -> String {
        if let existing = read() {
            return existing
        }
        let value = UUID().uuidString
        save(value)
        return value
    }

    private static func read() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data,
              let value = String(data: data, encoding: .utf8)
        else {
            return nil
        }
        return value
    }

    private static func save(_ value: String) {
        let data = Data(value.utf8)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        SecItemDelete(query as CFDictionary)
        var item = query
        item[kSecValueData as String] = data
        SecItemAdd(item as CFDictionary, nil)
    }
}

private extension CloudKitAccountState {
    init(_ status: CKAccountStatus) {
        switch status {
        case .available:
            self = .available
        case .noAccount:
            self = .noAccount
        case .restricted:
            self = .restricted
        case .temporarilyUnavailable:
            self = .temporarilyUnavailable
        case .couldNotDetermine:
            self = .couldNotDetermine
        @unknown default:
            self = .unknown
        }
    }
}

extension MobileSnapshot {
    static let empty = MobileSnapshot(
        schemaVersion: 1,
        generatedAt: "Not imported",
        user: OrionUser(id: 0, displayName: "Operator", email: ""),
        overview: OverviewPayload(metrics: [], primaryInsight: nil),
        health: nil,
        activity: nil,
        tasks: TasksPayload(counts: TaskCounts(open: 0, done: 0, total: 0), open: []),
        calendar: CalendarPayload(upcoming: []),
        insights: [],
        sources: []
    )
}
