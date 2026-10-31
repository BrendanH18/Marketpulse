import SwiftUI

struct TransactionSheet: View {
  @StateObject private var draft = TransactionSheetDraft()
  @ObservedObject var model: StatusModel
  /// An existing entry to change with `marketpulse txn edit`, instead of recording a new one.
  var editing: DesktopTransaction? = nil
  @Environment(\.dismiss) private var dismiss
  private var entry: TransactionEntry {
    TransactionEntry(
      type: draft.type, account: draft.account, target: draft.target, date: LedgerDate.string(draft.date),
      symbol: draft.symbol, quantity: draft.quantity, price: draft.price, amount: draft.amount, fees: draft.fees,
      currency: draft.currency, note: draft.note, splitNew: draft.splitNew, splitOld: draft.splitOld,
      priceRequired: crossesRegistered)
  }
  private var accounts: [DesktopAccount] { model.desktop?.accounts ?? [] }
  private func account(_ id: String) -> DesktopAccount? { accounts.first { String($0.id) == id } }
  /// An in-kind move into or out of a registered account, which tax treats as a sale or a new cost base.
  private var crossesRegistered: Bool {
    guard draft.type == "TRANSFER", let from = account(draft.account)?.registered,
      let to = account(draft.target)?.registered
    else { return false }
    return from != to
  }
  /// What the chosen account holds of the symbol now, for share entries.
  private var held: DesktopPosition? {
    model.desktop?.positions.first { String($0.accountId) == draft.account && $0.symbol == entry.symbolCode }
  }
  var body: some View {
    SheetLayout(
      title: editing == nil ? "Record a transaction" : "Edit transaction",
      subtitle: editing == nil
        ? "Add an entry to your local ledger. This doesn't place a trade."
        : "Change this entry in your local ledger. Cost base and gains are worked out again.",
      model: model
    ) {
      Form {
        Picker("Type", selection: $draft.type) {
          ForEach(TransactionEntry.types, id: \.self) { Text(TransactionEntry.title($0)).tag($0) }
        }.disabled(editing != nil)
          .help(editing == nil ? "" : "To change the type, delete this entry and record a new one.")
        Picker(draft.type == "TRANSFER" ? "From account" : "Account", selection: $draft.account) {
          Text("Choose account").tag("")
          ForEach(accounts) { Text($0.name).tag(String($0.id)) }
        }
        if draft.type == "TRANSFER" {
          Picker("To account", selection: $draft.target) {
            Text("Choose account").tag("")
            ForEach(accounts.filter { String($0.id) != draft.account }) { Text($0.name).tag(String($0.id)) }
          }
        }
        DatePicker("Date", selection: $draft.date, in: ...Date.now, displayedComponents: .date)
        if entry.needsSymbol {
          TextField("Symbol", text: $draft.symbol, prompt: Text("XEQT.TO"))
          if let note = holdingNote { caption(note) }
        }
        fields
        if entry.usesCurrency {
          TextField(
            draft.type == "TRANSFER" ? "Currency of the price" : "Transaction currency", text: $draft.currency,
            prompt: Text("Automatic"))
          caption(
            "Leave blank to use the symbol's listing currency (or the account's for cash entries). Enter one if the price is in another currency."
          )
        }
        TextField("Note (optional)", text: $draft.note)
      }.formStyle(.grouped).disabled(model.saving || draft.request != nil)
      .onAppear {
        if let editing, !draft.loaded {
          draft.load(editing)
        } else if draft.account.isEmpty, let id = model.desktop?.settings?.defaultAccountId,
          accounts.contains(where: { $0.id == id })
        {
          // Settings › Portfolio › Default account, when it's one of the accounts listed.
          draft.account = String(id)
        }
      }
      .onChange(of: draft.symbol) { _, _ in
        // The original currency belongs to the original symbol: work it out again for a new
        // one, unless the user typed a currency themselves.
        if let editing, entry.symbolCode != editing.symbol, entry.currencyCode == editing.currency {
          draft.currency = ""
        }
      }
      .onChange(of: draft.account) { _, account in
        if draft.target == account { draft.target = "" }
      }
      if draft.request != nil && !model.saving {
        Text("The save outcome is unknown. Retry the same entry before changing or closing it.")
          .font(.caption).foregroundStyle(.secondary)
      }
      HStack {
        Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction).disabled(model.saving || draft.request != nil)
        Spacer()
        if model.saving { ProgressView().controlSize(.small) }
        Button(editing != nil ? "Save changes" : draft.request == nil ? "Save transaction" : "Retry save") {
          if let editing {
            // An edit sets the same values again when repeated, so it needs no save receipt.
            let args = entry.editArguments(id: editing.id, revision: editing.revisionArguments)
            Task { if await model.perform(args, success: "Transaction updated") { dismiss() } }
            return
          }
          let attempt = draft.request ?? TransactionSaveRequest(arguments: entry.arguments())
          draft.request = attempt
          Task {
            switch await model.recordTransaction(attempt) {
            case .recorded, .recovered: dismiss()
            case .notRecorded: draft.request = nil
            case .unknown: break
            }
          }
        }
        .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction).disabled(
          !entry.isValid() || !model.canEdit)
      }
    }.interactiveDismissDisabled(model.saving || draft.request != nil)
  }

  @ViewBuilder private var fields: some View {
    switch draft.type {
    case "BUY", "SELL":
      NumberField(title: "Quantity", text: $draft.quantity)
      NumberField(title: "Price per share", text: $draft.price)
      NumberField(title: "Fees", text: $draft.fees)
    case "DRIP":
      NumberField(title: "New shares", text: $draft.quantity)
      NumberField(title: "Price per share", text: $draft.price)
      caption("The reinvested dividend counts as income and adds to the cost base. No cash moves.")
    case "TRANSFER":
      NumberField(title: "Quantity", text: $draft.quantity)
      NumberField(title: entry.priceRequired ? "Market price per share" : "Market price (optional)", text: $draft.price)
      caption(
        entry.priceRequired
          ? "Moving shares into a registered account counts as selling them at market value for tax (a loss is denied), and moving them out sets a new cost base at market value. Enter the price on the transfer date."
          : "The shares move at their cost base. A price is only needed between a registered and a non-registered account."
      )
    case "SPLIT":
      NumberField(title: "New shares", text: $draft.splitNew)
      NumberField(title: "For every old share(s)", text: $draft.splitOld)
      caption(splitNote)
    case "ROC":
      NumberField(title: "Amount", text: $draft.amount)
      caption(
        "Funds and ETFs report it in box 42 of the T3 slip. It lowers the cost base; once that reaches zero, the rest counts as a capital gain."
      )
    default:
      NumberField(title: "Amount", text: $draft.amount)
    }
  }

  /// For entries that act on shares already held: how many there are now.
  private var holdingNote: String? {
    guard ["TRANSFER", "SPLIT", "ROC"].contains(draft.type), !entry.symbolCode.isEmpty, !draft.account.isEmpty
    else { return nil }
    let name = account(draft.account)?.name ?? "This account"
    if let held { return "\(name) holds \(Self.quantity(held.quantity)) \(held.symbol) now." }
    return draft.type == "ROC"
      ? "\(name) holds no \(entry.symbolCode) now. A return of capital only lowers the cost of shares held on its date."
      : "\(name) holds no \(entry.symbolCode) now. An earlier date is checked against what it held then."
  }

  private var splitNote: String {
    let example = "For a 2-for-1 split, enter 2 and 1; for a 1-for-10 consolidation, 1 and 10."
    guard let ratio = entry.ratio(), ratio != 1, let held else { return example + " The cost base doesn't change." }
    return
      "\(Self.quantity(held.quantity)) \(held.symbol) become \(Self.quantity(held.quantity * ratio)), at the same total cost base. \(example)"
  }

  private static func quantity(_ value: Double) -> String {
    value.formatted(.number.precision(.fractionLength(0...6)))
  }

  private func caption(_ text: String) -> some View {
    Text(text).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
  }
}

