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
  /// Only Settings › Data lists these, to unarchive them. Absent from older engines.
  let archivedAccounts: [ArchivedAccount]?
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
  /// Absent from older engines; the Settings window then edits only the app's own preferences.
  let settings: SettingsInfo?
  /// Changes whenever anything a tax report reads does, archived accounts' entries included.
  /// Absent from older engines.
  let ledgerRevision: String?
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

/// The engine configuration the Settings window edits with `marketpulse config set`.
struct SettingsInfo: Decodable {
  let baseCurrency: String
  let privacy: Bool
  /// As written in the config: a name, id or account type. Empty for none.
  let defaultAccount: String
  /// The active account `defaultAccount` picks, if any.
  let defaultAccountId: Int?
  let menubarDisplay: String
  let menubarSymbol: String
  /// nil in the demo, whose settings are its own.
  let configPath: String?
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
  /// Every type `marketpulse accounts add --type` accepts.
  static let types = [
    "TFSA", "RRSP", "FHSA", "RESP", "LIRA", "RRIF", "NONREG", "MARGIN", "CRYPTO", "CASH", "OTHER",
  ]
  let id: Int
  let name: String
  let type: String
  let currency: String
  let institution: String
  let trackCash: Bool
  /// Sent back with an edit or archive, which the engine refuses if the account changed since.
  /// Absent from older engines.
  let revision: String?
  /// `accounts edit` options that make the change apply only to the account as shown.
  var revisionArguments: [String] { revision.map { ["--revision", $0] } ?? [] }
}

/// An archived account: hidden everywhere, left out of totals, history kept.
struct ArchivedAccount: Decodable, Identifiable {
  let id: Int
  let name: String
  let type: String
  /// As for `DesktopAccount`: unarchiving is refused if the account changed since.
  let revision: String?
  var revisionArguments: [String] { revision.map { ["--revision", $0] } ?? [] }
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
  /// Sent back with an edit or delete, which the engine refuses if the entry changed since.
  /// Absent from older engines.
  let revision: String?
  var signedValue: Double { direction < 0 ? -value : value }
  /// `txn edit` / `txn delete` options that make the change apply only to the entry as shown.
  var revisionArguments: [String] { revision.map { ["--revision", $0] } ?? [] }
}

struct AllocationBucket: Decodable, Identifiable {
  var id: String { key }
  let key: String
  let label: String
  let value: Double
  let weight: Double
}

/// Room CRA works out in Canadian dollars, whatever currency totals are shown in.
struct ContributionRoom: Decodable, Identifiable {
  /// The types the app sets room for (`marketpulse accounts room`).
  static let types = ["TFSA", "RRSP", "FHSA"]
  /// The earliest year the form offers: FHSAs began in 2023 and TFSAs in 2009. RRSP room is
  /// entered from a recent notice of assessment, so the TFSA range is plenty.
  static func firstYear(_ type: String) -> Int { type == "FHSA" ? 2023 : 2009 }
  var id: String { accountType }
  let accountType: String
  /// The user entered `startingRoom` as CRA's figure on January 1 of this year.
  let asOfYear: Int
  let startingRoom: Double
  let remaining: Double
  /// How `remaining` was worked out: starting room + new limits + withdrawals added back
  /// − contributions − forfeited. Absent from older engines.
  let contributions: Double?
  let newLimits: Double?
  let withdrawalsAddedBack: Double?
  /// FHSA room above the carry-forward or lifetime limits, which can't be used.
  let forfeited: Double?
}

/// Version 1 of `marketpulse desktop tax`: capital gains for every year, as `marketpulse tax`
/// reports them. Loaded only when the Tax workspace opens, because it needs historical FX rates.
struct TaxPayload: Decodable {
  let version: Int
  let demo: Bool
  let baseCurrency: String
  let inclusionRate: Double
  /// Newest year first; only years with a disposition.
  let years: [TaxYearReport]
  let issues: [TaxIssue]
  let room: [ContributionRoom]
  /// The "not tax advice" notes the workspace must show.
  let notes: [String]
}

