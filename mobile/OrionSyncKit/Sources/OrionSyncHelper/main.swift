import Foundation
import OrionSyncKit
import Darwin

struct HelperCommand: Codable {
    var operation: Operation
    var records: [OrionOutboxRecord]?
    var containerIdentifier: String?
    var zoneName: String?

    enum Operation: String, Codable {
        case accountStatus
        case dryRun
        case push
    }
}

struct HelperResponse: Codable {
    var ok: Bool
    var status: String?
    var count: Int?
    var records: [OrionPushedRecord]?
    var error: String?
}

@main
enum OrionSyncHelper {
    static func main() async {
        do {
            let input = FileHandle.standardInput.readDataToEndOfFile()
            let command = try OrionJSON.decoder().decode(HelperCommand.self, from: input)
            let response = try await handle(command)
            try write(response)
        } catch {
            try? write(HelperResponse(ok: false, error: String(describing: error)))
            Darwin.exit(1)
        }
    }

    private static func handle(_ command: HelperCommand) async throws -> HelperResponse {
        switch command.operation {
        case .dryRun:
            let records = command.records ?? []
            return HelperResponse(ok: true, count: records.count)
        case .accountStatus:
            let client = makeClient(command)
            let status = try await client.accountStatus()
            return HelperResponse(ok: true, status: status.orionDescription)
        case .push:
            let client = makeClient(command)
            let records = try await client.push(command.records ?? [])
            return HelperResponse(ok: true, count: records.count, records: records)
        }
    }

    private static func makeClient(_ command: HelperCommand) -> CloudKitSyncClient {
        CloudKitSyncClient(
            containerIdentifier: command.containerIdentifier ?? OrionSyncConstants.containerIdentifier,
            zoneName: command.zoneName ?? OrionSyncConstants.zoneName
        )
    }

    private static func write(_ response: HelperResponse) throws {
        let data = try OrionJSON.encoder().encode(response)
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data("\n".utf8))
    }
}