struct AccountSheet: View {
  @StateObject private var draft = AccountSheetDraft()
  @ObservedObject var model: StatusModel
  /// An existing account to change with `marketpulse accounts edit`, instead of creating one.
  var editing: DesktopAccount? = nil
  @Environment(\.dismiss) private var dismiss
  private var name: String { draft.name.trimmingCharacters(in: .whitespaces) }
  private var currency: String { CurrencyInput.normalize(draft.currency) }
  var body: some View {
    SheetLayout(
      title: editing == nil ? "A home for your investments" : "Edit account",
      subtitle: editing == nil
        ? "Create an account in your existing portfolio."
        : "Change how this account is named and tracked. Its transactions stay as they are.",
      model: model
    ) {
      Form {
        TextField("Account name", text: $draft.name, prompt: Text("My TFSA"))
        Picker("Type", selection: $draft.type) {
          ForEach(DesktopAccount.types, id: \.self) { Text($0).tag($0) }
        }
        if let editing, draft.type != editing.type {
          caution(
            "The type decides whether gains in this account are taxable and which contribution room it counts against. Both are worked out again."
          )
        }
        TextField("Currency", text: $draft.currency)
        if let editing, currency != editing.currency, hasActivity(editing) {
          caution(
            "Entries saved without a currency of their own are read in the account's currency, so changing it can change what they're worth."
          )
        }
        TextField("Institution (optional)", text: $draft.institution)
        Toggle("Track cash balance", isOn: $draft.cash)
        Text(
          "When enabled, record deposits and withdrawals so purchases and sales are reflected in cash. Otherwise, only holdings are included."
        ).font(.caption).foregroundStyle(.secondary)
      }.formStyle(.grouped).disabled(model.saving)
        .onAppear { if let editing, !draft.loaded { draft.load(editing) } }
      HStack {
        Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction).disabled(model.saving)
        if editing != nil {
          Button("Archive…") { draft.confirmArchive = true }.disabled(!model.canEdit)
            .help("Hide this account everywhere and leave it out of your totals")
        }
        Spacer()
        if model.saving { ProgressView().controlSize(.small) }
        Button(editing == nil ? "Create account" : "Save changes") {
          Task { if await model.perform(arguments, success: editing == nil ? "Account created" : "Account updated") { dismiss() } }
        }.buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
          .disabled(!model.canEdit || name.isEmpty || !CurrencyInput.isValid(currency))
      }
    }
    .confirmationDialog(
      "Archive \(editing?.name ?? "this account")?", isPresented: $draft.confirmArchive, presenting: editing
    ) { account in
      Button("Archive") {
        Task {
          if await model.perform(
            ["accounts", "edit", "--archive"] + account.revisionArguments + ["--", String(account.id)],
            success: "Archived \(account.name). You can unarchive it in Settings › Data.")
          {
            dismiss()
          }
        }
      }
      Button("Cancel", role: .cancel) {}
    } message: { _ in
      // Stated whenever it might apply: the engine pauses on any non-zero cash balance in any
      // currency, which the account's net value can't show (balances can offset, or lack a rate).
      Text(
        "It will be hidden everywhere in MarketPulse and left out of your totals. Its transactions are kept, and you can unarchive it in Settings › Data. While it still holds investments or cash, daily net-worth snapshots pause until you move or sell them, or unarchive it."
      )
    }
  }

  private var arguments: [String] {
    guard let editing else {
      return [
        "accounts", "add", "--type", draft.type, "--currency", currency, "--institution", draft.institution,
      ] + (draft.cash ? ["--track-cash"] : []) + ["--", name]
    }
    // Every field the form shows, so the account ends up exactly as the form reads.
    return [
      "accounts", "edit", "--name", name, "--type", draft.type, "--currency", currency,
      "--institution", draft.institution, draft.cash ? "--track-cash" : "--no-track-cash",
    ] + editing.revisionArguments + ["--", String(editing.id)]
  }

  private func hasActivity(_ account: DesktopAccount) -> Bool {
    model.desktop?.activity.contains { $0.accountId == account.id } ?? false
  }

  private func caution(_ text: String) -> some View {
    Text(text).font(.caption).foregroundStyle(Studio.warn).fixedSize(horizontal: false, vertical: true)
  }
}

