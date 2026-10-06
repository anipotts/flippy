// Flippy.app's executable: starts the Python daemon as a child and waits for it.
//
// The daemon runs as a child (not exec'd) so macOS treats Flippy.app as the
// "responsible" process: the Screen Recording permission is granted to Flippy,
// not to whatever terminal installed it. The repo path comes from Info.plist
// (FlippyRoot), written by scripts/install_mac.sh.
import Foundation

let info = Bundle.main.infoDictionary ?? [:]
guard let root = info["FlippyRoot"] as? String else {
    FileHandle.standardError.write("Flippy.app: FlippyRoot missing from Info.plist\n".data(using: .utf8)!)
    exit(1)
}

let logURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/flippy.log")
FileManager.default.createFile(atPath: logURL.path, contents: nil, attributes: nil)  // no-op if it exists
let log = try? FileHandle(forWritingTo: logURL)
log?.seekToEndOfFile()

let daemon = Process()
daemon.executableURL = URL(fileURLWithPath: root + "/bin/flippy-daemon")
daemon.arguments = Array(CommandLine.arguments.dropFirst())
var env = ProcessInfo.processInfo.environment
env.removeValue(forKey: "ANTHROPIC_API_KEY")  // bill the Pro/Max subscription, never the API
env["FLIPPY_APP"] = Bundle.main.bundlePath
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
    FileHandle.standardError.write("Flippy.app: couldn't start \(root)/bin/flippy-daemon: \(error)\n".data(using: .utf8)!)
    exit(1)
}
daemon.terminationHandler = { p in exit(p.terminationStatus) }
dispatchMain()
