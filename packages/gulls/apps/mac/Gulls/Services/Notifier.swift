import Foundation
import UserNotifications

// Native macOS notifications for new deliveries (replaces the CLI's
// osascript path for GUI users). Notifications are actionable: Reply with
// text input, Ack, and — when a rule-generated draft was previewed in the
// banner — Send draft. Clicking the notification body selects the delivery.
@MainActor
final class Notifier: NSObject, UNUserNotificationCenterDelegate {

    var onSelectDelivery: ((String) -> Void)?
    var onReply: ((String, String) -> Void)?
    var onAck: ((String) -> Void)?
    var onSendDraft: ((String, String) -> Void)?

    private let center = UNUserNotificationCenter.current()

    private enum Category {
        static let delivery = "delivery"
        static let deliveryWithDraft = "delivery-draft"
    }

    private enum Action {
        static let reply = "reply"
        static let ack = "ack"
        static let sendDraft = "send-draft"
    }

    func activate() {
        center.delegate = self

        let reply = UNTextInputNotificationAction(
            identifier: Action.reply,
            title: "Reply",
            options: [],
            textInputButtonTitle: "Send",
            textInputPlaceholder: "Type a reply…"
        )
        let ack = UNNotificationAction(identifier: Action.ack, title: "Ack", options: [])
        let sendDraft = UNNotificationAction(identifier: Action.sendDraft, title: "Send draft", options: [])

        center.setNotificationCategories([
            UNNotificationCategory(
                identifier: Category.delivery,
                actions: [reply, ack],
                intentIdentifiers: [],
                options: []
            ),
            UNNotificationCategory(
                identifier: Category.deliveryWithDraft,
                actions: [sendDraft, reply, ack],
                intentIdentifiers: [],
                options: []
            ),
        ])
    }

    func requestAuthorization() async -> Bool {
        (try? await center.requestAuthorization(options: [.alert, .sound, .badge])) ?? false
    }

    // draft, when present, is previewed in the banner and offered as a
    // "Send draft" action. The action sends exactly this previewed text —
    // informed approval means what you saw is what goes out.
    func notifyNewDelivery(id: String, sender: String, snippet: String?, draft: String? = nil) {
        let content = UNMutableNotificationContent()
        content.title = "New delivery from \(sender)"
        if let snippet, !snippet.isEmpty {
            content.body = String(snippet.prefix(96))
        }
        if let draft, !draft.isEmpty {
            content.subtitle = "Draft ready: \(String(draft.prefix(72)))"
            content.categoryIdentifier = Category.deliveryWithDraft
            content.userInfo = ["delivery_id": id, "draft": draft]
        } else {
            content.categoryIdentifier = Category.delivery
            content.userInfo = ["delivery_id": id]
        }
        content.sound = .default
        let request = UNNotificationRequest(identifier: Self.identifier(for: id), content: content, trigger: nil)
        center.add(request)
    }

    // Removes the banner for a delivery decided elsewhere (CLI, another
    // machine) so notifications stay a trustworthy view of the queue.
    func withdraw(deliveryID: String) {
        center.removeDeliveredNotifications(withIdentifiers: [Self.identifier(for: deliveryID)])
    }

    private static func identifier(for deliveryID: String) -> String {
        "delivery-\(deliveryID)"
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        [.banner, .sound]
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse
    ) async {
        let userInfo = response.notification.request.content.userInfo
        guard let deliveryID = userInfo["delivery_id"] as? String else {
            return
        }
        let actionID = response.actionIdentifier
        let replyText = (response as? UNTextInputNotificationResponse)?.userText
        let draft = userInfo["draft"] as? String

        await MainActor.run {
            switch actionID {
            case Action.reply:
                if let replyText, !replyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    onReply?(deliveryID, replyText)
                }
            case Action.ack:
                onAck?(deliveryID)
            case Action.sendDraft:
                if let draft {
                    onSendDraft?(deliveryID, draft)
                }
            default:
                onSelectDelivery?(deliveryID)
            }
        }
    }
}