/// Contribution room as CRA reported it on January 1 of a year (`marketpulse accounts room`).
struct RoomSheet: View {
  @StateObject private var draft = RoomSheetDraft()
  @ObservedObject var model: StatusModel
  let type: String
  @Environment(\.dismiss) private var dismiss
  private static let currentYear = Calendar.current.component(.year, from: .now)
  private var saved: ContributionRoom? { model.desktop?.room.first { $0.accountType == draft.type } }
  private var years: [Int] {
    Array(stride(from: Self.currentYear, through: min(ContributionRoom.firstYear(draft.type), draft.year), by: -1))
  }
  var body: some View {
    SheetLayout(
      title: "Contribution room",
      subtitle:
        "Enter the room CRA reported for January 1 of a year. You'll find it in CRA My Account or on your notice of assessment.",
      model: model
    ) {
      Form {
        Picker("Account type", selection: $draft.type) {
          ForEach(ContributionRoom.types, id: \.self) { Text($0).tag($0) }
        }
        Picker("Room on January 1 of", selection: $draft.year) {
          ForEach(years, id: \.self) { Text(String($0)).tag($0) }
        }
        NumberField(title: "Room in CAD", text: $draft.amount)
        Text(explanation).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        if let saved {
          Text(
            "Replaces the room you entered before: \(Format.money(saved.startingRoom, "CAD", privacy: model.status?.privacy ?? false)) on January 1, \(String(saved.asOfYear))."
          ).font(.caption).foregroundStyle(.secondary)
        }
      }.formStyle(.grouped).disabled(model.saving)
        .onAppear {
          guard !draft.loaded else { return }
          draft.loaded = true
          draft.type = type
          load()
        }
        .onChange(of: draft.type) { _, _ in load() }
      HStack {
        Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction).disabled(model.saving)
        Spacer()
        if model.saving { ProgressView().controlSize(.small) }
        Button("Save room") {
          let args = ["accounts", "room", "--", draft.type, String(draft.year), NumberInput.cli(draft.amount)]
          Task { if await model.perform(args, success: "\(draft.type) contribution room saved") { dismiss() } }
        }.buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
          .disabled(!model.canEdit || NumberInput.parse(draft.amount) == nil)
      }
    }
  }

  /// What MarketPulse does with the figure, which differs by account type.
  private var explanation: String {
    switch draft.type {
    case "TFSA":
      return
        "Each new year's limit is added for you, and withdrawals are added back the following January. Deposits to your TFSA accounts are subtracted. Enter a negative amount if you've over-contributed."
    case "FHSA":
      return
        "Each year's $8,000 is added for you, with up to $8,000 of unused room carried forward and the $40,000 lifetime limit applied. Deposits to your FHSA accounts are subtracted."
    default:
      return
        "RRSP room doesn't grow on its own here: enter the new figure from each year's notice of assessment. Deposits to your RRSP accounts are subtracted."
    }
  }

  /// The room saved for the chosen type, so it can be corrected; otherwise this year, blank.
  private func load() {
    if let saved {
      draft.year = saved.asOfYear
      draft.amount = NumberInput.editable(saved.startingRoom)
    } else {
      draft.year = Self.currentYear
      draft.amount = ""
    }
  }
}

