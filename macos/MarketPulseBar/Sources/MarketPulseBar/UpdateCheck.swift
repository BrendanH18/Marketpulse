import Foundation

/// A release version such as `v1.2.3`, `1.2` or `1.2.3-rc.2`, ordered by SemVer precedence:
/// missing minor/patch numbers count as 0 (`v1.2.0` == `1.2`), a pre-release sorts below its
/// release, pre-release identifiers compare numerically when both are digits, and build
/// metadata (`+abc`) is ignored. Parsing never traps; anything else yields nil.
struct AppVersion: Comparable, CustomStringConvertible {
  let major: Int
  let minor: Int
  let patch: Int
  /// Dot-separated pre-release identifiers (`["rc", "2"]`); empty for a release.
  let prerelease: [String]

  init?(_ text: String) {
    var rest = Substring(text)
    if rest.first == "v" || rest.first == "V" { rest = rest.dropFirst() }
    if let plus = rest.firstIndex(of: "+") {
      guard Self.identifiers(rest[rest.index(after: plus)...]) != nil else { return nil }
      rest = rest[..<plus]
    }
    var pre: [String] = []
    if let dash = rest.firstIndex(of: "-") {
      guard let ids = Self.identifiers(rest[rest.index(after: dash)...]) else { return nil }
      pre = ids
      rest = rest[..<dash]
    }
    let parts = rest.split(separator: ".", omittingEmptySubsequences: false)
    guard (2...3).contains(parts.count) else { return nil }
    var numbers: [Int] = []
    for part in parts {
      guard Self.isNumeric(part), let number = Int(part) else { return nil }
      numbers.append(number)
    }
    major = numbers[0]
    minor = numbers[1]
    patch = numbers.count > 2 ? numbers[2] : 0
    prerelease = pre
  }

  var isPrerelease: Bool { !prerelease.isEmpty }

  /// `1.2.3` or `1.2.3-rc.2`, without a leading `v` or build metadata.
  var description: String {
    let core = "\(major).\(minor).\(patch)"
    return prerelease.isEmpty ? core : core + "-" + prerelease.joined(separator: ".")
  }

  static func == (lhs: AppVersion, rhs: AppVersion) -> Bool {
    (lhs.major, lhs.minor, lhs.patch) == (rhs.major, rhs.minor, rhs.patch) && lhs.prerelease == rhs.prerelease
  }

  static func < (lhs: AppVersion, rhs: AppVersion) -> Bool {
    if (lhs.major, lhs.minor, lhs.patch) != (rhs.major, rhs.minor, rhs.patch) {
      return (lhs.major, lhs.minor, lhs.patch) < (rhs.major, rhs.minor, rhs.patch)
    }
    // A release outranks any of its pre-releases.
    if lhs.prerelease.isEmpty || rhs.prerelease.isEmpty { return !lhs.prerelease.isEmpty && rhs.prerelease.isEmpty }
    for (a, b) in zip(lhs.prerelease, rhs.prerelease) where a != b {
      switch (isNumeric(Substring(a)), isNumeric(Substring(b))) {
      // Digit strings without leading zeros: the longer is larger, and no Int can overflow.
      case (true, true): return a.count != b.count ? a.count < b.count : a < b
      case (true, false): return true  // numeric identifiers sort below alphanumeric ones
      case (false, true): return false
      case (false, false): return a < b
      }
    }
    return lhs.prerelease.count < rhs.prerelease.count
  }

  private static func isNumeric(_ text: Substring) -> Bool {
    !text.isEmpty && text.allSatisfy { $0.isASCII && $0.isNumber }
  }

  /// Non-empty dot-separated identifiers of ASCII letters, digits and hyphens, or nil. As in
  /// SemVer, numeric identifiers have no leading zeros (so `rc.01` can't tie with `rc.1`).
  private static func identifiers(_ text: Substring) -> [String]? {
    let ids = text.split(separator: ".", omittingEmptySubsequences: false)
    let valid = ids.allSatisfy { id in
      !id.isEmpty && id.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-") }
        && !(isNumeric(id) && id.count > 1 && id.first == "0")
    }
    return valid ? ids.map(String.init) : nil
  }
}

/// The fields of GitHub's `/releases/latest` response the update check reads.
struct LatestRelease: Codable, Equatable {
  var tagName: String
  var htmlURL: String
  var prerelease: Bool
  var draft: Bool

  enum CodingKeys: String, CodingKey {
    case tagName = "tag_name"
    case htmlURL = "html_url"
    case prerelease
    case draft
  }
}

