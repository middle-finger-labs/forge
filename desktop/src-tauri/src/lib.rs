mod commands;

#[cfg(desktop)]
mod tray;

#[cfg(desktop)]
use commands::CloseToTrayState;
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default()
        // ─── Cross-platform plugins ─────────────────
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_websocket::init())
        .plugin(tauri_plugin_os::init())
        .plugin(tauri_plugin_haptics::init())
        .plugin(tauri_plugin_deep_link::init());

    // ─── Mobile-only plugins ────────────────────
    #[cfg(mobile)]
    let builder = builder.plugin(tauri_plugin_biometric::init());

    // ─── Desktop-only plugins ───────────────────
    #[cfg(desktop)]
    let builder = builder
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
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.unminimize();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(),
        );

    // ─── Commands ────────────────────────────────
    let builder = builder.invoke_handler(tauri::generate_handler![
        commands::get_forge_api_url,
        commands::get_app_version,
        commands::get_connection_status,
        commands::set_push_token,
        commands::get_push_token,
        commands::proxy_fetch,
        commands::save_secure_data,
        commands::get_secure_data,
        commands::delete_secure_data,
        #[cfg(desktop)]
        commands::open_in_vscode,
        #[cfg(desktop)]
        commands::open_in_terminal,
        #[cfg(desktop)]
        commands::set_close_to_tray,
        #[cfg(desktop)]
        tray::update_tray_state,
    ]);

    // ─── Setup ───────────────────────────────────
    builder
        .setup(|app| {
            // Push token state (cross-platform)
            app.manage(commands::PushTokenState(std::sync::Mutex::new(None)));

            // Desktop-only setup: tray, shortcuts, close-to-tray
            #[cfg(desktop)]
            {
                app.manage(CloseToTrayState(std::sync::Mutex::new(true)));

                tray::create_tray(app.handle())?;

                {
                    use tauri_plugin_global_shortcut::GlobalShortcutExt;
                    let shortcut = "CmdOrCtrl+Shift+F";
                    if let Err(e) = app.global_shortcut().register(shortcut) {
                        eprintln!("Failed to register global shortcut {}: {}", shortcut, e);
                    }
                }

                let window = app.get_webview_window("main").unwrap();
                let window_for_event = window.clone();
                let app_handle = app.handle().clone();

                window.on_window_event(move |event| {
                    if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                        let close_to_tray = app_handle
                            .try_state::<CloseToTrayState>()
                            .map(|s| s.is_enabled())
                            .unwrap_or(false);

                        if close_to_tray {
                            api.prevent_close();
                            let _ = window_for_event.hide();
                        }
                    }
                });
            }

            // Mobile-specific setup
            #[cfg(mobile)]
            {
                let _handle = app.handle().clone();
                // Deep links are handled via the plugin's event system
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running forge");
}