struct AlertSheet: View {
  @StateObject private var draft = AlertSheetDraft()
  @ObservedObject var model: StatusModel
  @Environment(\.dismiss) private var dismiss
  var body: some View {
    SheetLayout(
      title: "Keep an eye on a price",
      subtitle: "Alerts are checked while the app or automation runner is active.", model: model
    ) {
      Form {
        TextField("Symbol", text: $draft.symbol, prompt: Text("XEQT.TO"))
        Picker("Condition", selection: $draft.condition) {
          Text("Price at or above").tag("above")
          Text("Price at or below").tag("below")
          Text("Daily gain (%)").tag("up_pct")
          Text("Daily decline (%)").tag("down_pct")
        }
        NumberField(
          title: draft.condition.contains("pct") ? "Percentage" : "Price in listing currency",
          text: $draft.threshold)
        TextField("Note (optional)", text: $draft.note)
      }.formStyle(.grouped)
      HStack {
        Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction).disabled(model.saving)
        Spacer()
        Button("Create alert") {
          Task {
            if await model.perform(
              [
                "alerts", "add", "--note", draft.note, "--",
                draft.symbol.trimmingCharacters(in: .whitespaces).uppercased(), draft.condition,
                NumberInput.cli(draft.threshold),
              ], success: "Price alert created")
            {
              dismiss()
            }
          }
        }.buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
          .disabled(
            !model.canEdit || draft.symbol.trimmingCharacters(in: .whitespaces).isEmpty
              || !positive(draft.threshold))
      }
    }
  }
}

/// A GIC or bond (`asset fixed`), an asset valued by hand (`asset manual`), or a new valuation
/// of one (`asset value`). Each records a ledger entry, so it saves with a request ID like a transaction.
struct AssetSheet: View {
  @StateObject private var draft = AssetSheetDraft()
  @ObservedObject var model: StatusModel
  /// An `AssetEntry.kinds` value.
  let kind: String
  /// The asset a valuation is for.
  var symbol = ""
  @Environment(\.dismiss) private var dismiss
  private var entry: AssetEntry {
    AssetEntry(
      kind: kind, account: draft.account, symbol: kind == "VALUE" ? symbol : draft.symbol, name: draft.name,
      value: draft.value, rate: draft.rate, date: LedgerDate.string(draft.date),
      maturity: LedgerDate.string(draft.maturity), compounding: draft.compounding, assetClass: draft.assetClass,
      currency: draft.currency)
  }
  private var accounts: [DesktopAccount] { model.desktop?.accounts ?? [] }
  /// A new asset can't reuse a symbol: its details would replace the other one's.
  private var taken: Bool {
    guard kind != "VALUE", !entry.symbolCode.isEmpty, let desktop = model.desktop else { return false }
    return desktop.assets?.contains { $0.symbol == entry.symbolCode } == true
      || desktop.positions.contains { $0.symbol == entry.symbolCode }
  }
  private var held: DesktopPosition? { model.desktop?.positions.first(where: { $0.symbol == symbol }) }
  private var valueTitle: String {
    guard let held else { return "New value" }
    return "New value (\(held.currency))"
  }
  private var title: String {
    switch kind {
    case "FIXED": return "Add a GIC or bond"
    case "MANUAL": return "Add an asset you value yourself"
    default: return "Record a valuation"
    }
  }
  private var subtitle: String {
    switch kind {
    case "FIXED":
      return "It's valued by the interest it earns, up to maturity. The principal is recorded as a purchase on the start date."
    case "MANUAL":
      return "Property, private shares, a pension, collectibles: anything the market can't price. Update its value whenever you like."
    default:
      return "What \(symbol) is worth now. Its value in your portfolio uses the latest valuation."
    }
  }
  var body: some View {
    SheetLayout(title: title, subtitle: subtitle, model: model) {
      Form {
        if kind == "VALUE" {
          LabeledContent("Asset", value: held.map { "\($0.symbol) · \($0.name)" } ?? symbol)
          if let held {
            LabeledContent(
              "Current value",
              value: Format.money(held.price, held.currency, privacy: model.status?.privacy ?? false))
          }
          NumberField(title: valueTitle, text: $draft.value)
          DatePicker("Valued on", selection: $draft.date, in: ...Date.now, displayedComponents: .date)
        } else {
          Picker("Account", selection: $draft.account) {
            Text("Choose account").tag("")
            ForEach(accounts) { Text($0.name).tag(String($0.id)) }
          }
          TextField("Symbol", text: $draft.symbol, prompt: Text(kind == "FIXED" ? "GIC-2027" : "COTTAGE"))
          if taken {
            caution("\(entry.symbolCode) is already in your portfolio. Choose another symbol.")
          } else {
            caption("A short code of your own. It names the asset in Holdings and Activity.")
          }
          TextField("Name (optional)", text: $draft.name, prompt: Text(kind == "FIXED" ? "2-year GIC" : "Family cottage"))
          if kind == "FIXED" {
            NumberField(title: "Principal", text: $draft.value)
            NumberField(title: "Annual rate (%)", text: $draft.rate)
            DatePicker("Start date", selection: $draft.date, in: ...Date.now, displayedComponents: .date)
            DatePicker("Matures on", selection: $draft.maturity, displayedComponents: .date)
            if entry.maturity <= entry.date { caution("The maturity date must be after the start date.") }
            Picker("Compounding", selection: $draft.compounding) {
              ForEach(AssetEntry.compoundings, id: \.self) { Text($0.capitalized).tag($0) }
            }
          } else {
            NumberField(title: "Value", text: $draft.value)
            Picker("Asset class", selection: $draft.assetClass) {
              ForEach(AssetClassOption.all) { Text($0.label).tag($0.key) }
            }
            DatePicker("Acquired on", selection: $draft.date, in: ...Date.now, displayedComponents: .date)
          }
          TextField("Currency", text: $draft.currency, prompt: Text("Account's currency"))
        }
      }.formStyle(.grouped).disabled(model.saving || draft.request != nil)
        .onAppear {
          if draft.account.isEmpty, let id = model.desktop?.settings?.defaultAccountId,
            accounts.contains(where: { $0.id == id })
          {
            draft.account = String(id)
          }
        }
      if draft.request != nil && !model.saving {
        Text("The save outcome is unknown. Retry the same entry before changing or closing it.")
          .font(.caption).foregroundStyle(.secondary)
      }
      HStack {
        Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction).disabled(model.saving || draft.request != nil)
        Spacer()
        if model.saving { ProgressView().controlSize(.small) }
        Button(draft.request == nil ? (kind == "VALUE" ? "Save valuation" : "Add asset") : "Retry save") {
          let attempt =
            draft.request
            ?? TransactionSaveRequest(arguments: entry.arguments(), commandWords: AssetEntry.commandWords)
          draft.request = attempt
          let success = kind == "VALUE" ? "Valuation recorded" : "\(entry.symbolCode) added"
          Task {
            switch await model.recordTransaction(attempt, success: success) {
            case .recorded, .recovered: dismiss()
            case .notRecorded: draft.request = nil
            case .unknown: break
            }
          }
        }
        .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
        .disabled(!entry.isValid() || taken || !model.canEdit)
      }
    }.interactiveDismissDisabled(model.saving || draft.request != nil)
  }

  private func caption(_ text: String) -> some View {
    Text(text).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
  }

  private func caution(_ text: String) -> some View {
    Text(text).font(.caption).foregroundStyle(Studio.warn).fixedSize(horizontal: false, vertical: true)
  }
}