/// A newer release to tell the user about.
struct UpdateAvailable: Codable, Equatable {
  /// Display version without a leading `v`, e.g. `2.3.0`.
  var version: String
  var tag: String
  /// The release's page on GitHub, with its notes.
  var notesURL: String
  /// The one-line Terminal command from docs/install.md that installs this release.
  var installCommand: String
}

/// Checks GitHub Releases for a newer app. The only request is a GET of `latestURL`; the
/// decision and the throttle are pure so they can be tested without the network.
enum UpdateCheck {
  static let repository = "https://github.com/BrendanH18/Marketpulse"
  static let latestURL = URL(string: "https://api.github.com/repos/BrendanH18/Marketpulse/releases/latest")!
  static let interval: TimeInterval = 24 * 60 * 60
  /// docs/install.md's recommended command; it always installs the latest release.
  static let latestInstallCommand = "curl -fsSL \(repository)/releases/latest/download/install.sh | bash"

  /// docs/install.md's command for a particular version, or the latest-release command when the
  /// tag isn't a plain `vX.Y.Z` (the only form scripts/install.sh downloads). The tag comes from
  /// the network and ends up in Terminal, so nothing else is ever interpolated.
  static func installCommand(tag: String) -> String {
    let plain = tag.range(of: #"^v[0-9]+\.[0-9]+\.[0-9]+$"#, options: .regularExpression) != nil
    guard plain else { return latestInstallCommand }
    return "curl -fsSL \(repository)/releases/download/\(tag)/install.sh | bash -s -- --version \(tag)"
  }

  /// Whether a check is due: never checked, at least a day since the last one, or a last check
  /// in the future (the clock moved back), which would otherwise block checks until it passed.
  static func isDue(lastCheck: Date?, now: Date = Date()) -> Bool {
    guard let lastCheck else { return true }
    let elapsed = now.timeIntervalSince(lastCheck)
    return elapsed < 0 || elapsed >= interval
  }

  /// The update to offer, or nil: development builds (no parseable current version), a
  /// malformed, draft or pre-release latest tag, or a latest release that isn't newer.
  static func decide(current: String?, latestTag: String?, notesURL: String? = nil, prerelease: Bool, draft: Bool)
    -> UpdateAvailable?
  {
    guard !prerelease, !draft, let current = current.flatMap(AppVersion.init),
      let tag = latestTag, let latest = AppVersion(tag),
      !latest.isPrerelease, latest > current
    else { return nil }
    // Only link to this repository's releases, whatever the response says.
    let notes = notesURL.flatMap { $0.hasPrefix(repository + "/releases/") ? $0 : nil }
    return UpdateAvailable(
      version: tag.hasPrefix("v") || tag.hasPrefix("V") ? String(tag.dropFirst()) : tag,
      tag: tag,
      notesURL: notes ?? repository + "/releases/latest",
      installCommand: installCommand(tag: tag))
  }

  static func decide(current: String?, latest: LatestRelease?) -> UpdateAvailable? {
    guard let latest else { return nil }
    return decide(
      current: current, latestTag: latest.tagName, notesURL: latest.htmlURL, prerelease: latest.prerelease,
      draft: latest.draft)
  }

  /// This app's `CFBundleShortVersionString`; nil in development builds, which have none.
  static var currentVersion: String? {
    Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String
  }

  /// No cookies, credentials or cache, so the request carries nothing from earlier ones.
  static let ephemeralSession: URLSession = {
    let config = URLSessionConfiguration.ephemeral
    config.httpCookieAcceptPolicy = .never
    config.httpShouldSetCookies = false
    config.urlCredentialStorage = nil
    config.urlCache = nil
    config.timeoutIntervalForRequest = 10
    config.timeoutIntervalForResource = 15
    return URLSession(configuration: config)
  }()

  /// The request `fetchLatest` makes; separate so its headers can be checked.
  static func request(appVersion: String? = currentVersion) -> URLRequest {
    var request = URLRequest(url: latestURL, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10)
    request.httpMethod = "GET"
    request.httpShouldHandleCookies = false
    request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
    request.setValue("MarketPulse/\(appVersion ?? "dev")", forHTTPHeaderField: "User-Agent")
    return request
  }

  /// GitHub's latest release, or nil on any failure (offline, timeout, rate limit, no releases
  /// yet, unexpected JSON). Never throws and logs nothing.
  static func fetchLatest(session: URLSession = ephemeralSession, appVersion: String? = currentVersion) async
    -> LatestRelease?
  {
    guard let (data, response) = try? await session.data(for: request(appVersion: appVersion)),
      (response as? HTTPURLResponse)?.statusCode == 200
    else { return nil }
    return try? JSONDecoder().decode(LatestRelease.self, from: data)
  }
}
