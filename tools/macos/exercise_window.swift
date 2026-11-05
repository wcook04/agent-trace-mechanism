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
    let label = [value(node, "AXTitle"), value(node, "AXDescription")].compactMap { $0 as? String }.joined(separator: " ")
    if id.hasPrefix("button:"), label.contains(String(id.dropFirst(7))),
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
        let target = CommandLine.arguments[4]
        _ = AXUIElementSetAttributeValue(node, kAXFocusedAttribute as CFString, kCFBooleanTrue)
        _ = AXUIElementSetAttributeValue(node, kAXSelectedTextAttribute as CFString, target as CFString)
        if value(node, "AXValue") as? String != target {
            // WebKit may acknowledge AXValue writes without updating the DOM.
            // Deliver text to this fixture PID only, then verify the DOM-backed value.
            let pid = pid_t(Int32(CommandLine.arguments[1])!)
            for scalar in target {
                let newline = scalar == "\n"
                let chars = Array(String(scalar).utf16)
                for down in [true, false] {
                    let event = CGEvent(keyboardEventSource: nil, virtualKey: newline ? 36 : 0, keyDown: down)!
                    if !newline { event.keyboardSetUnicodeString(stringLength: chars.count, unicodeString: chars) }
                    event.postToPid(pid)
                }
            }
        }
        let deadline = Date().addingTimeInterval(2)
        while value(node, "AXValue") as? String != target && Date() < deadline { Thread.sleep(forTimeInterval: 0.04) }
        guard value(node, "AXValue") as? String == target else { throw CheckError(message: "Text field did not accept the requested edit: " + CommandLine.arguments[3]) }
    case "value": print(value(try element(CommandLine.arguments[3]), "AXValue") ?? "")
    case "present": _ = try element(CommandLine.arguments[3])
    default: throw CheckError(message: "Unknown test operation")
    }
} catch { fputs("\(error)\n", stderr); exit(1) }