/// The asset class a symbol counts toward in Allocation (`marketpulse asset classify`).
struct AssetClassSheet: View {
  @StateObject private var draft = AssetClassSheetDraft()
  @ObservedObject var model: StatusModel
  let symbol: String
  @Environment(\.dismiss) private var dismiss
  /// The class shown in Holdings now: the saved one, or the one the listing reports.
  private var current: String? {
    if let saved = model.desktop?.assets?.first(where: { $0.symbol == symbol })?.assetClass { return saved }
    let label = model.desktop?.positions.first(where: { $0.symbol == symbol })?.assetClass
    return AssetClassOption.all.first { $0.label == label }?.key
  }
  var body: some View {
    SheetLayout(
      title: "Change asset class",
      subtitle: "Which class \(symbol) counts toward in Allocation and your targets, in every account.",
      model: model
    ) {
      Form {
        Picker("Asset class", selection: $draft.key) {
          ForEach(AssetClassOption.all) { Text($0.label).tag($0.key) }
        }
      }.formStyle(.grouped).disabled(model.saving)
        .onAppear {
          guard !draft.loaded else { return }
          draft.loaded = true
          draft.key = current ?? "other"
        }
      HStack {
        Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction).disabled(model.saving)
        Spacer()
        if model.saving { ProgressView().controlSize(.small) }
        Button("Save") {
          let label = AssetClassOption.all.first(where: { $0.key == draft.key })?.label ?? draft.key
          Task {
            if await model.perform(["asset", "classify", "--", symbol, draft.key], success: "\(symbol) counts as \(label)") {
              dismiss()
            }
          }
        }.buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
          .disabled(!model.canEdit || draft.key == current)
      }
    }
  }
}

