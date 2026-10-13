import SwiftUI

struct TransactionSheet: View {
  @StateObject private var draft = TransactionSheetDraft()
  @ObservedObject var model: StatusModel
  @Environment(\.dismiss) private var dismiss
  private var trade: Bool { draft.type == "BUY" || draft.type == "SELL" }
  private var needsSymbol: Bool { trade || draft.type == "DIVIDEND" }
  private var valid: Bool {
    !draft.account.isEmpty
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
        .onChange(of: draft.account) { _, value in
          draft.currency =
            model.desktop?.accounts.first { String($0.id) == value }?.currency ?? "CAD"
        }
        DatePicker("Date", selection: $draft.date, in: ...Date.now, displayedComponents: .date)
        if needsSymbol { TextField("Symbol", text: $draft.symbol, prompt: Text("XEQT.TO")) }
        if trade {
          TextField("Quantity", text: $draft.quantity)
          TextField("Price per share", text: $draft.price)
          TextField("Fees", text: $draft.fees)
        } else {
          TextField("Amount", text: $draft.amount)
        }
        TextField("Transaction currency", text: $draft.currency)
        Text(
          "Use the currency of the transaction's price, which can differ from the account currency."
        ).font(.caption).foregroundStyle(.secondary)
        TextField("Note (optional)", text: $draft.note)
      }.formStyle(.grouped)
      HStack {
        Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction).disabled(model.saving)
        Spacer()
        if model.saving { ProgressView().controlSize(.small) }
        Button("Save transaction") {
          Task { if await model.perform(arguments, success: "Transaction recorded") { dismiss() } }
        }
        .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction).disabled(
          !valid || !model.canEdit)
      }
    }
  }
  private var arguments: [String] {
    let command = [
      "BUY": "buy", "SELL": "sell", "DEPOSIT": "deposit", "WITHDRAWAL": "withdraw",
      "DIVIDEND": "dividend", "INTEREST": "interest", "FEE": "fee",
    ][draft.type]!
    var args = [command]
    if needsSymbol { args += [draft.symbol.trimmingCharacters(in: .whitespaces).uppercased()] }
    args += trade ? [draft.quantity, draft.price, "--fees", draft.fees] : [draft.amount]
    let f = DateFormatter()
    f.dateFormat = "yyyy-MM-dd"
    f.locale = Locale(identifier: "en_US_POSIX")
    args += [
      "--account", draft.account, "--date", f.string(from: draft.date), "--currency",
      draft.currency.uppercased(), "--note", draft.note,
    ]
    return args
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
              "accounts", "add", draft.name.trimmingCharacters(in: .whitespaces), "--type",
              draft.type, "--currency", draft.currency.uppercased(), "--institution",
              draft.institution,
            ] + (draft.cash ? ["--track-cash"] : [])
          Task { if await model.perform(args, success: "Account created") { dismiss() } }
        }.buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
          .disabled(
            !model.canEdit || draft.name.trimmingCharacters(in: .whitespaces).isEmpty
              || draft.currency.count != 3)
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
        TextField(
          draft.condition.contains("pct") ? "Percentage" : "Price in listing currency",
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
                "alerts", "add", draft.symbol.uppercased(), draft.condition, draft.threshold,
                "--note", draft.note,
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
  @Environment(\.dismiss) private var dismiss
  var body: some View {
    SheetLayout(
      title: "A clearer way to import",
      subtitle: model.importURL?.lastPathComponent ?? "CSV import", model: model
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
        Button("Cancel") {
          model.importPreview = nil
          dismiss()
        }.keyboardShortcut(.cancelAction).disabled(model.saving)
        Spacer()
        if model.saving { ProgressView().controlSize(.small) }
        Button("Import \(model.importPreview?.added ?? 0) entries") {
          Task { await model.commitImport() }
        }
        .buttonStyle(.borderedProminent).disabled(
          model.saving || (model.importPreview?.added ?? 0) == 0)
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

private func positive(_ value: String) -> Bool {
  guard let n = Double(value) else { return false }
  return n.isFinite && n > 0
}
private func nonnegative(_ value: String) -> Bool {
  guard let n = Double(value) else { return false }
  return n.isFinite && n >= 0
}

private final class TransactionSheetDraft: ObservableObject {
  @Published var type = "BUY"
  @Published var account = ""
  @Published var symbol = ""
  @Published var quantity = ""
  @Published var price = ""
  @Published var amount = ""
  @Published var fees = "0"
  @Published var currency = "CAD"
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
