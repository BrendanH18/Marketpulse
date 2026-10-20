import Foundation

// Compiled alongside the app's UpdateCheck.swift; works with Command Line Tools alone (no XCTest).
// Run by tests/test_update_check.py. The fetch is checked against a stub URLProtocol, so nothing
// touches the network.

nonisolated(unsafe) var failures = 0

func check(_ condition: Bool, _ message: String, line: Int = #line) {
  if !condition {
    failures += 1
    print("FAIL (line \(line)): \(message)")
  }
}

func v(_ text: String) -> AppVersion {
  guard let version = AppVersion(text) else {
    failures += 1
    print("FAIL: \(text) didn't parse")
    return AppVersion("0.0.0")!
  }
  return version
}

/// Serves one canned response and records the request it saw.
final class StubProtocol: URLProtocol {
  nonisolated(unsafe) static var status = 200
  nonisolated(unsafe) static var body = Data()
  nonisolated(unsafe) static var offline = false
  nonisolated(unsafe) static var seen: URLRequest?

  override class func canInit(with request: URLRequest) -> Bool { true }
  override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
  override func startLoading() {
    Self.seen = request
    if Self.offline {
      client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet))
      return
    }
    let response = HTTPURLResponse(url: request.url!, statusCode: Self.status, httpVersion: nil, headerFields: nil)!
    client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
    client?.urlProtocol(self, didLoad: Self.body)
    client?.urlProtocolDidFinishLoading(self)
  }
  override func stopLoading() {}
}

@main
struct UpdateCheckTests {
  static func main() async {
    versions()
    decisions()
    throttle()
    await fetching()
    if failures > 0 {
      print("\(failures) update check failure(s)")
      exit(1)
    }
    print("update check: all checks passed")
  }

  static func versions() {
    // Parsing and display.
    check(v("v1.2.3").description == "1.2.3", "v prefix dropped")
    check(v("V1.2.3").description == "1.2.3", "V prefix dropped")
    check(v("1.2").description == "1.2.0", "missing patch is 0")
    check(v("1.2.3-beta.1").prerelease == ["beta", "1"], "pre-release identifiers")
    check(v("v1.2.3-rc.2").description == "1.2.3-rc.2", "pre-release description")
    check(v("1.2.3+abc").description == "1.2.3", "build metadata dropped")
    check(v("1.2.3-rc.1+build.5").prerelease == ["rc", "1"], "pre-release before build metadata")
    check(v("1.2.3-x-y.7").prerelease == ["x-y", "7"], "hyphens inside identifiers")
    check(v("10.20.30").major == 10 && v("10.20.30").minor == 20 && v("10.20.30").patch == 30, "multi-digit parts")

    // Malformed input is nil, never a crash.
    let malformed = [
      "", "v", "latest", "v1.x", "1..2", "nightly-2026", "1", "2026", "1.2.3.4", ".1.2", "1.2.", "1.2.3-",
      "1.2.3+", "1.2.3-rc..1", "1.2.3-rc.01", "1.2.3-ünï", "1.2.3 ", " 1.2.3", "1.2.3\n", "-1.2.3", "1.-2.3",
      "+1.2.3", "1.2.3_4", "vv1.2.3", "v 1.2.3", "99999999999999999999.0.0", "1.2.3; rm -rf ~", "１.２.３",
    ]
    for text in malformed { check(AppVersion(text) == nil, "\(text.debugDescription) should be malformed") }

    // Equal versions.
    check(v("v1.2.0") == v("1.2"), "v1.2.0 == 1.2")
    check(v("1.2.3") == v("v1.2.3"), "prefix doesn't matter")
    check(v("1.2.3+abc") == v("1.2.3+def"), "build metadata ignored")
    check(v("1.2.3-rc.1") == v("v1.2.3-rc.1+x"), "equal pre-releases")
    check(!(v("1.2.3") < v("1.2.3")) && !(v("1.2.3") > v("1.2.3")), "equal isn't ordered")
    check(v("1.2.3") != v("1.2.3-rc.1"), "a pre-release isn't its release")

    // Core ordering, numeric rather than lexical.
    check(v("1.2.3") < v("1.2.4"), "patch")
    check(v("1.2.9") < v("1.10.0"), "minor compares numerically")
    check(v("1.99.99") < v("2.0.0"), "major")
    check(v("2.10.0") > v("2.9.1"), "2.10 > 2.9")

    // SemVer 2.0.0 section 11 example, strictly increasing.
    let chain = [
      "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11",
      "1.0.0-rc.1", "1.0.0",
    ].map(v)
    for (lower, higher) in zip(chain, chain.dropFirst()) {
      check(lower < higher && !(higher < lower) && lower != higher, "\(lower) < \(higher)")
    }
    check(v("1.2.3-beta.1") < v("1.2.3"), "pre-release below its release")
    check(v("1.2.3-rc.2") > v("1.2.2"), "pre-release above the previous release")
    check(v("1.2.3-rc.2") < v("1.2.3-rc.10"), "numeric identifiers compare numerically")
    check(v("1.2.3-rc.9") < v("1.2.3-rc.10"), "9 < 10, not lexically")
    check(v("1.0.0-1") < v("1.0.0-a"), "numeric below alphanumeric")
    check(v("1.0.0-rc.99999999999999999999") > v("1.0.0-rc.9"), "long numeric identifiers don't overflow")
    check(v("1.0.0-Beta") < v("1.0.0-beta"), "alphanumeric identifiers compare in ASCII order")
    check([v("1.10.0"), v("1.2.0-rc.1"), v("1.2.0"), v("1.9")].sorted().map(\.description)
      == ["1.2.0-rc.1", "1.2.0", "1.9.0", "1.10.0"], "sorting")
  }

