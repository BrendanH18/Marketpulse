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
      title: editing == nil ? String(localized: "Record a transaction") : String(localized: "Edit transaction"),
      subtitle: editing == nil
        ? String(localized: "Add an entry to your local ledger. This doesn't place a trade.")
        : String(localized: "Change this entry in your local ledger. Cost base and gains are worked out again."),
      model: model
    ) {
      Form {
        Picker("Type", selection: $draft.type) {
          ForEach(TransactionEntry.types, id: \.self) { Text(TransactionEntry.title($0)).tag($0) }
        }.disabled(editing != nil)
          .help(editing == nil ? "" : String(localized: "To change the type, delete this entry and record a new one."))
        Picker(
          draft.type == "TRANSFER" ? String(localized: "From account") : String(localized: "Account"),
          selection: $draft.account
        ) {
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
          TextField("Symbol", text: $draft.symbol, prompt: Text(verbatim: "XEQT.TO"))
          if let note = holdingNote { caption(note) }
        }
        fields
        if entry.usesCurrency {
          TextField(
            draft.type == "TRANSFER"
              ? String(localized: "Currency of the price") : String(localized: "Transaction currency"),
            text: $draft.currency,
            prompt: Text("Automatic"))
          caption(
            String(
              localized:
                "Leave blank to use the symbol's listing currency (or the account's for cash entries). Enter one if the price is in another currency."
            ))
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
        Button(
          editing != nil
            ? String(localized: "Save changes")
            : draft.request == nil ? String(localized: "Save transaction") : String(localized: "Retry save")
        ) {
          if let editing {
            // An edit sets the same values again when repeated, so it needs no save receipt.
            let args = entry.editArguments(id: editing.id, revision: editing.revisionArguments)
            Task { if await model.perform(args, success: String(localized: "Transaction updated")) { dismiss() } }
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
      NumberField(title: String(localized: "Quantity"), text: $draft.quantity)
      NumberField(title: String(localized: "Price per share"), text: $draft.price)
      NumberField(title: String(localized: "Fees"), text: $draft.fees)
    case "DRIP":
      NumberField(title: String(localized: "New shares"), text: $draft.quantity)
      NumberField(title: String(localized: "Price per share"), text: $draft.price)
      caption(String(localized: "The reinvested dividend counts as income and adds to the cost base. No cash moves."))
    case "TRANSFER":
      NumberField(title: String(localized: "Quantity"), text: $draft.quantity)
      NumberField(
        title: entry.priceRequired
          ? String(localized: "Market price per share") : String(localized: "Market price (optional)"),
        text: $draft.price)
      caption(
        entry.priceRequired
          ? String(
            localized:
              "Moving shares into a registered account counts as selling them at market value for tax (a loss is denied), and moving them out sets a new cost base at market value. Enter the price on the transfer date."
          )
          : String(
            localized:
              "The shares move at their cost base. A price is only needed between a registered and a non-registered account."
          )
      )
    case "SPLIT":
      NumberField(title: String(localized: "New shares"), text: $draft.splitNew)
      NumberField(title: String(localized: "For every old share(s)"), text: $draft.splitOld)
      caption(splitNote)
    case "ROC":
      NumberField(title: String(localized: "Amount"), text: $draft.amount)
      caption(
        String(
          localized:
            "Funds and ETFs report it in box 42 of the T3 slip. It lowers the cost base; once that reaches zero, the rest counts as a capital gain."
        ))
    default:
      NumberField(title: String(localized: "Amount"), text: $draft.amount)
    }
  }

  /// For entries that act on shares already held: how many there are now.
  private var holdingNote: String? {
    guard ["TRANSFER", "SPLIT", "ROC"].contains(draft.type), !entry.symbolCode.isEmpty, !draft.account.isEmpty
    else { return nil }
    let symbol = entry.symbolCode
    guard let name = account(draft.account)?.name else {
      if let held {
        return String(localized: "This account holds \(Self.quantity(held.quantity)) \(held.symbol) now.")
      }
      return draft.type == "ROC"
        ? String(
          localized:
            "This account holds no \(symbol) now. A return of capital only lowers the cost of shares held on its date.")
        : String(localized: "This account holds no \(symbol) now. An earlier date is checked against what it held then.")
    }
    if let held { return String(localized: "\(name) holds \(Self.quantity(held.quantity)) \(held.symbol) now.") }
    return draft.type == "ROC"
      ? String(
        localized: "\(name) holds no \(symbol) now. A return of capital only lowers the cost of shares held on its date.")
      : String(localized: "\(name) holds no \(symbol) now. An earlier date is checked against what it held then.")
  }

  private var splitNote: String {
    guard let ratio = entry.ratio(), ratio != 1, let held else {
      return String(
        localized:
          "For a 2-for-1 split, enter 2 and 1; for a 1-for-10 consolidation, 1 and 10. The cost base doesn't change.")
    }
    let before = Self.quantity(held.quantity)
    let after = Self.quantity(held.quantity * ratio)
    return String(
      localized:
        "\(before) \(held.symbol) become \(after), at the same total cost base. For a 2-for-1 split, enter 2 and 1; for a 1-for-10 consolidation, 1 and 10."
    )
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
      title: editing == nil ? String(localized: "A home for your investments") : String(localized: "Edit account"),
      subtitle: editing == nil
        ? String(localized: "Create an account in your existing portfolio.")
        : String(localized: "Change how this account is named and tracked. Its transactions stay as they are."),
      model: model
    ) {
      Form {
        TextField("Account name", text: $draft.name, prompt: Text("My TFSA"))
        Picker("Type", selection: $draft.type) {
          ForEach(DesktopAccount.types, id: \.self) { Text(DesktopAccount.typeLabel($0)).tag($0) }
        }
        if let editing, draft.type != editing.type {
          caution(
            String(
              localized:
                "The type decides whether gains in this account are taxable and which contribution room it counts against. Both are worked out again."
            ))
        }
        TextField("Currency", text: $draft.currency)
        if let editing, currency != editing.currency, hasActivity(editing) {
          caution(
            String(
              localized:
                "Entries saved without a currency of their own are read in the account's currency, so changing it can change what they're worth."
            ))
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
        Button(editing == nil ? String(localized: "Create account") : String(localized: "Save changes")) {
          let success = editing == nil ? String(localized: "Account created") : String(localized: "Account updated")
          Task { if await model.perform(arguments, success: success) { dismiss() } }
        }.buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
          .disabled(!model.canEdit || name.isEmpty || !CurrencyInput.isValid(currency))
      }
    }
    .confirmationDialog(
      "Archive \(editing?.name ?? "")?", isPresented: $draft.confirmArchive, presenting: editing
    ) { account in
      Button("Archive") {
        Task {
          if await model.perform(
            ["accounts", "edit", "--archive"] + account.revisionArguments + ["--", String(account.id)],
            success: String(localized: "Archived \(account.name). You can unarchive it in Settings › Data."))
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
      title: String(localized: "Contribution room"),
      subtitle: String(
        localized:
          "Enter the room CRA reported for January 1 of a year. You'll find it in CRA My Account or on your notice of assessment."
      ),
      model: model
    ) {
      Form {
        Picker("Account type", selection: $draft.type) {
          ForEach(ContributionRoom.types, id: \.self) { Text(DesktopAccount.typeLabel($0)).tag($0) }
        }
        Picker("Room on January 1 of", selection: $draft.year) {
          ForEach(years, id: \.self) { Text(String($0)).tag($0) }
        }
        NumberField(title: String(localized: "Room in CAD"), text: $draft.amount)
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
          Task { if await model.perform(args, success: roomSaved) { dismiss() } }
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
        String(
          localized:
            "Each new year's limit is added for you, and withdrawals are added back the following January. Deposits to your TFSA accounts are subtracted. Enter a negative amount if you've over-contributed."
        )
    case "FHSA":
      return
        String(
          localized:
            "Each year's $8,000 is added for you, with up to $8,000 of unused room carried forward and the $40,000 lifetime limit applied. Deposits to your FHSA accounts are subtracted."
        )
    default:
      return
        String(
          localized:
            "RRSP room doesn't grow on its own here: enter the new figure from each year's notice of assessment. Deposits to your RRSP accounts are subtracted."
        )
    }
  }

  /// One sentence per type, so each language can name the account its own way.
  private var roomSaved: String {
    switch draft.type {
    case "TFSA": return String(localized: "TFSA contribution room saved")
    case "FHSA": return String(localized: "FHSA contribution room saved")
    case "RRSP": return String(localized: "RRSP contribution room saved")
    default: return String(localized: "Contribution room saved")
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
      title: String(localized: "Keep an eye on a price"),
      subtitle: String(localized: "Alerts are checked while the app or automation runner is active."), model: model
    ) {
      Form {
        TextField("Symbol", text: $draft.symbol, prompt: Text(verbatim: "XEQT.TO"))
        Picker("Condition", selection: $draft.condition) {
          Text("Price at or above").tag("above")
          Text("Price at or below").tag("below")
          Text("Daily gain (%)").tag("up_pct")
          Text("Daily decline (%)").tag("down_pct")
        }
        NumberField(
          title: draft.condition.contains("pct")
            ? String(localized: "Percentage") : String(localized: "Price in listing currency"),
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
              ], success: String(localized: "Price alert created"))
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
    guard let held else { return String(localized: "New value") }
    return String(localized: "New value (\(held.currency))")
  }
  private var title: String {
    switch kind {
    case "FIXED": return String(localized: "Add a GIC or bond")
    case "MANUAL": return String(localized: "Add an asset you value yourself")
    default: return String(localized: "Record a valuation")
    }
  }
  private var subtitle: String {
    switch kind {
    case "FIXED":
      return String(
        localized:
          "It's valued by the interest it earns, up to maturity. The principal is recorded as a purchase on the start date."
      )
    case "MANUAL":
      return String(
        localized:
          "Property, private shares, a pension, collectibles: anything the market can't price. Update its value whenever you like."
      )
    default:
      return String(localized: "What \(symbol) is worth now. Its value in your portfolio uses the latest valuation.")
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
          TextField(
            "Symbol", text: $draft.symbol, prompt: kind == "FIXED" ? Text("GIC-2027") : Text("COTTAGE"))
          if taken && draft.request == nil {
            caution(String(localized: "\(entry.symbolCode) is already in your portfolio. Choose another symbol."))
          } else {
            caption(String(localized: "A short code of your own. It names the asset in Holdings and Activity."))
          }
          TextField(
            "Name (optional)", text: $draft.name,
            prompt: kind == "FIXED" ? Text("2-year GIC") : Text("Family cottage"))
          if kind == "FIXED" {
            NumberField(title: String(localized: "Principal"), text: $draft.value)
            NumberField(title: String(localized: "Annual rate (%)"), text: $draft.rate)
            DatePicker("Start date", selection: $draft.date, in: ...Date.now, displayedComponents: .date)
            DatePicker("Matures on", selection: $draft.maturity, displayedComponents: .date)
            if entry.maturity <= entry.date {
              caution(String(localized: "The maturity date must be after the start date."))
            }
            Picker("Compounding", selection: $draft.compounding) {
              ForEach(AssetEntry.compoundings, id: \.self) { Text(Self.compoundingLabel($0)).tag($0) }
            }
          } else {
            NumberField(title: String(localized: "Value"), text: $draft.value)
            Picker("Asset class", selection: $draft.assetClass) {
              ForEach(AssetClassOption.all) { Text($0.localizedLabel).tag($0.key) }
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
        Button(
          draft.request == nil
            ? (kind == "VALUE" ? String(localized: "Save valuation") : String(localized: "Add asset"))
            : String(localized: "Retry save")
        ) {
          let attempt =
            draft.request
            ?? TransactionSaveRequest(arguments: entry.arguments(), commandWords: AssetEntry.commandWords)
          draft.request = attempt
          let success =
            kind == "VALUE" ? String(localized: "Valuation recorded") : String(localized: "\(entry.symbolCode) added")
          Task {
            switch await model.recordTransaction(attempt, success: success) {
            case .recorded, .recovered: dismiss()
            case .notRecorded: draft.request = nil
            case .unknown: break
            }
          }
        }
        .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
        // An uncertain save always retries as it was, even once a refresh shows the asset it added.
        .disabled(!entry.isValid() || (taken && draft.request == nil) || !model.canEdit)
      }
    }.interactiveDismissDisabled(model.saving || draft.request != nil)
  }

  private func caption(_ text: String) -> some View {
    Text(text).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
  }

  private func caution(_ text: String) -> some View {
    Text(text).font(.caption).foregroundStyle(Studio.warn).fixedSize(horizontal: false, vertical: true)
  }

  /// The label for an `AssetEntry.compoundings` value (the value itself goes to the CLI).
  private static func compoundingLabel(_ value: String) -> String {
    switch value {
    case "annual": return String(localized: "Annual")
    case "semiannual": return String(localized: "Semiannual")
    case "quarterly": return String(localized: "Quarterly")
    case "monthly": return String(localized: "Monthly")
    case "simple": return String(localized: "Simple")
    default: return value.capitalized
    }
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
    // Holdings carries the engine's English label; the options' labels may be translated.
    guard let label = model.desktop?.positions.first(where: { $0.symbol == symbol })?.assetClass else { return nil }
    return AssetClassOption.all.first { $0.label == label }?.key
  }
  var body: some View {
    SheetLayout(
      title: String(localized: "Change asset class"),
      subtitle: String(localized: "Which class \(symbol) counts toward in Allocation and your targets, in every account."),
      model: model
    ) {
      Form {
        Picker("Asset class", selection: $draft.key) {
          ForEach(AssetClassOption.all) { Text($0.localizedLabel).tag($0.key) }
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
          let label = AssetClassOption.all.first(where: { $0.key == draft.key })?.localizedLabel ?? draft.key
          Task {
            let success = String(localized: "\(symbol) counts as \(label)")
            if await model.perform(["asset", "classify", "--", symbol, draft.key], success: success) {
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
    return String(localized: "Now \((weight / 100).formatted(.percent.precision(.fractionLength(1))))")
  }
  private func binding(_ key: String) -> Binding<String> {
    Binding(get: { draft.weights[key] ?? "" }, set: { draft.weights[key] = $0 })
  }
  var body: some View {
    SheetLayout(
      title: String(localized: "Allocation targets"),
      subtitle: String(localized: "The share of your portfolio you want in each asset class. Leave a class blank for none."),
      model: model
    ) {
      Form {
        ForEach(AssetClassOption.all) { option in
          LabeledContent {
            TextField("Target for \(option.localizedLabel) (%)", text: binding(option.key), prompt: Text("None"))
              .labelsHidden().multilineTextAlignment(.trailing).frame(width: 90)
          } label: {
            Text(option.localizedLabel)
            Text(model.status?.privacy == true ? "" : now(option.key))
          }
        }
        LabeledContent("Total", value: (entry.total() / 100).formatted(.percent.precision(.fractionLength(0...2))))
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
          let success = String(localized: "Allocation targets saved")
          Task { if await model.perform(entry.arguments(), success: success) { dismiss() } }
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
      title: String(localized: "A clearer way to import"),
      subtitle: model.importName.isEmpty ? String(localized: "CSV import") : model.importName, model: model
    ) {
      Picker("Broker format", selection: $model.importProfile) {
        ForEach(ImportProfile.all) { Text($0.label).tag($0.id) }
      }.onChange(of: model.importProfile) { _, _ in model.importPreview = nil }.disabled(model.saving)
      Picker("Default account for rows without one", selection: $model.importAccount) {
        Text("Use accounts named in the CSV").tag("")
        ForEach(model.desktop?.accounts ?? []) { Text($0.name).tag(String($0.id)) }
      }.onChange(of: model.importAccount) { _, _ in model.importPreview = nil }.disabled(model.saving)
      // Return previews first; once a preview has new entries, it imports them.
      Button("Preview import") { Task { await model.previewImport() } }.disabled(model.saving)
        .keyboardShortcut(model.importPreview == nil ? .defaultAction : nil)
      if let preview = model.importPreview {
        if let label = preview.localizedProfileLabel {
          (model.importProfile == "auto" ? Text("Detected format: \(label)") : Text("Read as: \(label)"))
            .font(.callout).foregroundStyle(.secondary)
        }
        HStack(spacing: 24) {
          previewCount(String(localized: "New entries"), preview.added)
          previewCount(String(localized: "Duplicates"), preview.duplicates)
          previewCount(String(localized: "Skipped"), preview.skipped.count)
        }.padding(.vertical, 8)
        if !preview.accountsCreated.isEmpty {
          Text("New accounts: \(preview.accountsCreated.formatted(.list(type: .and)))").font(.callout)
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
        .buttonStyle(.borderedProminent).keyboardShortcut(model.importPreview == nil ? nil : .defaultAction)
        .disabled(!model.canEdit || (model.importPreview?.added ?? 0) == 0)
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
              Text(issue.localizedReason).foregroundStyle(Studio.warn).fixedSize(horizontal: false, vertical: true)
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
          privacy ? Text("Line \(row.line)") : Text("Line \(row.line): \(row.summary)")
        }
        if duplicates.count > 20 {
          Text("…and \(duplicates.count - 20) more").foregroundStyle(.secondary)
        }
      }.font(.caption).frame(maxWidth: .infinity, alignment: .leading).padding(.top, 4)
    }.font(.callout)
  }

  private func previewCount(_ title: String, _ count: Int) -> some View {
    VStack(alignment: .leading, spacing: 6) {
      Text(count.formatted()).font(.title2).monospacedDigit()
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
      title: String(localized: "Welcome to MarketPulse"),
      subtitle: String(
        localized:
          "Track your TFSA, RRSP, FHSA, and non-registered accounts. MarketPulse works out your adjusted cost base as you go."
      ),
      model: model
    ) {
      VStack(spacing: 10) {
        choice(
          String(localized: "Create your first account"), icon: "building.columns",
          detail: String(localized: "Add an account, then record what you bought or deposited."), action: createAccount
        ).disabled(model.demoOnly)
        choice(
          String(localized: "Import a CSV"), icon: "square.and.arrow.down",
          detail: String(
            localized: "Bring in transactions exported from your broker. You'll see a preview before anything is saved."),
          action: importCSV
        ).disabled(model.demoOnly)
        if model.demo {
          choice(
            String(localized: "Leave the demo"), icon: "arrow.uturn.backward",
            detail: String(localized: "Go back to your own portfolio."), action: { model.leaveDemo(); dismiss() }
          ).disabled(model.demoOnly)
        } else {
          choice(
            String(localized: "Explore a demo portfolio"), icon: "sparkles",
            detail: String(
              localized:
                "Look around with fictional investments. Nothing is saved, and you can leave the demo at any time."),
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
    guard let path = model.dataDir else { return String(localized: "a MarketPulse folder in your home folder") }
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
        Image(systemName: icon).font(.title2).frame(width: 30).foregroundStyle(.tint).accessibilityHidden(true)
        VStack(alignment: .leading, spacing: 3) {
          Text(title).font(.headline)
          Text(detail).font(.callout).foregroundStyle(.secondary).fixedSize(
            horizontal: false, vertical: true)
        }
        Spacer(minLength: 0)
        Image(systemName: "chevron.right").foregroundStyle(.secondary).accessibilityHidden(true)
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