/// One calendar year. Totals leave out rows missing an FX rate (`missingFx` counts them).
struct TaxYearReport: Decodable, Identifiable {
  var id: Int { year }
  let year: Int
  let proceeds: Double
  let acb: Double
  /// Losses that don't count this year: superficial, or moved into a registered account.
  let denied: Double
  /// Gains minus allowed losses.
  let netGain: Double
  /// `netGain` times the inclusion rate; 0 for a net loss.
  let taxable: Double
  let inclusionRate: Double
  let dispositions: Int
  let missingFx: Int
  let superficial: Int
  let securities: [TaxSecurity]
  let rows: [TaxDisposition]
}

struct TaxSecurity: Decodable, Identifiable {
  var id: String { symbol }
  let symbol: String
  let dispositions: Int
  let quantity: Double
  let proceeds: Double
  let acb: Double
  let denied: Double
  let netGain: Double
  let missingFx: Int
}

/// One taxable event, every amount in the base currency. Amounts are nil when an FX rate they
/// depend on is missing: unknown, never zero.
struct TaxDisposition: Decodable, Identifiable {
  let id: String
  let date: String
  let accountId: Int
  /// nil for an archived account, which the app never names.
  let account: String?
  let accountType: String?
  let archived: Bool
  let symbol: String
  let quantity: Double
  /// The security's trading currency, and its rate to the base currency on the day.
  let currency: String
  let fx: Double?
  /// sale, roc (return of capital beyond ACB), or deemed (moved in kind into a registered account).
  let kind: String
  let complete: Bool
  let proceeds: Double?
  let acb: Double?
  let gain: Double?
  let denied: Double?
  /// The gain as reported: a denied loss is added back.
  let allowedGain: Double?
  /// superficial, registered, or empty.
  let deniedReason: String
  let superficial: Bool
  /// Superficial-loss working: units bought 30 days either side, and held at the end of day +30.
  let acquiredInWindow: Double
  let heldAfterWindow: Double
  /// Day +30 hasn't come yet, so the denial can still change.
  let windowOpen: Bool
  /// Short tag, as in `marketpulse tax` ("superficial", "FX missing"…); empty for an ordinary sale.
  let note: String
  let transactionId: Int?

  var accountLabel: String { account ?? "Archived account" }
  var kindLabel: String {
    switch kind {
    case "roc": return "Return of capital above ACB"
    case "deemed": return "Moved to a registered account"
    default: return "Sale"
    }
  }
}

/// `marketpulse desktop tax-csv`: what the export itself wrote, and the issues that may have
/// left sales out of the file. Not the loaded report's, which can be older.
struct TaxExportResult: Decodable {
  let exported: Int
  let issues: [TaxIssue]

  /// The confirmation: what was saved, and any issue that may have left a sale out.
  func message(year: Int, file: String) -> String {
    let saved = "Saved \(exported == 1 ? "1 sale" : "\(exported) sales") from \(year) to \(file)"
    switch issues.count {
    case 0: return saved
    case 1: return saved + ". 1 issue may leave sales out of it: \(issues[0].date) \(issues[0].message)"
    case let n: return saved + ". \(n) issues, listed under Needs attention, may leave sales out of it."
    }
  }
}

struct TaxIssue: Decodable, Identifiable, Equatable {
  var id: String { date + message }
  let date: String
  let message: String
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

  /// A stored number as the user would type it, with the fewest decimals that read back as
  /// exactly the same value, so saving an edit never rounds a field the user didn't touch.
  static func editable(_ value: Double, locale: Locale = .current) -> String {
    func text(_ digits: Int) -> String {
      value.formatted(.number.locale(locale).grouping(.never).precision(.fractionLength(0...digits)))
    }
    // Then Swift's shortest exact form ("1e-21"), for values no plain decimal reaches.
    let candidates = (0...20).lazy.map(text) + [String(value)]
    return candidates.first { parse($0, locale: locale) == value } ?? String(value)
  }
}

/// Ledger dates are plain `yyyy-MM-dd` days, read and written in the user's own time zone.
enum LedgerDate {
  private static func formatter(_ format: String) -> DateFormatter {
    let f = DateFormatter()
    f.dateFormat = format
    f.locale = Locale(identifier: "en_US_POSIX")
    return f
  }

  static func string(_ date: Date) -> String { formatter("yyyy-MM-dd").string(from: date) }
  /// Noon on that day: midnight doesn't exist on some daylight-saving days.
  static func date(_ string: String) -> Date? { formatter("yyyy-MM-dd HH:mm").date(from: string + " 12:00") }
}
