import UIKit
import UserNotifications
import WebKit

/// Handles APNs push notification registration and delivery for Forge.
///
/// This class acts as a bridge between the native iOS push notification
/// system and the Tauri WebView. It:
/// 1. Requests notification permission
/// 2. Registers for remote notifications
/// 3. Forwards the device token to the Rust side via evaluateJavaScript
/// 4. Handles notification taps for deep-link routing
///
/// **Requirements:**
/// - Apple Developer account with Push Notifications capability
/// - Push notification entitlement in the Xcode project
/// - APNs key (.p8) configured on the backend
class ForgePush: NSObject {
    static let shared = ForgePush()

    /// The most recent APNs device token (hex-encoded).
    private(set) var deviceToken: String?

    /// A reference to the WKWebView for JS bridging.
    weak var webView: WKWebView?

    private override init() {
        super.init()
    }

    // MARK: - Permission & Registration

    /// Request notification permission and register for remote notifications.
    func requestPermission() {
        let center = UNUserNotificationCenter.current()
        center.delegate = self

        center.requestAuthorization(options: [.alert, .sound, .badge]) { granted, error in
            if let error = error {
                print("[ForgePush] Permission error: \(error.localizedDescription)")
                return
            }

            guard granted else {
                print("[ForgePush] Permission denied by user")
                return
            }

            print("[ForgePush] Permission granted")

            DispatchQueue.main.async {
                UIApplication.shared.registerForRemoteNotifications()
            }
        }
    }

    // MARK: - Token Handling

    /// Called from AppDelegate when APNs registration succeeds.
    func didRegisterForRemoteNotifications(deviceToken data: Data) {
        let token = data.map { String(format: "%02x", $0) }.joined()
        self.deviceToken = token
        print("[ForgePush] APNs token: \(token.prefix(16))...")

        // Forward token to the WebView so the JS layer can register it with the backend
        forwardTokenToWebView(token: token)
    }

    /// Called from AppDelegate when APNs registration fails.
    func didFailToRegisterForRemoteNotifications(error: Error) {
        print("[ForgePush] Registration failed: \(error.localizedDescription)")

        // Notify JS side of the failure
        evaluateJS("""
            window.__FORGE_PUSH_ERROR && window.__FORGE_PUSH_ERROR('\(error.localizedDescription.replacingOccurrences(of: "'", with: "\\'"))');
        """)
    }

    // MARK: - WebView Bridge

    /// Forward the device token to the WebView's JS context.
    private func forwardTokenToWebView(token: String) {
        evaluateJS("""
            window.__FORGE_PUSH_TOKEN && window.__FORGE_PUSH_TOKEN('\(token)');
        """)
    }

    /// Evaluate JavaScript in the WebView on the main thread.
    private func evaluateJS(_ js: String) {
        DispatchQueue.main.async { [weak self] in
            self?.webView?.evaluateJavaScript(js) { _, error in
                if let error = error {
                    print("[ForgePush] JS eval error: \(error.localizedDescription)")
                }
            }
        }
    }

    // MARK: - Deep Link Routing

    /// Parse a notification's userInfo and generate a deep-link URL.
    private func deepLinkURL(from userInfo: [AnyHashable: Any]) -> URL? {
        // The backend sends a "data" dict with a "url" key containing the forge:// URL
        if let data = userInfo["data"] as? [String: Any],
           let urlString = data["url"] as? String,
           let url = URL(string: urlString) {
            return url
        }

        // Fallback: check top-level "url" key (for FCM compatibility)
        if let urlString = userInfo["url"] as? String,
           let url = URL(string: urlString) {
            return url
        }

        return nil
    }

    /// Route a deep-link URL to the WebView.
    func handleDeepLink(url: URL) {
        evaluateJS("""
            window.__FORGE_DEEP_LINK && window.__FORGE_DEEP_LINK('\(url.absoluteString)');
        """)
    }
}

// MARK: - UNUserNotificationCenterDelegate

extension ForgePush: UNUserNotificationCenterDelegate {
    /// Called when a notification is received while the app is in the foreground.
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        // Show the notification banner even when the app is in the foreground
        completionHandler([.banner, .sound, .badge])
    }

    /// Called when the user taps on a notification.
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        let userInfo = response.notification.request.content.userInfo

        if let url = deepLinkURL(from: userInfo) {
            print("[ForgePush] Notification tapped, deep link: \(url)")
            handleDeepLink(url: url)
        }

        completionHandler()
    }
}