/// Target percentages per asset class (`marketpulse allocation --target`). Saving replaces them all.
struct TargetsSheet: View {
  @StateObject private var draft = TargetsSheetDraft()
  @ObservedObject var model: StatusModel
  @Environment(\.dismiss) private var dismiss
  private var entry: TargetsEntry { TargetsEntry(weights: draft.weights) }
  private func now(_ key: String) -> String {
    let weight = model.desktop?.allocation.first(where: { $0.key == key })?.weight ?? 0
    return "Now " + weight.formatted(.number.precision(.fractionLength(1))) + "%"
  }
  private func binding(_ key: String) -> Binding<String> {
    Binding(get: { draft.weights[key] ?? "" }, set: { draft.weights[key] = $0 })
  }
  var body: some View {
    SheetLayout(
      title: "Allocation targets",
      subtitle: "The share of your portfolio you want in each asset class. Leave a class blank for none.",
      model: model
    ) {
      Form {
        ForEach(AssetClassOption.all) { option in
          LabeledContent {
            TextField("Target for \(option.label) (%)", text: binding(option.key), prompt: Text("None"))
              .labelsHidden().multilineTextAlignment(.trailing).frame(width: 90)
          } label: {
            Text(option.label)
            Text(model.status?.privacy == true ? "" : now(option.key))
          }
        }
        LabeledContent("Total", value: entry.total().formatted(.number.precision(.fractionLength(0...2))) + "%")
        if !entry.isValid() {
          Text("Each target is a percentage from 0 to 100, and together they can't pass 100%.")
            .font(.caption).foregroundStyle(Studio.warn).fixedSize(horizontal: false, vertical: true)
        }
      }.formStyle(.grouped).disabled(model.saving).frame(maxHeight: 460)
        .onAppear {
          guard !draft.loaded else { return }
          draft.loaded = true
          for target in model.desktop?.targets ?? [] {
            draft.weights[target.bucket] = NumberInput.editable(target.weight)
          }
        }
      HStack {
        Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction).disabled(model.saving)
        Button("Clear all") { draft.weights = [:] }.disabled(model.saving || draft.weights.values.allSatisfy(\.isEmpty))
        Spacer()
        if model.saving { ProgressView().controlSize(.small) }
        Button("Save targets") {
          Task { if await model.perform(entry.arguments(), success: "Allocation targets saved") { dismiss() } }
        }.buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
          .disabled(!model.canEdit || !entry.isValid())
      }
    }
  }
}

struct ImportSheet: View {
  @ObservedObject var model: StatusModel
  var body: some View {
    SheetLayout(
      title: "A clearer way to import",
      subtitle: model.importName.isEmpty ? "CSV import" : model.importName, model: model
    ) {
      Picker("Broker format", selection: $model.importProfile) {
        ForEach(ImportProfile.all) { Text($0.label).tag($0.id) }
      }.onChange(of: model.importProfile) { _, _ in model.importPreview = nil }.disabled(model.saving)
      Picker("Default account for rows without one", selection: $model.importAccount) {
        Text("Use accounts named in the CSV").tag("")
        ForEach(model.desktop?.accounts ?? []) { Text($0.name).tag(String($0.id)) }
      }.onChange(of: model.importAccount) { _, _ in model.importPreview = nil }.disabled(model.saving)
      Button("Preview import") { Task { await model.previewImport() } }.disabled(model.saving)
      if let preview = model.importPreview {
        if let label = preview.profileLabel {
          Text(model.importProfile == "auto" ? "Detected format: \(label)" : "Read as: \(label)")
            .font(.callout).foregroundStyle(.secondary)
        }
        HStack(spacing: 24) {
          previewCount("New entries", preview.added)
          previewCount("Duplicates", preview.duplicates)
          previewCount("Skipped", preview.skipped.count)
        }.padding(.vertical, 8)
        if !preview.accountsCreated.isEmpty {
          Text("New accounts: \(preview.accountsCreated.joined(separator: ", "))").font(.callout)
        }
        if let issues = preview.issues, !issues.isEmpty {
          skippedTable(issues)
        } else if !preview.skipped.isEmpty {
          ScrollView {
            VStack(alignment: .leading, spacing: 8) {
              ForEach(preview.skipped) { issue in
                Text("Line \(issue.line): \(issue.reason)").font(.caption).foregroundStyle(Studio.warn)
              }
            }
          }.frame(maxHeight: 160)
        }
        if let duplicates = preview.duplicateRows, !duplicates.isEmpty {
          duplicateList(duplicates)
        }
        Text(
          "Only valid new rows will be imported. Skipped rows stay out of the ledger. A safety backup is taken before the import."
        ).font(.caption).foregroundStyle(.secondary)
      } else {
        Text(
          "Preview reads your broker's export, checks for duplicates, and lists any rows it can't use, without changing the ledger."
        )
        .font(.callout).foregroundStyle(.secondary).padding(.vertical, 16)
      }
      HStack {
        Button("Cancel") { model.closeImport() }.keyboardShortcut(.cancelAction).disabled(
          model.saving)
        Spacer()
        if model.saving { ProgressView().controlSize(.small) }
        Button("Import \(model.importPreview?.added ?? 0) entries") {
          Task { await model.commitImport() }
        }
        .buttonStyle(.borderedProminent).disabled(
          !model.canEdit || (model.importPreview?.added ?? 0) == 0)
      }
    }
  }

