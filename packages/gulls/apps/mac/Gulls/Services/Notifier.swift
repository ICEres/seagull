import Foundation
import UserNotifications

// Native macOS notifications for new deliveries (replaces the CLI's
// osascript path for GUI users). A banner announces that a decision is
// waiting; it never carries out one. Reply sends text the owner typed here
// and nothing else, Ack marks the delivery handled, and Review draft opens
// the app — a generated draft is approved on the trusted review surface,
// where it can be read in full, never from a banner preview of it.
//
// Message and draft text stay out of the banner unless the owner opts in,
// because a banner is readable on a locked screen.
//
// Not final: tests subclass it to record notify/withdraw calls without
// touching the real notification center.
@MainActor
class Notifier: NSObject, UNUserNotificationCenterDelegate {

    var onSelectDelivery: ((String) -> Void)?
    var onReply: ((String, String) -> Void)?
    var onAck: ((String) -> Void)?

    // Off by default: the sender and the fact of a waiting decision are
    // announced, the correspondence itself is not.
    var showsContentPreview = false

    private let center = UNUserNotificationCenter.current()

    private enum Category {
        static let delivery = "delivery"
        static let deliveryWithDraft = "delivery-draft"
    }

    private enum Action {
        static let reply = "reply"
        static let ack = "ack"
        static let reviewDraft = "review-draft"
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
        // Opens the app rather than sending: approving a generated draft is a
        // decision about text too long to fit in a banner.
        let reviewDraft = UNNotificationAction(
            identifier: Action.reviewDraft,
            title: "Review draft",
            options: [.foreground]
        )

        center.setNotificationCategories([
            UNNotificationCategory(
                identifier: Category.delivery,
                actions: [reply, ack],
                intentIdentifiers: [],
                options: []
            ),
            UNNotificationCategory(
                identifier: Category.deliveryWithDraft,
                actions: [reviewDraft, reply, ack],
                intentIdentifiers: [],
                options: []
            ),
        ])
    }

    func requestAuthorization() async -> Bool {
        (try? await center.requestAuthorization(options: [.alert, .sound, .badge])) ?? false
    }

    // `draft` decides which actions the banner offers and nothing else. Its
    // text is deliberately not carried in userInfo: no notification action
    // sends it, so a banner cannot approve a draft the owner only saw the
    // first few words of.
    func notifyNewDelivery(id: String, sender: String, snippet: String?, draft: String? = nil) {
        let content = UNMutableNotificationContent()
        content.title = "New delivery from \(sender)"
        let hasDraft = !(draft ?? "").isEmpty
        if showsContentPreview, let snippet, !snippet.isEmpty {
            content.body = String(snippet.prefix(96))
        }
        if hasDraft {
            content.subtitle = "A draft is ready to review."
            content.categoryIdentifier = Category.deliveryWithDraft
        } else {
            content.categoryIdentifier = Category.delivery
        }
        content.userInfo = ["delivery_id": id]
        content.sound = .default
        let request = UNNotificationRequest(identifier: Self.identifier(for: id), content: content, trigger: nil)
        center.add(request)
    }

    // Removes the banners for deliveries decided elsewhere (CLI, another
    // machine) so notifications stay a trustworthy view of the queue.
    func withdraw(deliveryIDs: [String]) {
        guard !deliveryIDs.isEmpty else { return }
        center.removeDeliveredNotifications(
            withIdentifiers: deliveryIDs.map(Self.identifier(for:))
        )
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

        await MainActor.run {
            switch actionID {
            case Action.reply:
                // The owner typed this here, so what was composed is what is
                // sent — the banner is the review surface for its own text.
                if let replyText, !replyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    onReply?(deliveryID, replyText)
                }
            case Action.ack:
                onAck?(deliveryID)
            default:
                // Review draft and a plain click both land here: open it.
                onSelectDelivery?(deliveryID)
            }
        }
    }
}