  static func decisions() {
    let repo = "https://github.com/BrendanH18/Marketpulse"
    let notes = "\(repo)/releases/tag/v2.3.0"
    let update = UpdateCheck.decide(
      current: "2.2.0", latestTag: "v2.3.0", notesURL: notes, prerelease: false, draft: false)
    check(
      update
        == UpdateAvailable(
          version: "2.3.0", tag: "v2.3.0", notesURL: notes,
          installCommand: "curl -fsSL \(repo)/releases/download/v2.3.0/install.sh | bash -s -- --version v2.3.0"),
      "newer release offered: \(String(describing: update))")
    let release = LatestRelease(tagName: "v2.3.0", htmlURL: notes, prerelease: false, draft: false)
    check(UpdateCheck.decide(current: "2.2.0", latest: release) == update, "LatestRelease overload")
    check(UpdateCheck.decide(current: "2.2.0", latest: nil) == nil, "no release fetched")
    check(UpdateCheck.decide(current: "2.3.0-rc.1", latest: release) != nil, "release offered over its pre-release")

    func offered(_ current: String?, _ tag: String?, prerelease: Bool = false, draft: Bool = false) -> Bool {
      UpdateCheck.decide(current: current, latestTag: tag, notesURL: notes, prerelease: prerelease, draft: draft)
        != nil
    }
    check(!offered(nil, "v2.3.0"), "development build (no version) never offered")
    check(!offered("", "v2.3.0"), "empty current version")
    check(!offered("dev", "v2.3.0"), "unparseable current version")
    check(!offered("2.3.0", "v2.3.0"), "same version")
    check(!offered("2.3", "v2.3.0"), "equal versions written differently")
    check(!offered("2.4.0", "v2.3.0"), "older release")
    check(!offered("2.2.0", nil), "no tag")
    check(!offered("2.2.0", "latest"), "malformed tag")
    check(!offered("2.2.0", "v2.x"), "malformed tag")
    check(!offered("2.2.0", "v2.3.0", draft: true), "draft")
    check(!offered("2.2.0", "v2.3.0", prerelease: true), "flagged pre-release")
    check(!offered("2.2.0", "v2.3.0-rc.1"), "pre-release tag without the flag")
    check(offered("2.2.0", "v2.2.1"), "patch release")
    check(offered("2.2.0", "v10.0.0"), "numeric major")

    // Notes only ever link to this repository's releases.
    let elsewhere = UpdateCheck.decide(
      current: "2.2.0", latestTag: "v2.3.0", notesURL: "https://example.com/x", prerelease: false, draft: false)
    check(elsewhere?.notesURL == "\(repo)/releases/latest", "foreign notes URL replaced")
    let missing = UpdateCheck.decide(current: "2.2.0", latestTag: "v2.3.0", prerelease: false, draft: false)
    check(missing?.notesURL == "\(repo)/releases/latest", "missing notes URL replaced")
    check(
      UpdateCheck.decide(
        current: "2.2.0", latestTag: "v2.3.0", notesURL: "\(repo)-evil/releases/x", prerelease: false, draft: false)?
        .notesURL == "\(repo)/releases/latest", "lookalike repository rejected")

    // install.sh only downloads plain vX.Y.Z tags; anything else gets the latest-release command.
    let latest = "curl -fsSL \(repo)/releases/latest/download/install.sh | bash"
    check(UpdateCheck.latestInstallCommand == latest, "latest command matches docs/install.md")
    let short = UpdateCheck.decide(current: "2.2.0", latestTag: "v2.3", prerelease: false, draft: false)
    check(short?.version == "2.3" && short?.installCommand == latest, "two-part tag: \(String(describing: short))")
    let bare = UpdateCheck.decide(current: "2.2.0", latestTag: "2.3.0", prerelease: false, draft: false)
    check(bare?.version == "2.3.0" && bare?.installCommand == latest, "tag without v")
    let built = UpdateCheck.decide(current: "2.2.0", latestTag: "v2.3.0+build.1", prerelease: false, draft: false)
    check(built?.installCommand == latest, "build metadata never reaches the command")
    check(UpdateCheck.installCommand(tag: "v2.3.0; rm -rf ~") == latest, "shell text never reaches the command")
  }