  private var privacy: Bool { model.status?.privacy ?? false }

  /// Each skipped line with the field at fault, its value, and why, so the file can be fixed.
  private func skippedTable(_ issues: [ImportRowIssue]) -> some View {
    VStack(alignment: .leading, spacing: 6) {
      Text("Skipped lines").font(.callout.weight(.semibold))
      ScrollView {
        Grid(alignment: .leadingFirstTextBaseline, horizontalSpacing: 12, verticalSpacing: 6) {
          GridRow {
            Text("Line")
            Text("Field")
            Text("Value")
            Text("Reason")
          }.font(.caption.weight(.semibold)).foregroundStyle(.secondary)
          ForEach(issues) { issue in
            GridRow {
              Text("\(issue.line)").monospacedDigit()
              Text(issue.field.isEmpty ? "—" : issue.field)
              // Values come from the file and may be amounts; privacy mode hides them.
              Text(issue.value.isEmpty ? "—" : privacy ? Format.mask : issue.value)
                .lineLimit(1).truncationMode(.middle).frame(maxWidth: 110, alignment: .leading)
              Text(issue.reason).foregroundStyle(Studio.warn).fixedSize(horizontal: false, vertical: true)
            }
          }
        }.font(.caption).textSelection(.enabled)
      }.frame(maxHeight: 180)
    }
  }

  private func duplicateList(_ duplicates: [ImportDuplicate]) -> some View {
    DisclosureGroup("Duplicates already in the ledger (\(duplicates.count))") {
      VStack(alignment: .leading, spacing: 4) {
        ForEach(duplicates.prefix(20)) { row in
          Text(privacy ? "Line \(row.line)" : "Line \(row.line): \(row.summary)")
        }
        if duplicates.count > 20 {
          Text("…and \(duplicates.count - 20) more").foregroundStyle(.secondary)
        }
      }.font(.caption).frame(maxWidth: .infinity, alignment: .leading).padding(.top, 4)
    }.font(.callout)
  }

  private func previewCount(_ title: String, _ count: Int) -> some View {
    VStack(alignment: .leading, spacing: 6) {
      Text("\(count)").font(.title2).monospacedDigit()
      Text(title).font(.caption).foregroundStyle(.secondary)
    }
  }
}

/// First-run choices for a new ledger; also reachable from Help.
struct WelcomeSheet: View {
  @ObservedObject var model: StatusModel
  let createAccount: () -> Void
  let importCSV: () -> Void
  let exploreDemo: () -> Void
  @Environment(\.dismiss) private var dismiss
  private static let currencies = ["CAD", "USD", "EUR", "GBP"]

  var body: some View {
    SheetLayout(
      title: "Welcome to MarketPulse",
      subtitle:
        "Track your TFSA, RRSP, FHSA, and non-registered accounts. MarketPulse works out your adjusted cost base as you go.",
      model: model
    ) {
      VStack(spacing: 10) {
        choice(
          "Create your first account", icon: "building.columns",
          detail: "Add an account, then record what you bought or deposited.", action: createAccount
        ).disabled(model.demoOnly)
        choice(
          "Import a CSV", icon: "square.and.arrow.down",
          detail: "Bring in transactions exported from your broker. You'll see a preview before anything is saved.",
          action: importCSV
        ).disabled(model.demoOnly)
        if model.demo {
          choice(
            "Leave the demo", icon: "arrow.uturn.backward",
            detail: "Go back to your own portfolio.", action: { model.leaveDemo(); dismiss() }
          ).disabled(model.demoOnly)
        } else {
          choice(
            "Explore a demo portfolio", icon: "sparkles",
            detail: "Look around with fictional investments. Nothing is saved, and you can leave the demo at any time.",
            action: exploreDemo
          ).disabled(!model.canEnterDemo)
        }
      }.disabled(model.saving)
      if !model.demo, let base = model.status?.base {
        Picker("Show totals in", selection: baseCurrency(base)) {
          ForEach(Self.currencies.contains(base) ? Self.currencies : [base] + Self.currencies, id: \.self) {
            Text($0).tag($0)
          }
        }.disabled(!model.canEdit)
        Text("Each account keeps its own currency. Totals are converted to this one.")
          .font(.caption).foregroundStyle(.secondary)
      }
      Label {
        Text(
          "Your portfolio stays on this Mac, in \(folder). It's never uploaded. MarketPulse goes online only to look up prices and exchange rates."
        ).fixedSize(horizontal: false, vertical: true)
      } icon: {
        Image(systemName: "lock.shield")
      }.font(.callout).foregroundStyle(.secondary)
      HStack {
        Spacer()
        Button("Not now") { dismiss() }.keyboardShortcut(.cancelAction)
      }
    }
  }

  /// The ledger's folder, written the way Finder users think of it.
  private var folder: String {
    guard let path = model.dataDir else { return "a MarketPulse folder in your home folder" }
    let home = NSHomeDirectory()
    return path.hasPrefix(home + "/") ? "~" + path.dropFirst(home.count) : path
  }

