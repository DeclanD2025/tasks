import CloudKit
import Foundation
#if os(macOS)
import Security
#endif

public struct OrionPushedRecord: Codable, Equatable, Sendable {
    public var outboxID: Int
    public var recordType: String
    public var recordName: String
    public var operation: OrionSyncOperation
    public var changeTag: String?

    public init(
        outboxID: Int,
        recordType: String,
        recordName: String,
        operation: OrionSyncOperation,
        changeTag: String? = nil
    ) {
        self.outboxID = outboxID
        self.recordType = recordType
        self.recordName = recordName
        self.operation = operation
        self.changeTag = changeTag
    }
}

public enum CloudKitRecordMapper {
    public static func zoneID(zoneName: String = OrionSyncConstants.zoneName) -> CKRecordZone.ID {
        CKRecordZone.ID(zoneName: zoneName, ownerName: CKCurrentUserDefaultName)
    }

    public static func recordID(for envelope: OrionSyncEnvelope, zoneID: CKRecordZone.ID) -> CKRecord.ID {
        CKRecord.ID(recordName: envelope.recordName, zoneID: zoneID)
    }

    public static func makeRecord(from envelope: OrionSyncEnvelope, zoneID: CKRecordZone.ID) throws -> CKRecord {
        let record = CKRecord(
            recordType: envelope.recordType,
            recordID: recordID(for: envelope, zoneID: zoneID)
        )
        record["schemaVersion"] = NSNumber(value: envelope.schemaVersion)
        record["sourceDeviceID"] = envelope.sourceDeviceID as CKRecordValue
        record["updatedAt"] = envelope.updatedAt as NSDate
        if let deletedAt = envelope.deletedAt {
            record["deletedAt"] = deletedAt as NSDate
        }
        let payloadData = try OrionJSON.encoder().encode(envelope.payload)
        record["payload"] = String(decoding: payloadData, as: UTF8.self) as CKRecordValue
        return record
    }
}

public enum CloudKitSyncClientError: LocalizedError, Sendable {
    case missingCloudKitEntitlement

    public var errorDescription: String? {
        switch self {
        case .missingCloudKitEntitlement:
            "CloudKit is unavailable because the app is missing the iCloud CloudKit entitlement."
        }
    }
}

public final class CloudKitSyncClient: @unchecked Sendable {
    public let containerIdentifier: String
    public let zoneName: String

    private var container: CKContainer?

    public init(
        containerIdentifier: String = OrionSyncConstants.containerIdentifier,
        zoneName: String = OrionSyncConstants.zoneName
    ) {
        self.containerIdentifier = containerIdentifier
        self.zoneName = zoneName
    }

    public func accountStatus() async throws -> CKAccountStatus {
        try await cloudKitContainer().accountStatus()
    }

    public func ensureZone() async throws {
        let zone = CKRecordZone(zoneName: zoneName)
        _ = try await cloudKitContainer().privateCloudDatabase.save(zone)
    }

    public func push(_ records: [OrionOutboxRecord]) async throws -> [OrionPushedRecord] {
        try await ensureZone()
        let privateDatabase = try cloudKitContainer().privateCloudDatabase
        let zoneID = CloudKitRecordMapper.zoneID(zoneName: zoneName)
        var pushed: [OrionPushedRecord] = []

        for record in records {
            switch record.operation {
            case .upsert:
                let ckRecord = try CloudKitRecordMapper.makeRecord(
                    from: record.payload,
                    zoneID: zoneID
                )
                let saved = try await privateDatabase.save(ckRecord)
                pushed.append(
                    OrionPushedRecord(
                        outboxID: record.outboxID,
                        recordType: record.recordType,
                        recordName: record.recordName,
                        operation: record.operation,
                        changeTag: saved.recordChangeTag
                    )
                )
            case .delete:
                let recordID = CKRecord.ID(recordName: record.recordName, zoneID: zoneID)
                _ = try await privateDatabase.deleteRecord(withID: recordID)
                pushed.append(
                    OrionPushedRecord(
                        outboxID: record.outboxID,
                        recordType: record.recordType,
                        recordName: record.recordName,
                        operation: record.operation
                    )
                )
            }
        }

        return pushed
    }

    private func cloudKitContainer() throws -> CKContainer {
        guard Self.hasCloudKitEntitlement else {
            throw CloudKitSyncClientError.missingCloudKitEntitlement
        }
        if let container {
            return container
        }
        let container = CKContainer(identifier: containerIdentifier)
        self.container = container
        return container
    }

    public static var hasCloudKitEntitlement: Bool {
        #if os(macOS)
        guard let task = SecTaskCreateFromSelf(kCFAllocatorDefault),
              let value = SecTaskCopyValueForEntitlement(
                task,
                "com.apple.developer.icloud-services" as CFString,
                nil
              )
        else {
            return false
        }

        guard let services = value as? [String] else {
            return false
        }
        return services.contains("CloudKit") || services.contains("CloudKit-Anonymous")
        #elseif targetEnvironment(simulator)
        return ProcessInfo.processInfo.environment["ORION_ENABLE_SIMULATOR_CLOUDKIT"] == "1"
        #else
        return true
        #endif
    }
}

public extension CKAccountStatus {
    var orionDescription: String {
        switch self {
        case .available:
            "available"
        case .couldNotDetermine:
            "could_not_determine"
        case .noAccount:
            "no_account"
        case .restricted:
            "restricted"
        case .temporarilyUnavailable:
            "temporarily_unavailable"
        @unknown default:
            "unknown"
        }
    }
}
