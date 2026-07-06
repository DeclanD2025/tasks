import CloudKit
import Foundation
import XCTest

@testable import OrionSyncKit

final class OrionSyncKitTests: XCTestCase {
    func testEnvelopeDecodesPythonISODates() throws {
        let json = """
        {
          "schemaVersion": 1,
          "recordType": "Task",
          "recordName": "9F2CE357-3277-4D4E-8D8F-5F1E70929B10",
          "sourceDeviceID": "A6986C76-EF21-43F9-B0CF-65F675E4E4B2",
          "updatedAt": "2026-07-02T12:34:56.123456+00:00",
          "deletedAt": null,
          "payload": {
            "title": "Check CloudKit bridge",
            "priority": "high",
            "localID": 42
          }
        }
        """

        let envelope = try OrionJSON.decoder().decode(
            OrionSyncEnvelope.self,
            from: Data(json.utf8)
        )

        XCTAssertEqual(envelope.schemaVersion, 1)
        XCTAssertEqual(envelope.recordType, "Task")
        XCTAssertEqual(envelope.recordName, "9F2CE357-3277-4D4E-8D8F-5F1E70929B10")
        XCTAssertNil(envelope.deletedAt)
        guard case let .object(payload) = envelope.payload else {
            return XCTFail("Expected object payload")
        }
        XCTAssertEqual(payload["title"], .string("Check CloudKit bridge"))
        XCTAssertEqual(payload["localID"], .number(42))
    }

    func testMapperCreatesCloudKitRecordWithPayloadJSON() throws {
        let envelope = OrionSyncEnvelope(
            schemaVersion: 1,
            recordType: "CaptureInboxItem",
            recordName: "capture-1",
            sourceDeviceID: "device-1",
            updatedAt: Date(timeIntervalSince1970: 1_787_000_000),
            payload: .object([
                "text": .string("Phone note"),
                "source": .string("ios")
            ])
        )
        let zoneID = CloudKitRecordMapper.zoneID()

        let record = try CloudKitRecordMapper.makeRecord(from: envelope, zoneID: zoneID)

        XCTAssertEqual(record.recordType, "CaptureInboxItem")
        XCTAssertEqual(record.recordID.recordName, "capture-1")
        XCTAssertEqual(record["schemaVersion"] as? NSNumber, 1)
        XCTAssertEqual(record["sourceDeviceID"] as? String, "device-1")
        let payload = try XCTUnwrap(record["payload"] as? String)
        XCTAssertTrue(payload.contains("Phone note"))
    }
}
