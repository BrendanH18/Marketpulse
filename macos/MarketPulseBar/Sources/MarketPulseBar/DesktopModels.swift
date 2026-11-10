import Foundation

/// One immutable save intent. An uncertain attempt always retries these exact arguments and ID.
struct TransactionSaveRequest {
  let id: String
  let arguments: [String]
  var statusArguments: [String] { ["desktop", "transaction-status", id] }

  /// `commandWords` is how many leading arguments name the command (2 for `asset fixed`): the
  /// request ID goes right after them.
  init(arguments: [String], id: String = UUID().uuidString, commandWords: Int = 1) {
    self.id = id
    self.arguments = Array(arguments.prefix(commandWords)) + ["--request-id", id] + arguments.dropFirst(commandWords)
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
        String(
          localized:
            "\(failure)\nCouldn't confirm whether this transaction was saved. Retry save to check the same request safely."
        )
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

/// The transaction form's fields as typed, and the CLI command they become.
struct TransactionEntry {
  /// Every type the form records.
  static let types = [
    "BUY", "SELL", "DEPOSIT", "WITHDRAWAL", "DIVIDEND", "INTEREST", "FEE", "DRIP", "TRANSFER", "SPLIT", "ROC",
  ]
  /// The ones it can also edit; the others can be deleted and recorded again.
  static let editableTypes = ["BUY", "SELL", "DEPOSIT", "WITHDRAWAL", "DIVIDEND", "INTEREST", "FEE"]
  /// For lists and confirmations, where space is short. Display only: commands and
  /// comparisons use the type itself.
  static func label(_ type: String) -> String {
    switch type {
    case "BUY": return String(localized: "Buy")
    case "SELL": return String(localized: "Sell")
    case "DEPOSIT": return String(localized: "Deposit")
    case "WITHDRAWAL": return String(localized: "Withdrawal")
    case "DIVIDEND": return String(localized: "Dividend")
    case "INTEREST": return String(localized: "Interest")
    case "FEE": return String(localized: "Fee")
    case "DRIP": return String(localized: "DRIP")
    case "TRANSFER": return String(localized: "Transfer")
    case "SPLIT": return String(localized: "Split")
    case "ROC": return String(localized: "ROC")
    case "VALUATION": return String(localized: "Valuation")
    default: return type.capitalized
    }
  }
  /// For the form's type picker.
  static func title(_ type: String) -> String {
    switch type {
    case "DRIP": return String(localized: "Reinvested dividend (DRIP)")
    case "TRANSFER": return String(localized: "Transfer in kind")
    case "SPLIT": return String(localized: "Stock split")
    case "ROC": return String(localized: "Return of capital")
    default: return label(type)
    }
  }

  var type = "BUY"
  /// Account id; for a transfer, the account the shares leave.
  var account = ""
  /// Transfer destination account id.
  var target = ""
  /// `yyyy-MM-dd`
  var date = ""
  var symbol = ""
  var quantity = ""
  var price = ""
  var amount = ""
  var fees = "0"
  var currency = ""
  var note = ""
  /// A split of `splitNew` shares for every `splitOld`: 2 and 1 for a 2-for-1, 1 and 10 for a consolidation.
  var splitNew = "2"
  var splitOld = "1"
  /// A transfer between a registered and a non-registered account: tax needs its market value.
  var priceRequired = false

  var trade: Bool { type == "BUY" || type == "SELL" }
  var needsSymbol: Bool { !["DEPOSIT", "WITHDRAWAL", "INTEREST", "FEE"].contains(type) }
  /// Splits move no money, so they have no currency.
  var usesCurrency: Bool { type != "SPLIT" }
  var symbolCode: String { symbol.trimmingCharacters(in: .whitespaces).uppercased() }
  var currencyCode: String { CurrencyInput.normalize(currency) }
  func ratio(locale: Locale = .current) -> Double? {
    guard let new = NumberInput.parse(splitNew, locale: locale), let old = NumberInput.parse(splitOld, locale: locale),
      new > 0, old > 0
    else { return nil }
    return new / old
  }

  func isValid(locale: Locale = .current) -> Bool {
    func positive(_ value: String) -> Bool { (NumberInput.parse(value, locale: locale) ?? 0) > 0 }
    func nonnegative(_ value: String) -> Bool { (NumberInput.parse(value, locale: locale) ?? -1) >= 0 }
    guard !account.isEmpty, !usesCurrency || currencyCode.isEmpty || CurrencyInput.isValid(currencyCode),
      !needsSymbol || !symbolCode.isEmpty
    else { return false }
    switch type {
    case "BUY", "SELL": return positive(quantity) && nonnegative(price) && nonnegative(fees)
    case "DRIP": return positive(quantity) && nonnegative(price)
    case "TRANSFER":
      let priced = priceRequired ? positive(price) : price.trimmingCharacters(in: .whitespaces).isEmpty || nonnegative(price)
      return !target.isEmpty && target != account && positive(quantity) && priced
    case "SPLIT": return ratio(locale: locale).map { $0 != 1 } ?? false
    default: return positive(amount)
    }
  }

  /// The command that records this entry. User text and numbers go after `--`.
  func arguments(locale: Locale = .current) -> [String] {
    func number(_ value: String) -> String { NumberInput.cli(value, locale: locale) }
    let common = ["--date", date, "--note", note]
    // Blank lets the CLI infer the listing currency, so a USD stock in a CAD account stays USD.
    let currency = currencyCode.isEmpty || !usesCurrency ? [] : ["--currency", currencyCode]
    switch type {
    case "TRANSFER":
      let price = self.price.trimmingCharacters(in: .whitespaces).isEmpty ? [] : ["--price", number(self.price)]
      return ["transfer", "--from", account, "--to", target] + common + price + currency
        + ["--", symbolCode, number(quantity)]
    case "SPLIT":
      return ["split", "--account", account] + common + ["--", symbolCode, ratio(locale: locale).map { String($0) } ?? ""]
    case "DRIP":
      return ["drip", "--account", account] + common + currency + ["--", symbolCode, number(quantity), number(price)]
    case "ROC":
      return ["roc", "--account", account] + common + currency + ["--", symbolCode, number(amount)]
    default:
      let command = [
        "BUY": "buy", "SELL": "sell", "DEPOSIT": "deposit", "WITHDRAWAL": "withdraw",
        "DIVIDEND": "dividend", "INTEREST": "interest", "FEE": "fee",
      ][type]!
      let fees = trade ? ["--fees", number(self.fees)] : []
      let values = (needsSymbol ? [symbolCode] : []) + (trade ? [quantity, price] : [amount]).map(number)
      return [command, "--account", account] + common + fees + currency + ["--"] + values
    }
  }

  /// `txn edit` for an editable type, with every field the form shows, so the stored entry ends up
  /// exactly as the form reads. A blank currency is sent too: the CLI then works it out as for a new entry.
  func editArguments(id: Int, revision: [String], locale: Locale = .current) -> [String] {
    func number(_ value: String) -> String { NumberInput.cli(value, locale: locale) }
    var options = ["txn", "edit", "--account", account, "--date", date, "--currency", currencyCode, "--note", note]
    if needsSymbol { options += ["--symbol", symbolCode] }
    if trade {
      options += ["--quantity", number(quantity), "--price", number(price), "--fees", number(fees)]
    } else {
      options += ["--amount", number(amount)]
    }
    return options + revision + ["--", String(id)]
  }
}

/// The asset forms (`marketpulse asset fixed|manual|value`) as typed, and the command they become.
struct AssetEntry {
  /// A GIC or bond valued by accrual; an asset valued by hand; a new valuation of one.
  static let kinds = ["FIXED", "MANUAL", "VALUE"]
  /// As `marketpulse asset fixed --compounding` accepts them.
  static let compoundings = ["annual", "semiannual", "quarterly", "monthly", "simple"]
  /// A compounding as the app shows it; the CLI gets the value itself.
  static func compoundingLabel(_ compounding: String) -> String {
    switch compounding {
    case "annual": return String(localized: "annual")
    case "semiannual": return String(localized: "semiannual")
    case "quarterly": return String(localized: "quarterly")
    case "monthly": return String(localized: "monthly")
    case "simple": return String(localized: "simple")
    default: return compounding
    }
  }
  /// `asset fixed`, `asset manual`, `asset value`: the request ID goes after both words.
  static let commandWords = 2

  var kind = "FIXED"
  /// Account id; not used for a valuation, which applies to the asset wherever it's held.
  var account = ""
  var symbol = ""
  var name = ""
  /// The principal (FIXED), the value (MANUAL), or the new value (VALUE).
  var value = ""
  /// Annual rate in percent.
  var rate = ""
  /// `yyyy-MM-dd`: the start (FIXED), acquisition (MANUAL) or valuation (VALUE) date.
  var date = ""
  /// `yyyy-MM-dd`, FIXED only.
  var maturity = ""
  var compounding = "annual"
  /// An `AssetClassOption` key, MANUAL only.
  var assetClass = "real_estate"
  /// Blank uses the account's currency. Not used for a valuation, which is in the holding's.
  var currency = ""

  var symbolCode: String { symbol.trimmingCharacters(in: .whitespaces).uppercased() }
  var currencyCode: String { CurrencyInput.normalize(currency) }
  var trimmedName: String { name.trimmingCharacters(in: .whitespaces) }

  func isValid(locale: Locale = .current) -> Bool {
    guard !symbolCode.isEmpty, let amount = NumberInput.parse(value, locale: locale) else { return false }
    switch kind {
    // Something can become worthless; what's bought costs something.
    case "VALUE": return amount >= 0
    case _ where amount <= 0: return false
    case "FIXED":
      guard let rate = NumberInput.parse(rate, locale: locale), rate >= 0 else { return false }
      return !account.isEmpty && validCurrency && AssetEntry.compoundings.contains(compounding)
        && !maturity.isEmpty && maturity > date
    default:
      return !account.isEmpty && validCurrency && AssetClassOption.all.contains { $0.key == assetClass }
    }
  }

  private var validCurrency: Bool { currencyCode.isEmpty || CurrencyInput.isValid(currencyCode) }

  /// The command that records this entry. User text and numbers go after `--`.
  func arguments(locale: Locale = .current) -> [String] {
    func number(_ value: String) -> String { NumberInput.cli(value, locale: locale) }
    let currency = currencyCode.isEmpty ? [] : ["--currency", currencyCode]
    switch kind {
    case "VALUE":
      return ["asset", "value", "--date", date, "--", symbolCode, number(value)]
    case "FIXED":
      return [
        "asset", "fixed", "--account", account, "--start", date, "--maturity", maturity, "--rate", number(rate),
        "--compounding", compounding, "--name", trimmedName,
      ] + currency + ["--", symbolCode, number(value)]
    default:
      return ["asset", "manual", "--account", account, "--date", date, "--class", assetClass, "--name", trimmedName]
        + currency + ["--", symbolCode, number(value)]
    }
  }
}

/// An asset class, as `marketpulse allocation --target` and `asset classify` name it.
struct AssetClassOption: Identifiable, Equatable {
  var id: String { key }
  let key: String
  /// The engine's English label (`AssetClass.label`), which positions report as their class:
  /// compare with this one, and show `localizedLabel`.
  let label: String
  /// `label` in the user's language.
  var localizedLabel: String { Loc.backend(label) }
  /// Python's `AssetClass`, in its order; scripts/check_native_bridge.py checks they match.
  static let all = [
    AssetClassOption(key: "equity", label: "Equity"),
    AssetClassOption(key: "etf", label: "ETF"),
    AssetClassOption(key: "fund", label: "Fund"),
    AssetClassOption(key: "crypto", label: "Crypto"),
    AssetClassOption(key: "fixed_income", label: "Fixed Income"),
    AssetClassOption(key: "cash", label: "Cash"),
    AssetClassOption(key: "real_estate", label: "Real Estate"),
    AssetClassOption(key: "commodity", label: "Commodity"),
    AssetClassOption(key: "alternative", label: "Alternative"),
    AssetClassOption(key: "other", label: "Other"),
  ]
}

/// The targets form: a percentage per asset class as typed, blank for none.
struct TargetsEntry {
  var weights: [String: String] = [:]

  func percent(_ key: String, locale: Locale = .current) -> Double? {
    NumberInput.parse(weights[key] ?? "", locale: locale)
  }
  func total(locale: Locale = .current) -> Double {
    AssetClassOption.all.compactMap { percent($0.key, locale: locale) }.reduce(0, +)
  }

  /// Each entry blank or 0–100, and no more than 100% in all (the CLI's own limit).
  func isValid(locale: Locale = .current) -> Bool {
    for option in AssetClassOption.all {
      let text = (weights[option.key] ?? "").trimmingCharacters(in: .whitespaces)
      if text.isEmpty { continue }
      guard let value = NumberInput.parse(text, locale: locale), (0...100).contains(value) else { return false }
    }
    return total(locale: locale) <= 100.0001
  }

  /// Replaces every saved target with these, without pricing holdings. Zero and blank mean none.
  func arguments(locale: Locale = .current) -> [String] {
    ["allocation", "--quiet", "--clear-targets"]
      + AssetClassOption.all.flatMap { option -> [String] in
        guard let value = percent(option.key, locale: locale), value > 0 else { return [] }
        return ["--target", "\(option.key)=\(value)"]
      }
  }
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
  /// Asset-class targets, and how far the portfolio is from them (empty without targets).
  /// Absent from older engines.
  let targets: [AllocationTarget]?
  let rebalance: [RebalanceRow]?
  /// Saved asset details: GICs and bonds, assets valued by hand, and class overrides.
  /// Absent from older engines.
  let assets: [DesktopAsset]?
  let incomeMonths: [HistoryPoint]
  let room: [ContributionRoom]
  let alerts: [DesktopAlert]
  let automation: AutomationReport
  /// Where quotes come from: the primary provider, then the fallback when one is configured.
  /// Absent from older engines and may be absent from the demo.
  let providers: [QuoteProvider]?
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

  /// `warnings` with a code for each, in the same order. Absent from older engines.
  let warningItems: [DesktopWarning]?

  /// `warnings` in the user's language: worded from each one's code, else the English.
  var localizedWarnings: [String] { localizedWarnings() }

  func localizedWarnings(locale: Locale = .current) -> [String] {
    guard let items = warningItems, items.count == warnings.count else { return warnings }
    return items.map { $0.localized(locale: locale) }
  }

  /// Nobody has used this ledger yet, so the app offers its welcome. Older engines don't
  /// report archived accounts, so fall back to what the window can see.
  var ledgerEmpty: Bool { storage?.empty ?? (accounts.isEmpty && activity.isEmpty) }

  /// The primary provider's name, or nil when the engine doesn't report providers.
  var primaryProvider: String? { providers?.first { $0.primary }?.name }

  /// A provider's display name: from the status list, else the providers the engine offers.
  func providerLabel(_ name: String) -> String {
    providers?.first { $0.name == name }?.label
      ?? settings?.quoteProvidersAvailable?.first { $0.name == name }?.label ?? name
  }
}

/// One quote provider and how its last refresh went.
struct QuoteProvider: Decodable, Identifiable {
  var id: String { name }
  let name: String
  let label: String
  /// "primary" or "fallback".
  let role: String
  /// For a fallback, whether its API key is set. The primary needs no key.
  let configured: Bool
  /// nil when it hasn't been tried yet.
  let ok: Bool?
  /// Local ISO times, e.g. "2026-11-05T14:02:11".
  let lastAttempt: String?
  let lastSuccess: String?
  /// A short reason for the last failure. Never contains the API key.
  let lastError: String?
  /// Quotes it served in the last refresh.
  let quotes: Int

  var primary: Bool { role == "primary" }
  var lastSuccessDate: Date? { lastSuccess.flatMap(BridgeDate.parse) }
  var lastAttemptDate: Date? { lastAttempt.flatMap(BridgeDate.parse) }

  enum Health: Equatable {
    case ok, failing, notTried, notConfigured
    var label: String {
      switch self {
      case .ok: return String(localized: "OK")
      case .failing: return String(localized: "Failing")
      case .notTried: return String(localized: "Not tried")
      case .notConfigured: return String(localized: "No key")
      }
    }
  }

  var health: Health {
    if !configured { return .notConfigured }
    switch ok {
    case true?: return .ok
    case false?: return .failing
    case nil: return .notTried
    }
  }

  private enum CodingKeys: String, CodingKey {
    case name, label, role, configured, ok, lastAttempt, lastSuccess, lastError, quotes
  }

  init(from decoder: Decoder) throws {
    let c = try decoder.container(keyedBy: CodingKeys.self)
    name = try c.decode(String.self, forKey: .name)
    label = try c.decodeIfPresent(String.self, forKey: .label) ?? name
    role = try c.decodeIfPresent(String.self, forKey: .role) ?? "primary"
    configured = try c.decodeIfPresent(Bool.self, forKey: .configured) ?? true
    ok = try c.decodeIfPresent(Bool.self, forKey: .ok)
    lastAttempt = try c.decodeIfPresent(String.self, forKey: .lastAttempt)
    lastSuccess = try c.decodeIfPresent(String.self, forKey: .lastSuccess)
    lastError = try c.decodeIfPresent(String.self, forKey: .lastError)
    quotes = try c.decodeIfPresent(Int.self, forKey: .quotes) ?? 0
  }
}

/// A fallback quote provider the engine can use once the user gives it an API key.
struct QuoteProviderOption: Decodable, Identifiable, Equatable {
  var id: String { name }
  let name: String
  let label: String
  /// Where to get a key. Absent or empty when there's nothing to link to.
  let signupUrl: String?

  var signup: URL? {
    guard let signupUrl, let url = URL(string: signupUrl), url.scheme == "https" else { return nil }
    return url
  }
}

/// Times the engine writes: local ISO times without a zone ("2026-11-05T14:02:11"), with or
/// without fractional seconds, or full ISO 8601 with an offset.
enum BridgeDate {
  static func parse(_ raw: String) -> Date? {
    let text = raw.trimmingCharacters(in: .whitespaces)
    guard !text.isEmpty else { return nil }
    let iso = ISO8601DateFormatter()
    if let date = iso.date(from: text) { return date }
    iso.formatOptions.insert(.withFractionalSeconds)
    if let date = iso.date(from: text) { return date }
    let local = DateFormatter()
    local.locale = Locale(identifier: "en_US_POSIX")
    local.calendar = Calendar(identifier: .gregorian)
    for format in ["yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd'T'HH:mm:ss.SSSSSS", "yyyy-MM-dd'T'HH:mm:ss.SSS", "yyyy-MM-dd HH:mm:ss"] {
      local.dateFormat = format
      if let date = local.date(from: text) { return date }
    }
    return nil
  }

  /// "5 minutes ago", for labels VoiceOver reads too.
  static func relative(_ date: Date, now: Date = .now) -> String {
    // A refresh moments ago (or a clock a little ahead) reads as "now", never "in 2 seconds".
    if abs(date.timeIntervalSince(now)) < 60 { return String(localized: "just now") }
    return min(date, now).formatted(.relative(presentation: .named, unitsStyle: .wide))
  }
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
  /// Saved asset/watchlist/alert/target data; combine with ledgerRevision before a restore.
  let restoreRevision: String?
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
  /// The fallback quote provider's name, "" for none. Absent from older engines.
  let quoteProvider: String?
  /// Whether its API key is saved. The key itself is never sent to the app.
  let quoteProviderKeySet: Bool?
  /// Fallback providers the engine supports. Absent from older engines.
  let quoteProvidersAvailable: [QuoteProviderOption]?
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

  /// How the app names each reason, in English; `desktop.BACKUP_REASON_LABELS` matches it
  /// (scripts/check_native_bridge.py checks), so Backend.strings translates them. "pre-v"
  /// stands for every schema upgrade (pre-v2, pre-v3, …).
  static let reasonLabels = [
    "daily": "Daily backup",
    "import": "Before an import",
    "manual": "Backed up by you",
    "pre-restore": "Before a restore",
    "pre-v": "Before an upgrade",
  ]

  var reasonLabel: String {
    let key = reason.hasPrefix("pre-v") ? "pre-v" : reason
    return BackupInfo.reasonLabels[key].map(Loc.backend) ?? reason
  }
}

struct DesktopAccount: Decodable, Identifiable {
  /// Every type `marketpulse accounts add --type` accepts.
  static let types = [
    "TFSA", "RRSP", "FHSA", "RESP", "LIRA", "RRIF", "NONREG", "MARGIN", "CRYPTO", "CASH", "OTHER",
  ]
  /// An account type as the app shows it (CELI, REER… in French). Display only: the CLI and
  /// comparisons use the type itself.
  static func typeLabel(_ type: String) -> String {
    switch type {
    case "TFSA": return String(localized: "TFSA")
    case "RRSP": return String(localized: "RRSP")
    case "FHSA": return String(localized: "FHSA")
    case "RESP": return String(localized: "RESP")
    case "LIRA": return String(localized: "LIRA")
    case "RRIF": return String(localized: "RRIF")
    case "NONREG": return String(localized: "Non-registered")
    case "MARGIN": return String(localized: "Margin")
    case "CRYPTO": return String(localized: "Crypto")
    case "CASH": return String(localized: "Cash")
    case "OTHER": return String(localized: "Other")
    default: return type
    }
  }
  let id: Int
  let name: String
  let type: String
  let currency: String
  let institution: String
  let trackCash: Bool
  /// Tax-sheltered (TFSA, RRSP, …). Absent from older engines.
  let registered: Bool?
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
  /// The provider that priced it, "" for GICs, bonds and assets valued by hand.
  /// Absent from older engines.
  let quoteSource: String?
  /// How old the quote was when the snapshot was built. Absent from older engines.
  let quoteAgeSeconds: Double?
  /// `assetClass` (the engine's English label) in the user's language.
  var localizedAssetClass: String { Loc.backend(assetClass) }
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
  /// `label` (the engine's English asset class) in the user's language.
  var localizedLabel: String { Loc.backend(label) }
}

struct AllocationTarget: Decodable, Identifiable {
  var id: String { bucket }
  /// An `AssetClassOption` key.
  let bucket: String
  /// Percent of the portfolio.
  let weight: Double
}

/// One asset class against its target, as `marketpulse allocation` shows it.
struct RebalanceRow: Decodable, Identifiable {
  var id: String { bucket }
  let bucket: String
  let label: String
  /// Base currency.
  let value: Double
  /// Percent of the portfolio now, and the target (0 for a class without one).
  let weight: Double
  let target: Double
  /// `weight - target`, in percentage points.
  let drift: Double
  /// Base currency to buy (+) or sell (−) to reach the target. A suggestion only.
  let delta: Double
  /// `label` (the engine's English asset class) in the user's language. Found by `bucket`,
  /// since the engine titles a target class it holds nothing of from its key ("Etf").
  var localizedLabel: String {
    AssetClassOption.all.first { $0.key == bucket }?.localizedLabel ?? Loc.backend(label)
  }
}

/// A symbol's saved details (`marketpulse asset list`).
struct DesktopAsset: Decodable, Identifiable {
  var id: String { symbol }
  let symbol: String
  /// fixed_income (valued by accrual), manual (valued by hand), market (a class override), or cash.
  let kind: String
  let name: String
  /// An `AssetClassOption` key, or nil for the class the market reports.
  let assetClass: String?
  let assetClassLabel: String?
  let currency: String
  /// Fixed income: annual percent, compounding, and `yyyy-MM-dd` term.
  let rate: Double
  let compounding: String
  let startDate: String
  let maturityDate: String
  /// Manual: the date of the valuation (or purchase) its value rests on.
  let valuedOn: String?

  var fixedIncome: Bool { kind == "fixed_income" }
  var manual: Bool { kind == "manual" }
  /// `assetClassLabel` (the engine's English asset class) in the user's language.
  var localizedAssetClassLabel: String? { assetClassLabel.map(Loc.backend) }
  /// Shown under the asset's name in Holdings.
  var summary: String? { summary() }

  func summary(locale: Locale = .current) -> String? {
    if fixedIncome {
      let rate = (self.rate / 100).formatted(.percent.locale(locale).precision(.fractionLength(0...3)))
      let compounding = AssetEntry.compoundingLabel(self.compounding)
      return String(localized: "\(rate) \(compounding) · matures \(maturityDate)")
    }
    if manual, let valuedOn { return String(localized: "Valued by you · \(valuedOn)") }
    return nil
  }
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
  /// `notes` in the user's language.
  var localizedNotes: [String] { notes.map(Loc.backend) }
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

  var accountLabel: String { account ?? String(localized: "Archived account") }
  var kindLabel: String {
    switch kind {
    case "roc": return String(localized: "Return of capital above ACB")
    case "deemed": return String(localized: "Moved to a registered account")
    default: return String(localized: "Sale")
    }
  }
  /// `note` (a fixed English tag) in the user's language; empty for an ordinary sale.
  var localizedNote: String { note.isEmpty ? "" : Loc.backend(note) }
}

/// `marketpulse desktop tax-csv`: what the export itself wrote, and the issues that may have
/// left sales out of the file. Not the loaded report's, which can be older.
struct TaxExportResult: Decodable {
  let exported: Int
  let issues: [TaxIssue]

  /// The confirmation: what was saved, and any issue that may have left a sale out.
  func message(year: Int, file: String, locale: Locale = .current) -> String {
    let one = exported == 1
    let year = String(year)  // a year, never "2,025"
    switch issues.count {
    case 0:
      return one
        ? String(localized: "Saved 1 sale from \(year) to \(file)")
        : String(localized: "Saved \(exported) sales from \(year) to \(file)")
    case 1:
      let date = issues[0].date
      let issue = issues[0].localizedMessage(locale: locale)
      return one
        ? String(localized: "Saved 1 sale from \(year) to \(file). 1 issue may leave sales out of it: \(date) \(issue)")
        : String(
          localized:
            "Saved \(exported) sales from \(year) to \(file). 1 issue may leave sales out of it: \(date) \(issue)")
    case let n:
      return one
        ? String(
          localized:
            "Saved 1 sale from \(year) to \(file). \(n) issues, listed under Needs attention, may leave sales out of it.")
        : String(
          localized:
            "Saved \(exported) sales from \(year) to \(file). \(n) issues, listed under Needs attention, may leave sales out of it."
        )
    }
  }
}

struct TaxIssue: Decodable, Identifiable, Equatable {
  var id: String { date + message }
  let date: String
  /// English, as `marketpulse tax` shows it.
  let message: String
  /// Names the message, and the values that fill it in (see `EngineMessage`). Absent from
  /// older engines; "" for a message without a code.
  let code: String?
  let args: [String: MessageArg]?
  /// `message` in the user's language: worded from its code, else the English.
  var localizedMessage: String { localizedMessage() }

  func localizedMessage(locale: Locale = .current) -> String {
    EngineMessage.issue(code ?? "", args ?? [:], locale: locale) ?? message
  }
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
  /// `description` in the user's language, built from the condition as `models.Alert.describe`
  /// builds it; the engine's English for a condition the app doesn't know.
  var localizedDescription: String { localizedDescription() }

  func localizedDescription(locale: Locale = .current) -> String {
    if Loc.english { return description }  // the engine's wording, exactly
    let price = threshold.formatted(.number.locale(locale).precision(.fractionLength(2)))
    let percent = EngineMessage.percent(threshold, locale)
    switch condition {
    case "above": return "\(symbol) ≥ \(price)"
    case "below": return "\(symbol) ≤ \(price)"
    case "up_pct": return String(localized: "\(symbol) up \(percent) today")
    case "down_pct": return String(localized: "\(symbol) down \(percent) today")
    default: return description
    }
  }
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
  /// Quotes served from the offline cache, and when the oldest was fetched (a local ISO time).
  /// Absent from older engines.
  let staleCount: Int?
  let staleSince: String?
  var staleSinceDate: Date? { staleSince.flatMap(BridgeDate.parse) }
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
  /// The broker profile that read the file (absent from older engines).
  let profile: String?
  let profileLabel: String?
  /// One per skipped line, with the field at fault; `skipped` has the same lines.
  let issues: [ImportRowIssue]?
  let duplicateRows: [ImportDuplicate]?
  /// `profileLabel` (the engine's English) in the user's language.
  var localizedProfileLabel: String? { profileLabel.map(Loc.backend) }
}

/// Broker export formats the importer reads; `marketpulse import --profile` takes the ids.
struct ImportProfile: Identifiable {
  let id: String
  /// In the user's language. Brokers' names aren't translated.
  var label: String {
    switch id {
    case "auto": return String(localized: "Auto-detect")
    case "generic": return Loc.backend("Generic CSV")  // the engine's `profile_label` for it
    case "questrade": return "Questrade"
    case "wealthsimple": return "Wealthsimple"
    default: return id
    }
  }
  static let all = [
    ImportProfile(id: "auto"), ImportProfile(id: "questrade"), ImportProfile(id: "wealthsimple"),
    ImportProfile(id: "generic"),
  ]
}

struct ImportRowIssue: Decodable, Identifiable, Equatable {
  var id: Int { line }
  let line: Int
  /// The import field at fault (date, type, symbol, quantity, …); empty when no single one is.
  let field: String
  /// `field` as the import sheet's columns name it, in the user's language.
  var localizedField: String {
    if Loc.english { return field }  // the engine's name, as `marketpulse import` shows it
    switch field {
    case "date": return String(localized: "Date")
    case "account": return String(localized: "Account")
    case "type": return String(localized: "Type")
    case "symbol": return String(localized: "Symbol")
    case "quantity": return String(localized: "Quantity")
    case "price": return String(localized: "Price")
    case "amount": return String(localized: "Amount")
    case "fees": return String(localized: "Fees")
    case "ratio": return String(localized: "Split ratio")
    case "target_account": return String(localized: "Target account")
    case "currency": return String(localized: "Currency")
    default: return field
    }
  }
  let value: String
  /// English, as `marketpulse import` shows it.
  let reason: String
  /// Names the reason, and the values that fill it in (see `EngineMessage`). Absent from
  /// older engines; "" for a reason without a code.
  let code: String?
  let args: [String: MessageArg]?
  /// `reason` in the user's language: worded from its code, else the English.
  var localizedReason: String { localizedReason() }

  func localizedReason(locale: Locale = .current) -> String {
    // A broker activity the importer skips: its reason is fixed text, so Backend.strings has it.
    if code == "not_imported" { return Loc.backend(reason) }
    return EngineMessage.importReason(code ?? "", args ?? [:], locale: locale) ?? reason
  }
}

struct ImportDuplicate: Decodable, Identifiable, Equatable {
  var id: Int { line }
  let line: Int
  let summary: String
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
      let example = 12.5.formatted(.number.locale(locale))
      return String(localized: "Enter a number, like \(example).")
    }
    if Double(text) == value { return nil }
    let reading = value.formatted(.number.locale(locale).precision(.fractionLength(0...8)))
    return String(localized: "Reads as \(reading)")
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

/// A value filling in an engine message: text (a symbol, an account) or a number (a quantity).
enum MessageArg: Decodable, Equatable {
  case text(String)
  case number(Double)

  init(from decoder: Decoder) throws {
    let c = try decoder.singleValueContainer()
    if let text = try? c.decode(String.self) {
      self = .text(text)
    } else {
      self = .number(try c.decode(Double.self))
    }
  }

  var text: String? {
    if case .text(let value) = self { return value }
    return nil
  }
  var number: Double? {
    if case .number(let value) = self { return value }
    return nil
  }
}

/// One of the snapshot's `warnings`, with the code the app words it from.
struct DesktopWarning: Decodable, Equatable {
  /// "" for a warning without a code: the app shows `text`.
  let code: String
  let args: [String: MessageArg]
  /// English, exactly as in `warnings`.
  let text: String

  private enum CodingKeys: String, CodingKey { case code, args, text }

  init(from decoder: Decoder) throws {
    let c = try decoder.container(keyedBy: CodingKeys.self)
    text = try c.decode(String.self, forKey: .text)
    code = try c.decodeIfPresent(String.self, forKey: .code) ?? ""
    args = try c.decodeIfPresent([String: MessageArg].self, forKey: .args) ?? [:]
  }

  /// In the user's language: worded from the code, else the English.
  func localized(locale: Locale = .current) -> String {
    func value(_ key: String) -> String? { args[key]?.text }
    switch code {
    case "excluded_unpriced":
      guard let symbol = value("symbol") else { return text }
      return String(localized: "Excluded from totals: \(symbol)")
    case "excluded_archived_holding":
      guard let symbol = value("symbol"), let account = value("account") else { return text }
      return String(localized: "Excluded from totals: \(symbol) in archived \(account)")
    case "excluded_archived_cash":
      guard let account = value("account"), let currency = value("currency") else { return text }
      return String(localized: "Excluded from totals: \(account) cash (\(currency), archived)")
    case "excluded_unconverted_cash":
      guard let account = value("account"), let currency = value("currency") else { return text }
      return String(localized: "Excluded from totals: \(account) cash (\(currency))")
    case "archived_account_value":
      guard let account = value("account") else { return text }
      return String(
        localized:
          "Archived account \(account) still holds investments or cash. They're left out of your totals, and daily snapshots are paused. Move or sell them, or unarchive the account."
      )
    default:
      // A ledger issue, dated as `warnings` dates it.
      guard let date = value("date"), let message = EngineMessage.issue(code, args, locale: locale) else {
        return text
      }
      return String(localized: "\(date): \(message)")
    }
  }
}

/// The engine's coded messages in the user's language. Each English template mirrors the
/// engine's text exactly (scripts/check_native_bridge.py checks), so an English app shows what
/// the CLI does. A code the app doesn't know, or a missing value, gives nil: show the English.
enum EngineMessage {
  /// A quantity as the engine writes it (`:,.4f`), in the user's format.
  static func quantity(_ value: Double, _ locale: Locale) -> String {
    value.formatted(.number.locale(locale).precision(.fractionLength(4)))
  }

  /// A threshold in percent (5 for 5%) as the engine writes it (`:g`), in the user's format.
  static func percent(_ value: Double, _ locale: Locale) -> String {
    // Up to six significant digits, like the engine's `{:g}`, so a threshold isn't rounded away.
    (value / 100).formatted(.percent.locale(locale).precision(.significantDigits(1...6)))
  }

  /// A ledger or tax report issue (`LedgerIssue.code`).
  static func issue(_ code: String, _ args: [String: MessageArg], locale: Locale = .current) -> String? {
    guard let symbol = args["symbol"]?.text else { return nil }
    let quantity = args["quantity"]?.number.map { self.quantity($0, locale) }
    let held = args["held"]?.number.map { self.quantity($0, locale) }
    switch code {
    case "sell_exceeds_held":
      guard let quantity, let held else { return nil }
      return String(localized: "Sell of \(quantity) \(symbol) exceeds \(held) held")
    case "transfer_exceeds_held":
      guard let quantity, let held else { return nil }
      return String(localized: "Transfer of \(quantity) \(symbol) exceeds \(held) held")
    case "split_nothing_held":
      return String(localized: "Split of \(symbol) with nothing held")
    case "transfer_nothing_held":
      return String(localized: "Transfer of \(symbol) with nothing held")
    case "transfer_to_registered_unpriced":
      return String(
        localized:
          "Transfer of \(symbol) into a registered account is a deemed sale at market value — add the price per unit to the transfer to include it in the tax report"
      )
    case "transfer_from_registered_unpriced":
      return String(
        localized:
          "Transfer of \(symbol) out of a registered account enters your cost base at market value — add the price per unit to the transfer"
      )
    default:
      return nil
    }
  }

  /// Why an import skipped a row (`RowIssue.code`).
  static func importReason(_ code: String, _ args: [String: MessageArg], locale: Locale = .current) -> String? {
    let value = args["value"]?.text
    // A transaction type by the name the app shows it; English keeps the engine's (DIVIDEND).
    let type = args["type"]?.text.map { Loc.english ? $0 : TransactionEntry.label($0) }
    let account = args["account"]?.text
    switch code {
    case "unknown_type":
      return value.map { String(localized: "unrecognized type '\($0)'") }
    case "invalid_date":
      return value.map { String(localized: "Invalid date '\($0)' — use YYYY-MM-DD.") }
    case "ambiguous_date":
      return value.map { String(localized: "Ambiguous date '\($0)' — use YYYY-MM-DD.") }
    case "unknown_account":
      return account.map { String(localized: "unknown account '\($0)'") }
    case "no_account":
      return String(localized: "no account")
    case "archived_account":
      return account.map { String(localized: "account '\($0)' is archived") }
    case "ambiguous_listing_both":
      guard let (first, second) = pair(args["symbols"]) else { return nil }
      return String(localized: "can't tell whether this is \(first) or \(second): the account holds both; record it by hand")
    case "ambiguous_listing_neither":
      guard let (first, second) = pair(args["symbols"]) else { return nil }
      return String(
        localized: "can't tell whether this is \(first) or \(second): the account holds neither; record it by hand")
    case "no_amount":
      return type.map { String(localized: "\($0) row has no amount") }
    case "needs_symbol":
      return type.map { String(localized: "\($0) needs a symbol.") }
    case "negative_amount":
      return type.map { String(localized: "negative amount on a \($0) (a reversal or correction?); record it by hand") }
    case "positive_amount":
      return type.map { String(localized: "positive amount on a \($0) (a reversal or correction?); record it by hand") }
    case "not_finite": return String(localized: "Transaction numbers must be finite.")
    case "quantity_not_positive": return String(localized: "Quantity must be positive.")
    case "price_negative": return String(localized: "Price cannot be negative.")
    case "amount_negative": return String(localized: "Amount cannot be negative.")
    case "fees_negative": return String(localized: "Fees cannot be negative.")
    case "ratio_not_positive": return String(localized: "Split ratio must be positive (e.g. 2 for a 2-for-1).")
    case "transfer_needs_target": return String(localized: "Transfer needs a different target account.")
    case "future_date": return String(localized: "Date cannot be in the future.")
    case "not_a_number": return String(localized: "expected a number like 1234.56")
    case "questrade_unsupported_activity":
      return value.map { String(localized: "Questrade activity type '\($0)' isn't supported") }
    case "questrade_unsupported_action":
      return value.map { String(localized: "Questrade trade action '\($0)' isn't a buy or sell") }
    case "wealthsimple_unsupported_code":
      return value.map { String(localized: "Wealthsimple transaction code '\($0)' isn't supported") }
    case "no_symbol_in_description":
      return String(localized: "couldn't read the symbol from the description")
    case "no_shares_in_description":
      return String(localized: "couldn't read the share count from the description")
    default:
      return nil
    }
  }

  /// Two listings sent as "A B".
  private static func pair(_ arg: MessageArg?) -> (String, String)? {
    let symbols = (arg?.text ?? "").split(separator: " ").map(String.init)
    return symbols.count == 2 ? (symbols[0], symbols[1]) : nil
  }
}
