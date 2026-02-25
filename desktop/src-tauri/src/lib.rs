mod commands;
mod tray;

use commands::CloseToTrayState;
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // ─── Plugins ─────────────────────────────────
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_websocket::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_window_state::Builder::new().build())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _shortcut, event| {
                    if let tauri_plugin_global_shortcut::ShortcutState::Pressed = event.state {
                        // Global shortcut: focus the Forge window
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.unminimize();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(),
        )
        // ─── Commands ────────────────────────────────
        .invoke_handler(tauri::generate_handler![
            commands::get_forge_api_url,
            commands::get_app_version,
            commands::open_in_vscode,
            commands::open_in_terminal,
            commands::get_connection_status,
            commands::set_close_to_tray,
            tray::update_tray_state,
        ])
        // ─── Setup ───────────────────────────────────
        .setup(|app| {
            // Initialize close-to-tray state (default: enabled)
            app.manage(CloseToTrayState(std::sync::Mutex::new(true)));

            // Create system tray
            tray::create_tray(app.handle())?;

            // Register global shortcut: Cmd+Shift+F to focus window
            {
                use tauri_plugin_global_shortcut::GlobalShortcutExt;
                let shortcut = "CmdOrCtrl+Shift+F";
                if let Err(e) = app.global_shortcut().register(shortcut) {
                    eprintln!("Failed to register global shortcut {}: {}", shortcut, e);
                }
            }

            // Close-to-tray behavior
            let window = app.get_webview_window("main").unwrap();
            let window_for_event = window.clone();
            let app_handle = app.handle().clone();

            window.on_window_event(move |event| {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    // Check if close-to-tray is enabled
                    let close_to_tray = app_handle
                        .try_state::<CloseToTrayState>()
                        .map(|s| s.is_enabled())
                        .unwrap_or(false);

                    if close_to_tray {
                        api.prevent_close();
                        let _ = window_for_event.hide();
                    }
                    // If not close-to-tray, let the window close normally
                }
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running forge");
}
