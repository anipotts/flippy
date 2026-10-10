// Flippy.app's executable: starts the Python daemon as a child and waits for it.
//
// The daemon runs as a child (not exec'd) so macOS treats Flippy.app as the
// "responsible" process: the Screen Recording permission is granted to Flippy,
// not to whatever terminal installed it.
//
// Two kinds of app:
// - Installed from a checkout or download (scripts/install_mac.sh): Info.plist's FlippyRoot is that folder, and
//   the daemon runs from its .venv.
// - Self-contained (scripts/build_app.sh, the Flippy.dmg you drag to Applications): FlippyBundled. Python and the
//   packages are inside the app; the code is copied out to ~/Library/Application Support/Flippy/code on first
//   launch, and updates replace it there, so the app itself never changes and macOS keeps its permissions.
import Foundation

let info = Bundle.main.infoDictionary ?? [:]
let bundled = info["FlippyBundled"] as? Bool ?? false
let resources = Bundle.main.resourcePath ?? ""

func versionParts(_ path: String) -> [Int] {
    let text = (try? String(contentsOfFile: path + "/VERSION", encoding: .utf8)) ?? ""
    return text.trimmingCharacters(in: .whitespacesAndNewlines).split(separator: ".").map { Int($0) ?? 0 }
}

func newer(_ a: [Int], than b: [Int]) -> Bool {
    for i in 0..<max(a.count, b.count) {
        let x = i < a.count ? a[i] : 0, y = i < b.count ? b[i] : 0
        if x != y { return x > y }
    }
    return false
}

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(("Flippy.app: " + message + "\n").data(using: .utf8)!)
    exit(1)
}

/// The code the daemon runs: the app's own copy in Application Support, refreshed when this app is newer
/// (a new Flippy.dmg) and left alone when it's older (Flippy updated itself since).
func bundledRoot(_ appName: String) -> String {
    let fm = FileManager.default
    let support = fm.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/" + appName)
    let code = support.appendingPathComponent("code").path
    let shipped = resources + "/code"
    let installed = fm.fileExists(atPath: code + "/flippy/daemon.py")
    if !installed || newer(versionParts(shipped), than: versionParts(code)) {
        let staging = support.appendingPathComponent("code.new").path
        do {
            try fm.createDirectory(atPath: support.path, withIntermediateDirectories: true)
            try? fm.removeItem(atPath: staging)
            try fm.copyItem(atPath: shipped, toPath: staging)
            try? fm.removeItem(atPath: code)
            try fm.moveItem(atPath: staging, toPath: code)
        } catch {
            fail("couldn't set up \(code): \(error)")
        }
    }
    return code
}

let profile = info["FlippyProfile"] as? String ?? "default"
guard profile == "default" || profile == "demo" else { exit(1) }
let appName = profile == "demo" ? "Flippy Demo" : "Flippy"
let root: String
if bundled {
    root = bundledRoot(appName)
} else {
    guard let r = info["FlippyRoot"] as? String else { fail("FlippyRoot missing from Info.plist") }
    root = r
}
let logName = profile == "demo" ? "flippy-demo.log" : "flippy.log"
let logURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/" + logName)
FileManager.default.createFile(atPath: logURL.path, contents: nil, attributes: nil)  // no-op if it exists
let log = try? FileHandle(forWritingTo: logURL)
log?.seekToEndOfFile()

let daemon = Process()
var env = ProcessInfo.processInfo.environment
env.removeValue(forKey: "ANTHROPIC_API_KEY")  // bill the Pro/Max subscription, never the API
env["FLIPPY_APP"] = Bundle.main.bundlePath
env["FLIPPY_PROFILE"] = profile
if bundled {  // the app's own Python, nothing from the user's
    daemon.executableURL = URL(fileURLWithPath: resources + "/python/bin/python3")
    daemon.arguments = ["-m", "flippy.daemon"] + Array(CommandLine.arguments.dropFirst())
    daemon.currentDirectoryURL = URL(fileURLWithPath: root)
    env["FLIPPY_BUNDLED"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env.removeValue(forKey: "PYTHONPATH")
    env.removeValue(forKey: "PYTHONHOME")
    env["SSL_CERT_FILE"] = resources + "/cacert.pem"  // this Python has no access to the system's certificates
} else {
    daemon.executableURL = URL(fileURLWithPath: root + "/bin/flippy-daemon")
    daemon.arguments = Array(CommandLine.arguments.dropFirst())
}
daemon.environment = env
if let log = log {
    daemon.standardOutput = log
    daemon.standardError = log
}

var signalSources: [DispatchSourceSignal] = []

// Quitting Flippy.app (logout, Activity Monitor) stops the daemon too.
for sig in [SIGTERM, SIGINT, SIGHUP] {
    signal(sig, SIG_IGN)
    let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    src.setEventHandler { daemon.terminate() }
    src.resume()
    signalSources.append(src)
}

do {
    try daemon.run()
} catch {
    fail("couldn't start the daemon in \(root): \(error)")
}
daemon.terminationHandler = { p in exit(p.terminationStatus) }
dispatchMain()
