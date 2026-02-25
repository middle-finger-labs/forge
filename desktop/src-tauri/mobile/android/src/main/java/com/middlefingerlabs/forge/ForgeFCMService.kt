package com.middlefingerlabs.forge

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

/**
 * Firebase Cloud Messaging service for Forge push notifications.
 *
 * Handles:
 * - FCM token registration and refresh
 * - Incoming push notification display
 * - Deep-link routing on notification tap
 *
 * **Requirements:**
 * - Firebase project configured with google-services.json
 * - Firebase Messaging dependency in build.gradle
 */
class ForgeFCMService : FirebaseMessagingService() {

    companion object {
        private const val TAG = "ForgeFCM"
        private const val CHANNEL_ID = "forge_notifications"
        private const val CHANNEL_NAME = "Forge Notifications"

        /** Key used to store the latest FCM token for the JS bridge to read. */
        const val PREF_FCM_TOKEN = "forge_fcm_token"
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    /**
     * Called when a new FCM token is generated (first launch or token refresh).
     * Stores the token in SharedPreferences so the WebView JS bridge can read it.
     */
    override fun onNewToken(token: String) {
        super.onNewToken(token)
        Log.d(TAG, "FCM token refreshed: ${token.take(16)}...")

        // Persist token for the WebView to pick up
        getSharedPreferences("forge_push", Context.MODE_PRIVATE)
            .edit()
            .putString(PREF_FCM_TOKEN, token)
            .apply()

        // Notify the WebView if it's running
        // The JS bridge polls for this on init and when the app resumes
    }

    /**
     * Called when a push notification is received (foreground or background).
     */
    override fun onMessageReceived(message: RemoteMessage) {
        super.onMessageReceived(message)
        Log.d(TAG, "Push received: ${message.data}")

        val title = message.notification?.title
            ?: message.data["title"]
            ?: "Forge"

        val body = message.notification?.body
            ?: message.data["body"]
            ?: ""

        // Build the deep-link intent from the data payload
        val deepLinkUrl = message.data["url"]

        showNotification(title, body, deepLinkUrl)
    }

    /**
     * Display a local notification with optional deep-link on tap.
     */
    private fun showNotification(title: String, body: String, deepLinkUrl: String?) {
        val notificationManager =
            getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

        // Create an intent that opens the app via the forge:// deep link
        val intent = if (deepLinkUrl != null) {
            Intent(Intent.ACTION_VIEW, Uri.parse(deepLinkUrl)).apply {
                setPackage(packageName)
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
        } else {
            packageManager.getLaunchIntentForPackage(packageName)?.apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
        }

        val pendingIntent = PendingIntent.getActivity(
            this,
            System.currentTimeMillis().toInt(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)  // Replace with app icon
            .setContentTitle(title)
            .setContentText(body)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(pendingIntent)
            .build()

        notificationManager.notify(System.currentTimeMillis().toInt(), notification)
    }

    /**
     * Create the notification channel (required for Android 8+).
     */
    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                CHANNEL_NAME,
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Pipeline updates, approvals, and agent messages"
                enableVibration(true)
            }

            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }
}
