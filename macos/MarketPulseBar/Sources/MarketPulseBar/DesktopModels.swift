import Foundation

/// Version 1 of `marketpulse desktop snapshot`; separate from the stable status API.
struct DesktopPayload: Decodable {
  let version: Int
  let demo: Bool
  let status: StatusPayload
  let accounts: [DesktopAccount]
  let positions: [DesktopPosition]
  let activity: [DesktopTransaction]
  let allocation: [AllocationBucket]
  let incomeMonths: [HistoryPoint]
  let room: [ContributionRoom]
  let alerts: [DesktopAlert]
  let automation: AutomationReport
  let warnings: [String]
}

struct DesktopAccount: Decodable, Identifiable {
  let id: Int
  let name: String
  let type: String
  let currency: String
  let institution: String
  let trackCash: Bool
}

struct DesktopPosition: Decodable, Identifiable {
  let id: String
  let accountId: Int
  let account: String
  let symbol: String
  let name: String
  let assetClass: String
  let quantity: Double
  let price: Double?
  let currency: String
  let value: Double?
  let book: Double?
  let gain: Double?
  let gainPct: Double?
  let dayChangePct: Double?
  let weight: Double
  let stale: Bool
}

struct DesktopTransaction: Decodable, Identifiable {
  let id: Int
  let accountId: Int
  let date: String
  let type: String
  let symbol: String
  let quantity: Double
  let price: Double
  let amount: Double
  let fees: Double
  let currency: String
  let note: String
  var value: Double { ["BUY", "SELL", "DRIP"].contains(type) ? quantity * price : amount }
}

struct AllocationBucket: Decodable, Identifiable {
  var id: String { key }
  let key: String
  let label: String
  let value: Double
  let weight: Double
}

struct ContributionRoom: Decodable, Identifiable {
  var id: String { accountType }
  let accountType: String
  let asOfYear: Int
  let remaining: Double
}

struct DesktopAlert: Decodable, Identifiable {
  let id: Int
  let symbol: String
  let condition: String
  let threshold: Double
  let note: String
  let active: Bool
  let triggeredAt: String
  let description: String
}

struct AutomationReport: Decodable {
  let lastRun: String
  let stale: Bool
  let snapshotDate: String?
  let backup: String?
  let fired: [String]
  let errors: [String]
}

struct ImportPreview: Decodable {
  let added: Int
  let duplicates: Int
  // Python emits [lineNumber, reason] tuples, which require an unkeyed decoder.
  let skipped: [ImportIssue]
  let accountsCreated: [String]
  let backup: String?
}

struct ImportIssue: Decodable, Identifiable {
  var id: Int { line }
  let line: Int
  let reason: String
  init(from decoder: Decoder) throws {
    var values = try decoder.unkeyedContainer()
    line = try values.decode(Int.self)
    reason = try values.decode(String.self)
  }
}
