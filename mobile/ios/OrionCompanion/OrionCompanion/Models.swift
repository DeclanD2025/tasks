import Foundation
import SwiftData
import OrionSyncKit

enum CloudKitAccountState: String, Codable {
    case unknown
    case available
    case noAccount
    case restricted
    case temporarilyUnavailable
    case couldNotDetermine

    var label: String {
        switch self {
        case .unknown: "Unknown"
        case .available: "Available"
        case .noAccount: "No iCloud Account"
        case .restricted: "Restricted"
        case .temporarilyUnavailable: "Temporarily Unavailable"
        case .couldNotDetermine: "Could Not Determine"
        }
    }
}

struct SyncStatus: Codable {
    var accountState: CloudKitAccountState = .unknown
    var lastCheckedAt: Date?
    var lastSyncedAt: Date?
    var pendingCount: Int = 0
    var lastError: String?

    var isReady: Bool { accountState == .available }
}

@Model
final class LocalSyncRecord {
    @Attribute(.unique) var recordName: String
    var recordType: String
    var payloadJSON: String
    var sourceDeviceID: String
    var updatedAt: Date
    var deletedAt: Date?

    init(envelope: OrionSyncEnvelope) {
        self.recordName = envelope.recordName
        self.recordType = envelope.recordType
        self.sourceDeviceID = envelope.sourceDeviceID
        self.updatedAt = envelope.updatedAt
        self.deletedAt = envelope.deletedAt
        let data = (try? OrionJSON.encoder().encode(envelope.payload)) ?? Data("{}".utf8)
        self.payloadJSON = String(decoding: data, as: UTF8.self)
    }
}

@Model
final class CaptureDraft {
    @Attribute(.unique) var recordName: String
    var text: String
    var createdAt: Date
    var status: String
    var lastError: String?

    init(recordName: String = UUID().uuidString, text: String, createdAt: Date = .now) {
        self.recordName = recordName
        self.text = text
        self.createdAt = createdAt
        self.status = "pending"
    }
}

struct MobileSnapshot: Codable {
    let schemaVersion: Int
    let generatedAt: String
    let user: OrionUser
    let overview: OverviewPayload
    let health: SignalPayload?
    let activity: SignalPayload?
    let tasks: TasksPayload
    let calendar: CalendarPayload
    let insights: [InsightPayload]
    let sources: [SourcePayload]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case generatedAt = "generated_at"
        case user
        case overview
        case health
        case activity
        case tasks
        case calendar
        case insights
        case sources
    }
}

struct OrionUser: Codable {
    let id: Int
    let displayName: String
    let email: String

    enum CodingKeys: String, CodingKey {
        case id
        case displayName = "display_name"
        case email
    }
}

struct OverviewPayload: Codable {
    let metrics: [MetricPayload]
    let primaryInsight: InsightPayload?

    enum CodingKeys: String, CodingKey {
        case metrics
        case primaryInsight = "primary_insight"
    }
}

struct MetricPayload: Codable, Identifiable {
    var id: String { label }
    let label: String
    let value: String
    let delta: String
    let trend: String
}

struct SignalPayload: Codable {
    let latest: [String: JSONValuePayload]?
}

enum JSONValuePayload: Codable, Equatable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValuePayload])
    case array([JSONValuePayload])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([JSONValuePayload].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: JSONValuePayload].self))
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value):
            try container.encode(value)
        case .number(let value):
            try container.encode(value)
        case .bool(let value):
            try container.encode(value)
        case .object(let value):
            try container.encode(value)
        case .array(let value):
            try container.encode(value)
        case .null:
            try container.encodeNil()
        }
    }

    var displayValue: String {
        switch self {
        case .string(let value):
            value
        case .number(let value):
            value.rounded() == value ? String(Int(value)) : String(format: "%.1f", value)
        case .bool(let value):
            value ? "Yes" : "No"
        case .object, .array:
            "Available"
        case .null:
            "—"
        }
    }
}

struct TasksPayload: Codable {
    let counts: TaskCounts
    let open: [TaskPayload]
}

struct TaskCounts: Codable {
    let open: Int
    let done: Int
    let total: Int
}

struct TaskPayload: Codable, Identifiable {
    let id: Int
    let title: String
    let area: String
    let priority: String
    let status: String
    let notes: String?
    let dueDate: String?

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case area
        case priority
        case status
        case notes
        case dueDate = "due_date"
    }
}

struct CalendarPayload: Codable {
    let upcoming: [CalendarEventPayload]
}

struct CalendarEventPayload: Codable, Identifiable {
    let id: Int
    let title: String
    let calendarName: String?
    let startsAt: String
    let endsAt: String?
    let allDay: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case calendarName = "calendar_name"
        case startsAt = "starts_at"
        case endsAt = "ends_at"
        case allDay = "all_day"
    }
}

struct InsightPayload: Codable, Identifiable {
    var id: String { "\(domain)-\(title)-\(createdAt)" }
    let domain: String
    let severity: String
    let title: String
    let body: String
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case domain
        case severity
        case title
        case body
        case createdAt = "created_at"
    }
}

struct SourcePayload: Codable, Identifiable {
    var id: String { key }
    let key: String
    let name: String
    let domain: String
    let status: String
    let isMock: Bool

    enum CodingKeys: String, CodingKey {
        case key
        case name
        case domain
        case status
        case isMock = "is_mock"
    }
}
