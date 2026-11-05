// Operate only the supplied fixture process via its WebKit accessibility tree.
import Cocoa
import ApplicationServices

struct CheckError: Error { let message: String }
let app = AXUIElementCreateApplication(Int32(CommandLine.arguments[1])!)
func value(_ node: AXUIElement, _ key: String) -> AnyObject? {
    var result: CFTypeRef?
    guard AXUIElementCopyAttributeValue(node, key as CFString, &result) == .success else { return nil }
    return result
}
func search(_ node: AXUIElement, _ id: String, depth: Int = 0) -> AXUIElement? {
    if value(node, "AXDOMIdentifier") as? String == id { return node }
    if id.hasPrefix("button:"), let title = value(node, "AXTitle") as? String,
       title.hasPrefix(String(id.dropFirst(7))),
       ["AXButton", "AXCheckBox", "AXRadioButton", "AXRow"].contains(value(node, "AXRole") as? String ?? "") { return node }
    guard depth < 35 else { return nil }
    for child in value(node, "AXChildren") as? [AXUIElement] ?? [] {
        if let found = search(child, id, depth: depth + 1) { return found }
    }
    return nil
}
func element(_ id: String) throws -> AXUIElement {
    let deadline = Date().addingTimeInterval(10)
    repeat {
        if let found = search(app, id) { return found }
        Thread.sleep(forTimeInterval: 0.12)
    } while Date() < deadline
    throw CheckError(message: "Control unavailable: " + id)
}
func press(_ id: String) throws {
    guard AXUIElementPerformAction(try element(id), kAXPressAction as CFString) == .success else {
        throw CheckError(message: "Control refused press: " + id)
    }
}
do {
    guard AXIsProcessTrusted() else { throw CheckError(message: "The test driver requires existing Accessibility permission.") }
    switch CommandLine.arguments[2] {
    case "press": try press(CommandLine.arguments[3])
    case "set":
        let node = try element(CommandLine.arguments[3])
        guard AXUIElementSetAttributeValue(node, kAXValueAttribute as CFString,
            CommandLine.arguments[4] as CFString) == .success else { throw CheckError(message: "Text field refused edit") }
    case "value": print(value(try element(CommandLine.arguments[3]), "AXValue") ?? "")
    case "present": _ = try element(CommandLine.arguments[3])
    default: throw CheckError(message: "Unknown test operation")
    }
} catch { fputs("\(error)\n", stderr); exit(1) }
