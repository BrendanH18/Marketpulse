import Foundation

/// One immutable save intent. An uncertain attempt always retries these exact arguments and ID.
struct TransactionSaveRequest {
  let id: String
  let arguments: [String]
  var statusArguments: [String] { ["desktop", "transaction-status", id] }

  init(arguments: [String], id: String = UUID().uuidString) {
    self.id = id
    self.arguments = [arguments[0], "--request-id", id] + arguments.dropFirst()
  }

  func submit(using run: ([String]) async throws -> Data) async -> TransactionSaveResult {
    do {
      _ = try await run(arguments)
      return .recorded
    } catch {
      let failure = error.localizedDescription
      do {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let status = try decoder.decode(TransactionSaveStatus.self, from: await run(statusArguments))
        if status.recorded && status.transactionId != nil { return .recovered }
        if !status.recorded && status.transactionId == nil { return .notRecorded(failure) }
      } catch {
        // A failed/malformed receipt check is an unknown outcome, never permission to create a new request.
      }
      return .unknown(
        "\(failure)\nCouldn't confirm whether this transaction was saved. Retry save to check the same request safely."
      )
    }
  }
}

enum TransactionSaveResult: Equatable {
  case recorded
  case recovered
  case notRecorded(String)
  case unknown(String)
}

private struct TransactionSaveStatus: Decodable {
  let recorded: Bool
  let transactionId: Int?
}

/// Version 1 of `marketpulse desktop snapshot`; separate from the stable status API.
struct DesktopPayload: Decodable {
  let version: Int
  let demo: Bool
  var status: StatusPayload
  let accounts: [DesktopAccount]
  let positions: [DesktopPosition]
  let activity: [DesktopTransaction]
  let allocation: [AllocationBucket]
  let incomeMonths: [HistoryPoint]
  let room: [ContributionRoom]
  let alerts: [DesktopAlert]
  let automation: AutomationReport
  /// Absent from older engines (e.g. an old CLI behind MARKETPULSE_CLI).
  let backend: BackendInfo?
  /// Absent from older engines.
  let storage: StorageInfo?
  let warnings: [String]

  /// Nobody has used this ledger yet, so the app offers its welcome. Older engines don't
  /// report archived accounts, so fall back to what the window can see.
  var ledgerEmpty: Bool { storage?.empty ?? (accounts.isEmpty && activity.isEmpty) }
}

/// The engine that produced the payload.
struct BackendInfo: Decodable {
  let version: String
  let python: String
}

/// Where the engine keeps the ledger. `dataDir` is nil in the demo, whose folder is temporary.
struct StorageInfo: Decodable {
  let dataDir: String?
  /// No accounts at all, archived ones included.
  let empty: Bool
  /// Where backups are kept. Absent from older engines; nil in the demo.
  let backupDir: String?
  /// Backups the app can restore, newest first. Absent from older engines; empty in the demo.
  let backups: [BackupInfo]?
}

/// One file in the backups folder (`marketpulse backup list`).
struct BackupInfo: Decodable, Identifiable, Equatable {
  var id: String { name }
  let name: String
  /// daily, import, manual, pre-restore, or pre-vN (before a schema upgrade).
  let reason: String
  /// Local time from the file name, e.g. "2026-01-02T09:00:00".
  let takenAt: String?
  let size: Int

  var date: Date? {
    guard let takenAt else { return nil }
    let parser = DateFormatter()
    parser.locale = Locale(identifier: "en_US_POSIX")
    parser.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
    return parser.date(from: takenAt)
  }

  var when: String { date?.formatted(date: .abbreviated, time: .shortened) ?? name }

  var reasonLabel: String {
    switch reason {
    case "daily": return "Daily backup"
    case "import": return "Before an import"
    case "manual": return "Backed up by you"
    case "pre-restore": return "Before a restore"
    case let r where r.hasPrefix("pre-v"): return "Before an upgrade"
    default: return reason
    }
  }
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
  let ratio: Double
  /// Unsigned headline value, computed by the Python ledger (`Transaction.gross_value`).
  let value: Double
  /// +1 money into the account, -1 money out, 0 for share-only entries (DRIP, split, transfer).
  let direction: Int
  let targetAccount: String
  var signedValue: Double { direction < 0 ? -value : value }
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
  /// The cycle itself failed (e.g. no backup).
  let errors: [String]
  /// Symbols or FX rates the provider couldn't quote; not a failure.
  let quoteErrors: [String]
}

struct ImportPreview: Decodable, Equatable {
  let added: Int
  let duplicates: Int
  // Python emits [lineNumber, reason] tuples, which require an unkeyed decoder.
  let skipped: [ImportIssue]
  let accountsCreated: [String]
  let backup: String?
  /// Identifies the preview's inputs; the commit sends it back so nothing changed is imported.
  let fingerprint: String
}

struct ImportIssue: Decodable, Identifiable, Equatable {
  var id: Int { line }
  let line: Int
  let reason: String
  init(from decoder: Decoder) throws {
    var values = try decoder.unkeyedContainer()
    line = try values.decode(Int.self)
    reason = try values.decode(String.self)
  }
}

/// Currency codes typed into forms: trimmed and uppercased; valid codes are three ASCII letters.
enum CurrencyInput {
  static func normalize(_ raw: String) -> String {
    raw.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
  }

  static func isValid(_ code: String) -> Bool {
    code.count == 3 && code.unicodeScalars.allSatisfy { ("A"..."Z").contains($0) }
  }
}

/// Number entry in the user's own format ("12,5" in French or German) as well as "12.5".
/// The CLI always receives a plain "." decimal.
enum NumberInput {
  static func parse(_ raw: String, locale: Locale = .current) -> Double? {
    let text = raw.trimmingCharacters(in: .whitespaces)
    guard !text.isEmpty else { return nil }
    let formatter = NumberFormatter()
    formatter.numberStyle = .decimal
    formatter.locale = locale
    // Locale first, so "1.000" is one thousand in German rather than 1.
    guard let value = formatter.number(from: text)?.doubleValue ?? Double(text), value.isFinite
    else { return nil }
    return value
  }

  /// Shown under a field when the entry isn't a plain number, so "1.000" or "1,000" is never
  /// read differently from what the user meant without them seeing it.
  static func hint(_ raw: String, locale: Locale = .current) -> String? {
    let text = raw.trimmingCharacters(in: .whitespaces)
    guard !text.isEmpty else { return nil }
    guard let value = parse(text, locale: locale) else {
      return "Enter a number, like \(12.5.formatted(.number.locale(locale)))."
    }
    if Double(text) == value { return nil }
    return "Reads as \(value.formatted(.number.locale(locale).precision(.fractionLength(0...8))))"
  }

  static func cli(_ raw: String, locale: Locale = .current) -> String {
    parse(raw, locale: locale).map { String($0) } ?? raw
  }
}
