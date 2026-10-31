import Foundation

// Compiled alongside the app's actual model files; works with Command Line Tools alone.
@main
struct NativeBridgeCheck {
  static func main() async throws {
    let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    let payload = try decoder.decode(DesktopPayload.self, from: data)
    precondition(payload.version == 1 && payload.demo)
    precondition(payload.accounts.count == 3 && payload.positions.count == 6)
    precondition(payload.status.history.count == 181 && payload.incomeMonths.count == 12)
    precondition(payload.warnings.isEmpty && payload.automation.backup == nil)
    precondition(payload.automation.errors.isEmpty && payload.automation.quoteErrors.isEmpty)
    precondition(payload.status.netWorth! > 0)
    precondition(payload.positions.allSatisfy { $0.value != nil })
    precondition(payload.backend?.version.isEmpty == false && payload.backend?.python.isEmpty == false)
    precondition(payload.ledgerRevision?.count == 16)  // the Tax workspace reloads when it changes
    // The demo's folder is temporary and never shown; a populated ledger never offers the welcome.
    precondition(payload.storage?.dataDir == nil && payload.storage?.empty == false && !payload.ledgerEmpty)
    let storage = try decoder.decode(
      StorageInfo.self, from: Data(#"{"data_dir":"/tmp/marketpulse","empty":true}"#.utf8))
    precondition(storage.dataDir == "/tmp/marketpulse" && storage.empty)
    precondition(storage.backupDir == nil && storage.backups == nil)  // an older engine
    precondition(payload.storage?.backupDir == nil && payload.storage?.backups?.isEmpty == true)
    // The demo's settings are its own: no config file to reveal.
    precondition(payload.settings?.baseCurrency == "CAD" && payload.settings?.configPath == nil)
    precondition(payload.settings?.defaultAccountId == nil && payload.settings?.menubarDisplay == "day_pct")
    let settings = try decoder.decode(
      SettingsInfo.self,
      from: Data(
        #"{"base_currency":"USD","privacy":true,"default_account":"tfsa","default_account_id":3,"menubar_display":"symbol","menubar_symbol":"XEQT.TO","config_path":"/tmp/config.toml"}"#
          .utf8))
    precondition(settings.defaultAccount == "tfsa" && settings.defaultAccountId == 3 && settings.privacy)
    precondition(settings.menubarSymbol == "XEQT.TO" && settings.configPath == "/tmp/config.toml")
    let ledger = try decoder.decode(
      StorageInfo.self, from: try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[4])))
    let backups = ledger.backups ?? []
    precondition(ledger.backupDir?.hasSuffix("/backups") == true && backups.count >= 2)
    precondition(Set(backups.map(\.reasonLabel)) == ["Daily backup", "Before a restore"])
    precondition(backups.allSatisfy { $0.date != nil && $0.size > 0 && $0.when != $0.name })
    // Archived accounts: none in the demo; listed with just enough to unarchive them.
    precondition(payload.archivedAccounts?.isEmpty == true)
    let archived = try decoder.decode(
      [ArchivedAccount].self, from: try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[5])))
    precondition(archived.count == 1 && archived[0].name == "Old RRSP" && archived[0].type == "RRSP")
    // Edits, archive and unarchive send the account's revision, so a changed or restored one is refused.
    precondition(archived[0].revisionArguments.count == 2 && archived[0].revision?.count == 16)
    precondition(payload.accounts.allSatisfy { $0.revisionArguments.count == 2 && $0.revision?.count == 16 })
    precondition(payload.accounts.allSatisfy { DesktopAccount.types.contains($0.type) })
    // The transfer form asks for a market price between registered and non-registered accounts.
    precondition(payload.accounts.allSatisfy { $0.registered == ["TFSA", "RRSP", "FHSA"].contains($0.type) })
    precondition(Set(payload.accounts.compactMap(\.registered)) == [true, false])
    // The demo's TFSA room, as entered: the room sheet edits it from these fields.
    let year = Calendar.current.component(.year, from: .now)
    precondition(payload.room.count == 1 && payload.room[0].accountType == "TFSA")
    precondition(payload.room[0].asOfYear == year && payload.room[0].startingRoom == 18000)
    precondition(ContributionRoom.firstYear("FHSA") == 2023 && ContributionRoom.firstYear("TFSA") == 2009)
    precondition(payload.room[0].newLimits != nil && payload.room[0].contributions == 0)

    // The Tax workspace (`desktop tax`): the demo's superficial loss, then a gain on the rebought shares.
    let demoTax = try decoder.decode(
      TaxPayload.self, from: try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[6])))
    precondition(demoTax.version == 1 && demoTax.demo && demoTax.baseCurrency == "CAD" && demoTax.inclusionRate == 0.5)
    let demoSales = demoTax.years.reversed().flatMap(\.rows)
    precondition(demoSales.map(\.superficial) == [true, false] && demoSales.allSatisfy(\.complete))
    precondition(demoSales.allSatisfy { $0.allowedGain != nil && $0.fx != nil && $0.accountLabel == "Personal investing" })
    precondition(demoSales[0].allowedGain == 0 && demoSales[0].denied! > 0 && demoSales[0].note == "superficial")
    precondition(demoTax.years.allSatisfy { $0.securities.map(\.symbol) == ["NVDA"] && $0.missingFx == 0 })
    precondition(demoTax.room.count == 1 && demoTax.issues.isEmpty)
    precondition(demoTax.notes.contains { $0.contains("not tax advice") })
    let ledgerTax = try decoder.decode(
      TaxPayload.self, from: try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[7])))
    precondition(!ledgerTax.demo && ledgerTax.years.map(\.year) == [2025] && ledgerTax.years[0].missingFx == 1)
    let unpriced = ledgerTax.years[0].rows.first { $0.symbol == "SAP.DE" }!
    precondition(!unpriced.complete && unpriced.proceeds == nil && unpriced.allowedGain == nil && unpriced.fx == nil)
    precondition(unpriced.note == "FX missing" && unpriced.accountLabel == "Fictional Taxable")
    let archivedSale = ledgerTax.years[0].rows.first { $0.symbol == "ZAG.TO" }!
    precondition(archivedSale.archived && archivedSale.account == nil && archivedSale.accountLabel == "Archived account")
    precondition(archivedSale.allowedGain == 100 && ledgerTax.years[0].netGain == 100)
    // Export CSV reports what the export itself found.
    let export = try decoder.decode(
      TaxExportResult.self, from: try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[8])))
    precondition(export.exported == 2 && export.issues == ledgerTax.issues)  // the shown report is current
    precondition(export.message(year: 2025, file: "gains.csv") == "Saved 2 sales from 2025 to gains.csv")
    let withIssue = try decoder.decode(
      TaxExportResult.self,
      from: Data(#"{"exported":1,"issues":[{"date":"2024-07-02","message":"No price"}]}"#.utf8))
    precondition(
      withIssue.message(year: 2024, file: "g.csv")
        == "Saved 1 sale from 2024 to g.csv. 1 issue may leave sales out of it: 2024-07-02 No price")

    let transactions = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[2]))
    for row in try decoder.decode([ValuedTransaction].self, from: transactions) {
      precondition(
        row.transaction.revisionArguments.count == 2 && row.transaction.revision?.count == 16,
        "Missing revision for \(row.transaction.type)")
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
      #"{"added":2,"duplicates":1,"skipped":[[4,"Invalid date"]],"accounts_created":["TFSA"],"backup":null,"fingerprint":"abc"}"#
        .utf8)
    let result = try decoder.decode(ImportPreview.self, from: preview)
    precondition(result.added == 2 && result.duplicates == 1)
    precondition(result.skipped.first?.line == 4 && result.skipped.first?.reason == "Invalid date")
    precondition(result.accountsCreated == ["TFSA"] && result.backup == nil && result.fingerprint == "abc")
    precondition(result.profile == nil && result.issues == nil && result.duplicateRows == nil)  // an older engine
    // A real Questrade preview from the CLI, after the same file was imported once.
    let broker = try decoder.decode(
      ImportPreview.self, from: try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[10])))
    precondition(broker.profile == "questrade" && broker.profileLabel == "Questrade")
    precondition(broker.added == 0 && broker.duplicates == 8 && broker.duplicateRows?.count == 8)
    let firstDuplicate = broker.duplicateRows?.first
    precondition(firstDuplicate?.line == 2 && firstDuplicate?.summary.contains("DEPOSIT") == true)
    let issues = broker.issues ?? []
    precondition(issues.map(\.line) == broker.skipped.map(\.line))
    precondition(issues.map(\.reason) == broker.skipped.map(\.reason))
    precondition(issues.first?.field == "amount" && issues.first?.value == "-22.00")
    let profileIds = try JSONDecoder().decode(
      [String].self, from: try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[11])))
    precondition(ImportProfile.all.map(\.id) == profileIds, "Import profiles differ from the engine's")
    precondition(CurrencyInput.normalize(" usd\n") == "USD" && CurrencyInput.isValid("USD"))
    precondition(!CurrencyInput.isValid("12$") && !CurrencyInput.isValid("CA") && !CurrencyInput.isValid("ÉUR"))
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
    // The edit form prefills stored numbers; they must read back unchanged, with no hint.
    for locale in [french, german, english] {
      for value in [0, 1234.5, 0.000125, 10, 33.333333, 0.123456789012, 1.0 / 3, 0.1 + 0.2, 1e-12, 0.000012345678901234568, 1e-21, 123456789.123456789] {
        let text = NumberInput.editable(value, locale: locale)
        precondition(NumberInput.parse(text, locale: locale) == value, "\(text) in \(locale.identifier)")
      }
    }
    precondition(NumberInput.editable(1234.5, locale: french) == "1234,5")
    precondition(NumberInput.editable(10, locale: english) == "10")
    // Tax sale details and superficial-loss explanations must not turn fractional units into zero.
    precondition(NumberInput.editable(0.000125, locale: english) == "0.000125")
    precondition(NumberInput.editable(1.25e-9, locale: english) == "0.00000000125")
    precondition(NumberInput.editable(0.000125, locale: french) == "0,000125")
    for day in ["2024-01-02", "2024-03-10", "2024-11-03", "2025-12-31"] {
      precondition(LedgerDate.date(day).map(LedgerDate.string) == day, day)
    }
    let receipt = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[3]))
    let request = TransactionSaveRequest(
      arguments: ["deposit", "--note", "--a literal note", "--", "12.5"],
      id: "00000000-0000-0000-0000-000000000055")
    precondition(request.arguments == [
      "deposit", "--request-id", request.id, "--note", "--a literal note", "--", "12.5",
    ])
    let failed = NSError(domain: "Save confirmation failed", code: 1)
    var calls: [[String]] = []
    let recovered = await request.submit { args in
      calls.append(args)
      if args == request.statusArguments { return receipt }
      throw failed
    }
    precondition(recovered == .recovered)
    precondition(calls == [request.arguments, request.statusArguments])
    let notRecorded = await request.submit { args in
      if args == request.statusArguments { return Data(#"{"recorded":false,"transaction_id":null}"#.utf8) }
      throw failed
    }
    precondition(notRecorded == .notRecorded(failed.localizedDescription))
    let unknown = await request.submit { _ in throw failed }
    guard case .unknown(let warning) = unknown else { preconditionFailure("Unknown save unlocked the form") }
    precondition(warning.contains("Retry save"))
    let malformed = await request.submit { args in
      if args == request.statusArguments { return Data(#"{"recorded":true,"transaction_id":null}"#.utf8) }
      throw failed
    }
    guard case .unknown = malformed else { preconditionFailure("Invalid receipt unlocked the form") }
    // Retrying an unknown outcome uses the original immutable ID and arguments.
    let retry = await request.submit { args in
      precondition(args == request.arguments)
      return Data()
    }
    precondition(retry == .recorded)

    // The transaction form: the commands tests/test_cli.py runs on a fictional ledger.
    let forms = try JSONDecoder().decode(
      FormCases.self, from: try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[9])))
    let us = Locale(identifier: "en_US")
    precondition(forms.cases.count > 10)
    for form in forms.cases {
      let f = form.entry
      let entry = TransactionEntry(
        type: f["type"]!, account: f["account"] ?? "", target: f["target"] ?? "", date: f["date"] ?? "",
        symbol: f["symbol"] ?? "", quantity: f["quantity"] ?? "", price: f["price"] ?? "", amount: f["amount"] ?? "",
        fees: f["fees"] ?? "0", currency: f["currency"] ?? "", note: f["note"] ?? "", splitNew: f["splitNew"] ?? "2",
        splitOld: f["splitOld"] ?? "1", priceRequired: f["priceRequired"] == "true")
      precondition(entry.isValid(locale: us) == form.valid, "Form validity differs for \(f)")
      if let expected = form.arguments {
        let sent = entry.arguments(locale: us)
        precondition(sent == expected, "Form arguments differ: \(sent)")
      }
    }
    precondition(Set(forms.cases.map { $0.entry["type"]! }).isSuperset(of: ["DRIP", "TRANSFER", "SPLIT", "ROC"]))
    precondition(TransactionEntry.types.count == 11 && TransactionEntry.editableTypes.count == 7)
    precondition(TransactionEntry.label("ROC") == "ROC" && TransactionEntry.label("TRANSFER") == "Transfer")

    // Assets and allocation: the demo's GIC and targets, and the forms' commands.
    let gic = payload.assets?.first { $0.symbol == "GIC-DEMO" }
    precondition(payload.assets?.count == 1 && gic?.fixedIncome == true && gic?.assetClass == "fixed_income")
    precondition(gic?.valuedOn == nil && gic?.summary?.hasPrefix("4.1% annual · matures ") == true)
    precondition(payload.positions.contains { $0.symbol == "GIC-DEMO" && ($0.value ?? 0) > 8000 })
    precondition(payload.targets?.map(\.bucket) == ["equity", "etf", "fixed_income"])
    let rebalance = payload.rebalance ?? []
    precondition(Set(rebalance.map(\.bucket)) == ["equity", "etf", "fixed_income", "cash"])
    precondition(rebalance.allSatisfy { abs($0.drift - ($0.weight - $0.target)) < 1e-9 })
    let manual = try decoder.decode(
      DesktopAsset.self,
      from: Data(
        #"{"symbol":"COTTAGE","kind":"manual","name":"Cottage","asset_class":"real_estate","asset_class_label":"Real Estate","currency":"CAD","rate":0,"compounding":"annual","start_date":"","maturity_date":"","valued_on":"2024-06-01"}"#
          .utf8))
    precondition(manual.manual && manual.summary == "Valued by you · 2024-06-01")
    let classes = try JSONDecoder().decode(
      [[String]].self, from: try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[13])))
    precondition(AssetClassOption.all.map { [$0.key, $0.label] } == classes, "Asset classes differ from Python's")
    let assetForms = try JSONDecoder().decode(
      AssetFormCases.self, from: try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[12])))
    precondition(assetForms.assets.count >= 9 && assetForms.targets.count >= 4)
    for form in assetForms.assets {
      let f = form.entry
      let entry = AssetEntry(
        kind: f["kind"]!, account: f["account"] ?? "", symbol: f["symbol"] ?? "", name: f["name"] ?? "",
        value: f["value"] ?? "", rate: f["rate"] ?? "", date: f["date"] ?? "", maturity: f["maturity"] ?? "",
        compounding: f["compounding"] ?? "annual", assetClass: f["assetClass"] ?? "real_estate",
        currency: f["currency"] ?? "")
      precondition(entry.isValid(locale: us) == form.valid, "Asset form validity differs for \(f)")
      if let expected = form.arguments {
        let sent = entry.arguments(locale: us)
        precondition(sent == expected, "Asset form arguments differ: \(sent)")
        let save = TransactionSaveRequest(arguments: sent, id: "R", commandWords: AssetEntry.commandWords)
        precondition(Array(save.arguments.prefix(4)) == [sent[0], sent[1], "--request-id", "R"])
      }
    }
    precondition(Set(assetForms.assets.map { $0.entry["kind"]! }) == Set(AssetEntry.kinds))
    for form in assetForms.targets {
      let entry = TargetsEntry(weights: form.weights)
      precondition(entry.isValid(locale: us) == form.valid, "Targets validity differs for \(form.weights)")
      if let expected = form.arguments {
        precondition(entry.arguments(locale: us) == expected, "Targets arguments differ: \(entry.arguments(locale: us))")
      }
    }
    // Other commands keep the request ID right after the command, as before.
    precondition(TransactionSaveRequest(arguments: ["deposit", "--", "1"], id: "R").arguments == ["deposit", "--request-id", "R", "--", "1"])
    print(
      "Native bridge checks passed: real Python demo, storage and backups, archived accounts, room, tax report, settings, activity values, import result, broker import preview and profiles, privacy formatting, number entry, editable numbers and dates, transaction save recovery, transaction form commands, assets, allocation targets and rebalancing, asset and targets form commands"
    )
  }
}

private struct ValuedTransaction: Decodable {
  let transaction: DesktopTransaction
  let expectedSignedValue: Double
}

private struct AssetFormCases: Decodable {
  struct Asset: Decodable {
    let entry: [String: String]
    let valid: Bool
    let arguments: [String]?
  }
  struct Targets: Decodable {
    let weights: [String: String]
    let valid: Bool
    let arguments: [String]?
  }
  let assets: [Asset]
  let targets: [Targets]
}

private struct FormCases: Decodable {
  struct Case: Decodable {
    let entry: [String: String]
    let valid: Bool
    let arguments: [String]?
  }
  let cases: [Case]
}
