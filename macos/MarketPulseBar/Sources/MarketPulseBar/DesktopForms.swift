import SwiftUI

struct TransactionSheet: View {
  @StateObject private var draft = TransactionSheetDraft()
  @ObservedObject var model: StatusModel
  @Environment(\.dismiss) private var dismiss
  private var trade: Bool { draft.type == "BUY" || draft.type == "SELL" }
  private var needsSymbol: Bool { trade || draft.type == "DIVIDEND" }
  private var currency: String { CurrencyInput.normalize(draft.currency) }
  private var valid: Bool {
    !draft.account.isEmpty && (currency.isEmpty || CurrencyInput.isValid(currency))
      && (!needsSymbol || !draft.symbol.trimmingCharacters(in: .whitespaces).isEmpty)
      && (trade
        ? positive(draft.quantity) && nonnegative(draft.price) && nonnegative(draft.fees)
        : positive(draft.amount))
  }
  var body: some View {
    SheetLayout(
      title: "Record a transaction",
      subtitle: "Add an entry to your local ledger. This doesn't place a trade.", model: model
    ) {
      Form {
        Picker("Type", selection: $draft.type) {
          ForEach(
            ["BUY", "SELL", "DEPOSIT", "WITHDRAWAL", "DIVIDEND", "INTEREST", "FEE"], id: \.self
          ) { Text($0.capitalized).tag($0) }
        }
        Picker("Account", selection: $draft.account) {
          Text("Choose account").tag("")
          ForEach(model.desktop?.accounts ?? []) { Text($0.name).tag(String($0.id)) }
        }
        DatePicker("Date", selection: $draft.date, in: ...Date.now, displayedComponents: .date)
        if needsSymbol { TextField("Symbol", text: $draft.symbol, prompt: Text("XEQT.TO")) }
        if trade {
          NumberField(title: "Quantity", text: $draft.quantity)
          NumberField(title: "Price per share", text: $draft.price)
          NumberField(title: "Fees", text: $draft.fees)
        } else {
          NumberField(title: "Amount", text: $draft.amount)
        }
        TextField("Transaction currency", text: $draft.currency, prompt: Text("Automatic"))
        Text(
          "Leave blank to use the symbol's listing currency (or the account's for cash entries). Enter one if the price is in another currency."
        ).font(.caption).foregroundStyle(.secondary)
        TextField("Note (optional)", text: $draft.note)
      }.formStyle(.grouped).disabled(model.saving || draft.request != nil)
      if draft.request != nil && !model.saving {
        Text("The save outcome is unknown. Retry the same entry before changing or closing it.")
          .font(.caption).foregroundStyle(.secondary)
      }
      HStack {
        Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction).disabled(model.saving || draft.request != nil)
        Spacer()
        if model.saving { ProgressView().controlSize(.small) }
        Button(draft.request == nil ? "Save transaction" : "Retry save") {
          let attempt = draft.request ?? TransactionSaveRequest(arguments: arguments)
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
          !valid || !model.canEdit)
      }
    }.interactiveDismissDisabled(model.saving || draft.request != nil)
  }
  private var arguments: [String] {
    let command = [
      "BUY": "buy", "SELL": "sell", "DEPOSIT": "deposit", "WITHDRAWAL": "withdraw",
      "DIVIDEND": "dividend", "INTEREST": "interest", "FEE": "fee",
    ][draft.type]!
    let f = DateFormatter()
    f.dateFormat = "yyyy-MM-dd"
    f.locale = Locale(identifier: "en_US_POSIX")
    var options = ["--account", draft.account, "--date", f.string(from: draft.date), "--note", draft.note]
    if trade { options += ["--fees", NumberInput.cli(draft.fees)] }
    // Blank lets the CLI infer the listing currency, so a USD stock in a CAD account stays USD.
    if !currency.isEmpty { options += ["--currency", currency] }
    var values = needsSymbol ? [draft.symbol.trimmingCharacters(in: .whitespaces).uppercased()] : []
    values += (trade ? [draft.quantity, draft.price] : [draft.amount]).map { NumberInput.cli($0) }
    return [command] + options + ["--"] + values
  }
}