  private func baseCurrency(_ current: String) -> Binding<String> {
    Binding(get: { current }, set: { if $0 != current { model.setConfig("base_currency", $0) } })
  }

  private func choice(
    _ title: String, icon: String, detail: String, action: @escaping () -> Void
  ) -> some View {
    Button(action: action) {
      HStack(spacing: 14) {
        Image(systemName: icon).font(.title2).frame(width: 30).foregroundStyle(.tint)
        VStack(alignment: .leading, spacing: 3) {
          Text(title).font(.headline)
          Text(detail).font(.callout).foregroundStyle(.secondary).fixedSize(
            horizontal: false, vertical: true)
        }
        Spacer(minLength: 0)
        Image(systemName: "chevron.right").foregroundStyle(.secondary)
      }.padding(14).frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 10))
        .contentShape(RoundedRectangle(cornerRadius: 10))
    }.buttonStyle(.plain)
  }
}

private struct SheetLayout<Content: View>: View {
  let title: String
  let subtitle: String
  @ObservedObject var model: StatusModel
  @ViewBuilder let content: Content
  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      Text(title).font(.title2.weight(.semibold))
      Text(subtitle).font(.callout).foregroundStyle(.secondary)
      if let error = model.errorMessage {
        Text(error).font(.callout).foregroundStyle(Studio.red).fixedSize(
          horizontal: false, vertical: true
        ).textSelection(.enabled)
      }
      content
    }.padding(28).frame(width: 520).fixedSize(horizontal: false, vertical: true)
      .interactiveDismissDisabled(model.saving)
  }
}

private func positive(_ value: String) -> Bool { (NumberInput.parse(value) ?? 0) > 0 }
private func nonnegative(_ value: String) -> Bool { (NumberInput.parse(value) ?? -1) >= 0 }

/// A number field that explains how it reads the entry, instead of silently disabling Save.
private struct NumberField: View {
  let title: String
  @Binding var text: String
  var body: some View {
    TextField(title, text: $text)
    if let hint = NumberInput.hint(text) {
      Text(hint).font(.caption).foregroundStyle(
        NumberInput.parse(text) == nil ? AnyShapeStyle(Studio.warn) : AnyShapeStyle(.secondary))
    }
  }
}

private final class TransactionSheetDraft: ObservableObject {
  @Published var request: TransactionSaveRequest?
  /// Whether `load` has filled in the entry being edited (only once, so edits aren't reset).
  var loaded = false
  @Published var type = "BUY"
  @Published var account = ""
  @Published var target = ""
  @Published var symbol = ""
  @Published var quantity = ""
  @Published var price = ""
  @Published var amount = ""
  @Published var fees = "0"
  @Published var currency = ""
  @Published var note = ""
  @Published var date = Date.now
  @Published var splitNew = "2"
  @Published var splitOld = "1"

  func load(_ t: DesktopTransaction) {
    loaded = true
    type = t.type
    account = String(t.accountId)
    symbol = t.symbol
    quantity = NumberInput.editable(t.quantity)
    price = NumberInput.editable(t.price)
    amount = NumberInput.editable(t.amount)
    fees = NumberInput.editable(t.fees)
    currency = t.currency
    note = t.note
    date = LedgerDate.date(t.date) ?? date
  }
}

private final class AccountSheetDraft: ObservableObject {
  /// Whether `load` has filled in the account being edited (only once, so edits aren't reset).
  var loaded = false
  @Published var name = ""
  @Published var type = "TFSA"
  @Published var currency = "CAD"
  @Published var institution = ""
  @Published var cash = false
  @Published var confirmArchive = false

  func load(_ account: DesktopAccount) {
    loaded = true
    name = account.name
    type = account.type
    currency = account.currency
    institution = account.institution
    cash = account.trackCash
  }
}

private final class RoomSheetDraft: ObservableObject {
  var loaded = false
  @Published var type = "TFSA"
  @Published var year = Calendar.current.component(.year, from: .now)
  @Published var amount = ""
}

private final class AlertSheetDraft: ObservableObject {
  @Published var symbol = ""
  @Published var condition = "above"
  @Published var threshold = ""
  @Published var note = ""
}

private final class AssetSheetDraft: ObservableObject {
  @Published var request: TransactionSaveRequest?
  @Published var account = ""
  @Published var symbol = ""
  @Published var name = ""
  /// The principal (GIC or bond), value (an asset you value yourself), or new value (a valuation).
  @Published var value = ""
  @Published var rate = ""
  @Published var date = Date.now
  @Published var maturity = Calendar.current.date(byAdding: .year, value: 1, to: .now) ?? .now
  @Published var compounding = "annual"
  @Published var assetClass = "real_estate"
  @Published var currency = ""
}

private final class AssetClassSheetDraft: ObservableObject {
  var loaded = false
  @Published var key = "other"
}

private final class TargetsSheetDraft: ObservableObject {
  var loaded = false
  @Published var weights: [String: String] = [:]
}
