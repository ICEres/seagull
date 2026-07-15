import Foundation
import UserNotifications

// Native macOS notifications for new deliveries (replaces the CLI's
// osascript path for GUI users). Clicking a notification selects the
// delivery in the inbox via onSelectDelivery.
@MainActor
final class Notifier: NSObject, UNUserNotificationCenterDelegate {

    var onSelectDelivery: ((String) -> Void)?

    private let center = UNUserNotificationCenter.current()

    func activate() {
        center.delegate = self
    }

    func requestAuthorization() async -> Bool {
        (try? await center.requestAuthorization(options: [.alert, .sound, .badge])) ?? false
    }

    func notifyNewDelivery(id: String, sender: String, snippet: String?) {
        let content = UNMutableNotificationContent()
        content.title = "New delivery from \(sender)"
        if let snippet, !snippet.isEmpty {
            content.body = String(snippet.prefix(96))
        }
        content.sound = .default
        content.userInfo = ["delivery_id": id]
        let request = UNNotificationRequest(identifier: "delivery-\(id)", content: content, trigger: nil)
        center.add(request)
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
        guard let deliveryID = response.notification.request.content.userInfo["delivery_id"] as? String else {
            return
        }
        await MainActor.run {
            onSelectDelivery?(deliveryID)
        }
    }
}