  static func throttle() {
    let now = Date(timeIntervalSince1970: 1_800_000_000)
    let day: TimeInterval = 24 * 60 * 60
    check(UpdateCheck.isDue(lastCheck: nil, now: now), "never checked")
    check(!UpdateCheck.isDue(lastCheck: now, now: now), "just checked")
    check(!UpdateCheck.isDue(lastCheck: now - 60, now: now), "a minute ago")
    check(!UpdateCheck.isDue(lastCheck: now - day + 1, now: now), "just under a day")
    check(UpdateCheck.isDue(lastCheck: now - day, now: now), "exactly a day")
    check(UpdateCheck.isDue(lastCheck: now - 3 * day, now: now), "days ago")
    check(UpdateCheck.isDue(lastCheck: now + 60, now: now), "last check in the future (clock moved back)")
  }

  static func fetching() async {
    let config = URLSessionConfiguration.ephemeral
    config.protocolClasses = [StubProtocol.self]
    let session = URLSession(configuration: config)
    let body = #"""
      {"tag_name":"v2.3.0","html_url":"https://github.com/BrendanH18/Marketpulse/releases/tag/v2.3.0",
       "prerelease":false,"draft":false,"name":"MarketPulse 2.3.0","assets":[],"body":"Notes"}
      """#

    StubProtocol.body = Data(body.utf8)
    let release = await UpdateCheck.fetchLatest(session: session, appVersion: "2.2.0")
    check(
      release
        == LatestRelease(
          tagName: "v2.3.0", htmlURL: "https://github.com/BrendanH18/Marketpulse/releases/tag/v2.3.0",
          prerelease: false, draft: false), "decodes the release: \(String(describing: release))")
    let seen = StubProtocol.seen
    check(seen?.url?.absoluteString == "https://api.github.com/repos/BrendanH18/Marketpulse/releases/latest", "URL")
    check(seen?.httpMethod == "GET" && seen?.httpBody == nil, "a bodiless GET")
    check(seen?.value(forHTTPHeaderField: "Accept") == "application/vnd.github+json", "Accept header")
    check(seen?.value(forHTTPHeaderField: "User-Agent") == "MarketPulse/2.2.0", "User-Agent header")
    check(seen?.value(forHTTPHeaderField: "Cookie") == nil, "no cookies")
    check(seen?.value(forHTTPHeaderField: "Authorization") == nil, "no credentials")

    let request = UpdateCheck.request(appVersion: nil)
    check(request.value(forHTTPHeaderField: "User-Agent") == "MarketPulse/dev", "development User-Agent")
    check(request.timeoutInterval == 10 && !request.httpShouldHandleCookies, "timeout and cookies")
    check(Set((request.allHTTPHeaderFields ?? [:]).keys) == ["Accept", "User-Agent"], "only two headers set")
    let defaults = UpdateCheck.ephemeralSession.configuration
    check(
      !defaults.httpShouldSetCookies && defaults.httpCookieAcceptPolicy == .never && defaults.urlCache == nil
        && defaults.urlCredentialStorage == nil && defaults.timeoutIntervalForRequest == 10,
      "default session keeps no cookies, cache or credentials")

    // Every failure is nil, never a throw or a crash.
    for (status, text) in [
      (403, #"{"message":"API rate limit exceeded"}"#), (429, "{}"), (404, #"{"message":"Not Found"}"#),
      (500, ""), (200, "not json"), (200, "{}"), (200, #"{"tag_name":1}"#), (200, ""),
      (200, #"{"tag_name":"v2.3.0","html_url":"x","prerelease":"no","draft":false}"#),
    ] {
      StubProtocol.status = status
      StubProtocol.body = Data(text.utf8)
      let result = await UpdateCheck.fetchLatest(session: session, appVersion: "2.2.0")
      check(result == nil, "HTTP \(status) \(text.debugDescription) should be nil")
    }
    StubProtocol.offline = true
    check(await UpdateCheck.fetchLatest(session: session, appVersion: "2.2.0") == nil, "offline")
  }
}
