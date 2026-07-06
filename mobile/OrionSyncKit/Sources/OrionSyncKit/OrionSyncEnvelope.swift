import Foundation

public enum OrionSyncConstants {
    public static let containerIdentifier = "iCloud.com.declandundas.orion"
    public static let zoneName = "orion-main"
}

public struct OrionSyncEnvelope: Codable, Equatable, Sendable {
    public var schemaVersion: Int
    public var recordType: String
    public var recordName: String
    public var sourceDeviceID: String
    public var updatedAt: Date
    public var deletedAt: Date?
    public var payload: JSONValue

    public init(
        schemaVersion: Int,
        recordType: String,
        recordName: String,
        sourceDeviceID: String,
        updatedAt: Date,
        deletedAt: Date? = nil,
        payload: JSONValue
    ) {
        self.schemaVersion = schemaVersion
        self.recordType = recordType
        self.recordName = recordName
        self.sourceDeviceID = sourceDeviceID
        self.updatedAt = updatedAt
        self.deletedAt = deletedAt
        self.payload = payload
    }
}

public struct OrionOutboxRecord: Codable, Equatable, Sendable, Identifiable {
    public var outboxID: Int
    public var recordType: String
    public var recordName: String
    public var operation: OrionSyncOperation
    public var payload: OrionSyncEnvelope

    public var id: Int { outboxID }

    public init(
        outboxID: Int,
        recordType: String,
        recordName: String,
        operation: OrionSyncOperation,
        payload: OrionSyncEnvelope
    ) {
        self.outboxID = outboxID
        self.recordType = recordType
        self.recordName = recordName
        self.operation = operation
        self.payload = payload
    }
}

public enum OrionSyncOperation: String, Codable, Sendable {
    case upsert
    case delete
}

public enum JSONValue: Codable, Equatable, Sendable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: JSONValue].self))
        }
    }

    public func encode(to encoder: Encoder) throws {
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
}

public enum OrionJSON {
    public static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let string = try container.decode(String.self)
            if let date = parseDate(string) {
                return date
            }
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Invalid ISO-8601 date: \(string)"
            )
        }
        return decoder
    }

    public static func encoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        encoder.dateEncodingStrategy = .custom { date, encoder in
            var container = encoder.singleValueContainer()
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            try container.encode(formatter.string(from: date))
        }
        return encoder
    }

    private static func parseDate(_ string: String) -> Date? {
        for formatter in iso8601Formatters() {
            if let date = formatter.date(from: string) {
                return date
            }
        }
        for formatter in pythonDateFormatters() {
            if let date = formatter.date(from: string) {
                return date
            }
        }
        return nil
    }

    private static func iso8601Formatters() -> [ISO8601DateFormatter] {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let plainFormatter = ISO8601DateFormatter()
        plainFormatter.formatOptions = [.withInternetDateTime]
        return [formatter, plainFormatter]
    }

    private static func pythonDateFormatters() -> [DateFormatter] {
        [
            "yyyy-MM-dd'T'HH:mm:ss.SSSSSSXXXXX",
            "yyyy-MM-dd'T'HH:mm:ss.SSSXXXXX",
            "yyyy-MM-dd'T'HH:mm:ssXXXXX",
            "yyyy-MM-dd'T'HH:mm:ss.SSSSSS",
            "yyyy-MM-dd'T'HH:mm:ss.SSS",
            "yyyy-MM-dd'T'HH:mm:ss",
            "yyyy-MM-dd"
        ].map { format in
            let formatter = DateFormatter()
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.timeZone = TimeZone(secondsFromGMT: 0)
            formatter.dateFormat = format
            return formatter
        }
    }
}