struct AccountSheet: View {
  @StateObject private var draft = AccountSheetDraft()
  @ObservedObject var model: StatusModel
  @Environment(\.dismiss) private var dismiss
  var body: some View {
    SheetLayout(
      title: "A home for your investments",
      subtitle: "Create an account in your existing portfolio.", model: model
    ) {
      Form {
        TextField("Account name", text: $draft.name, prompt: Text("My TFSA"))
        Picker("Type", selection: $draft.type) {
          ForEach(
            [
              "TFSA", "RRSP", "FHSA", "RESP", "LIRA", "RRIF", "NONREG", "MARGIN", "CRYPTO", "CASH",
              "OTHER",
            ], id: \.self
          ) { Text($0).tag($0) }
        }
        TextField("Currency", text: $draft.currency)
        TextField("Institution (optional)", text: $draft.institution)
        Toggle("Track cash balance", isOn: $draft.cash)
        Text(
          "When enabled, record deposits and withdrawals so purchases and sales are reflected in cash. Otherwise, only holdings are included."
        ).font(.caption).foregroundStyle(.secondary)
      }.formStyle(.grouped)
      HStack {
        Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction).disabled(model.saving)
        Spacer()
        Button("Create account") {
          let args =
            [
              "accounts", "add", "--type", draft.type, "--currency", CurrencyInput.normalize(draft.currency),
              "--institution", draft.institution,
            ] + (draft.cash ? ["--track-cash"] : [])
            + ["--", draft.name.trimmingCharacters(in: .whitespaces)]
          Task { if await model.perform(args, success: "Account created") { dismiss() } }
        }.buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
          .disabled(
            !model.canEdit || draft.name.trimmingCharacters(in: .whitespaces).isEmpty
              || !CurrencyInput.isValid(CurrencyInput.normalize(draft.currency)))
      }
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

struct ImportSheet: View {
  @ObservedObject var model: StatusModel
  var body: some View {
    SheetLayout(
      title: "A clearer way to import",
      subtitle: model.importName.isEmpty ? "CSV import" : model.importName, model: model
    ) {
      Picker("Default account for rows without one", selection: $model.importAccount) {
        Text("Use accounts named in the CSV").tag("")
        ForEach(model.desktop?.accounts ?? []) { Text($0.name).tag(String($0.id)) }
      }.onChange(of: model.importAccount) { _, _ in model.importPreview = nil }
      Button("Preview import") { Task { await model.previewImport() } }.disabled(model.saving)
      if let preview = model.importPreview {
        HStack(spacing: 24) {
          previewCount("New entries", preview.added)
          previewCount("Duplicates", preview.duplicates)
          previewCount("Skipped", preview.skipped.count)
        }.padding(.vertical, 14)
        if !preview.accountsCreated.isEmpty {
          Text("New accounts: \(preview.accountsCreated.joined(separator: ", "))").font(.callout)
        }
        if !preview.skipped.isEmpty {
          ScrollView {
            VStack(alignment: .leading, spacing: 8) {
              ForEach(preview.skipped) { issue in
                Text("Line \(issue.line): \(issue.reason)").font(.caption).foregroundStyle(.orange)
              }
            }
          }.frame(maxHeight: 160)
        }
        Text(
          "Only valid new rows will be imported. Skipped rows stay out of the ledger. A safety backup is taken before the import."
        ).font(.caption).foregroundStyle(.secondary)
      } else {
        Text("Preview maps your CSV columns and checks for duplicates without changing the ledger.")
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
        Text(error).font(.callout).foregroundStyle(.red).fixedSize(
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
        NumberInput.parse(text) == nil ? AnyShapeStyle(.orange) : AnyShapeStyle(.secondary))
    }
  }
}

private final class TransactionSheetDraft: ObservableObject {
  @Published var request: TransactionSaveRequest?
  @Published var type = "BUY"
  @Published var account = ""
  @Published var symbol = ""
  @Published var quantity = ""
  @Published var price = ""
  @Published var amount = ""
  @Published var fees = "0"
  @Published var currency = ""
  @Published var note = ""
  @Published var date = Date.now
}

private final class AccountSheetDraft: ObservableObject {
  @Published var name = ""
  @Published var type = "TFSA"
  @Published var currency = "CAD"
  @Published var institution = ""
  @Published var cash = false
}

private final class AlertSheetDraft: ObservableObject {
  @Published var symbol = ""
  @Published var condition = "above"
  @Published var threshold = ""
  @Published var note = ""
}
