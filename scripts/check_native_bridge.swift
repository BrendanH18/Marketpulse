import Foundation

// Compiled alongside the app's actual model files; works with Command Line Tools alone.
@main
struct NativeBridgeCheck {
  static func main() throws {
    let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    let payload = try decoder.decode(DesktopPayload.self, from: data)
    precondition(payload.version == 1 && payload.demo)
    precondition(payload.accounts.count == 3 && payload.positions.count == 5)
    precondition(payload.status.history.count == 181 && payload.incomeMonths.count == 12)
    precondition(payload.warnings.isEmpty && payload.automation.backup == nil)
    precondition(payload.automation.errors.isEmpty && payload.automation.quoteErrors.isEmpty)
    precondition(payload.status.netWorth! > 0)
    precondition(payload.positions.allSatisfy { $0.value != nil })

    let transactions = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[2]))
    for row in try decoder.decode([ValuedTransaction].self, from: transactions) {
      precondition(
        row.transaction.signedValue == row.expectedSignedValue,
        "Activity value differs for \(row.transaction.type)")
      precondition(
        (row.transaction.type == "TRANSFER") == (row.transaction.targetAccount == "RRSP"),
        "Transfer target differs for \(row.transaction.type)")
    }
    precondition(payload.activity.contains { $0.type == "BUY" && $0.signedValue < 0 })
    precondition(payload.activity.contains { $0.type == "DIVIDEND" && $0.signedValue > 0 })

    let preview = Data(
      #"{"added":2,"duplicates":1,"skipped":[[4,"Invalid date"]],"accounts_created":["TFSA"],"backup":null}"#
        .utf8)
    let result = try decoder.decode(ImportPreview.self, from: preview)
    precondition(result.added == 2 && result.duplicates == 1)
    precondition(result.skipped.first?.line == 4 && result.skipped.first?.reason == "Invalid date")
    precondition(result.accountsCreated == ["TFSA"] && result.backup == nil)
    precondition(Format.money(12345, "CAD", privacy: true) == Format.mask)
    precondition(Format.money(nil, "CAD", privacy: true) == "—")
    precondition(Format.pct(-1.25) == "-1.25%")
    let french = Locale(identifier: "fr_CA")
    let german = Locale(identifier: "de_DE")
    let english = Locale(identifier: "en_CA")
    precondition(NumberInput.parse("12,5", locale: french) == 12.5)
    precondition(NumberInput.parse("1.000", locale: german) == 1000)
    precondition(NumberInput.parse("12.5", locale: german) == 12.5)
    precondition(NumberInput.parse("1,000", locale: english) == 1000)
    precondition(NumberInput.parse("12,5", locale: english) == nil)
    precondition(NumberInput.parse("inf", locale: english) == nil)
    precondition(NumberInput.cli("12,5", locale: french) == "12.5")
    precondition(NumberInput.hint("12.50", locale: english) == nil)
    precondition(NumberInput.hint("1.000", locale: german)?.hasPrefix("Reads as") == true)
    precondition(NumberInput.hint("12,5", locale: english)?.hasPrefix("Enter a number") == true)
    print(
      "Native bridge checks passed: real Python demo, activity values, import result, privacy formatting, number entry"
    )
  }
}

private struct ValuedTransaction: Decodable {
  let transaction: DesktopTransaction
  let expectedSignedValue: Double
}
