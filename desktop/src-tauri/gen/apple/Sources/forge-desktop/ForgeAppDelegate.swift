import UIKit

/// Custom AppDelegate that integrates APNs push notifications with
/// the Tauri WebView application.
///
/// Tauri's generated iOS project creates a SceneDelegate-based app.
/// This delegate is registered via the `@UIApplicationDelegateAdaptor`
/// pattern or as a plugin. It handles the APNs lifecycle callbacks.
class ForgeAppDelegate: NSObject, UIApplicationDelegate {

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        // Request push notification permission on launch
        ForgePush.shared.requestPermission()
        return true
    }

    // MARK: - APNs Callbacks

    func application(
        _ application: UIApplication,
        didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
        ForgePush.shared.didRegisterForRemoteNotifications(deviceToken: deviceToken)
    }

    func application(
        _ application: UIApplication,
        didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
        ForgePush.shared.didFailToRegisterForRemoteNotifications(error: error)
    }

    // MARK: - Background Notification (Silent Push)

    func application(
        _ application: UIApplication,
        didReceiveRemoteNotification userInfo: [AnyHashable: Any],
        fetchCompletionHandler completionHandler: @escaping (UIBackgroundFetchResult) -> Void
    ) {
        // Handle silent/background push notifications
        // These can be used to update badge count or prefetch data
        print("[ForgeAppDelegate] Background notification received")
        completionHandler(.newData)
    }
}
