use serde::Deserialize;
use std::sync::Mutex;
use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem, Submenu},
    tray::TrayIconBuilder,
    AppHandle, Emitter, Manager,
};

// ─── Tray state (updated from frontend) ─────────────

#[derive(Default, Clone)]
pub struct TrayState {
    pub active_pipelines: u32,
    pub has_unread: bool,
    pub has_pending_approval: bool,
    pub agents: Vec<AgentTrayInfo>,
}

#[derive(Clone, Deserialize)]
pub struct AgentTrayInfo {
    pub name: String,
    pub emoji: String,
    pub status: String,
}

pub struct TrayStateWrapper(pub Mutex<TrayState>);

// ─── Create initial tray ─────────────────────────────

pub fn create_tray(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    // Store tray state in app managed state
    app.manage(TrayStateWrapper(Mutex::new(TrayState::default())));

    let menu = build_tray_menu(app, &TrayState::default())?;

    TrayIconBuilder::new()
        .icon(app.default_window_icon().cloned().unwrap())
        .menu(&menu)
        .tooltip("Forge")
        .show_menu_on_left_click(false)
        .on_tray_icon_event(|tray, event| {
            if let tauri::tray::TrayIconEvent::Click {
                button: tauri::tray::MouseButton::Left,
                ..
            } = event
            {
                let app = tray.app_handle();
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.unminimize();
                    let _ = window.set_focus();
                }
            }
        })
        .on_menu_event(|app: &AppHandle, event| match event.id.as_ref() {
            "show" => {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.unminimize();
                    let _ = window.set_focus();
                }
            }
            "pipelines" => {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                    // Emit event so frontend can navigate to pipelines
                    let _ = window.emit("navigate", "pipelines");
                }
            }
            "quit" => {
                app.exit(0);
            }
            _ => {}
        })
        .build(app)?;

    Ok(())
}

// ─── Build menu from state ───────────────────────────

fn build_tray_menu(
    app: &AppHandle,
    state: &TrayState,
) -> Result<Menu<tauri::Wry>, Box<dyn std::error::Error>> {
    let show = MenuItem::with_id(app, "show", "Open Forge", true, None::<&str>)?;

    let pipeline_label = if state.active_pipelines > 0 {
        format!("Active Pipelines: {}", state.active_pipelines)
    } else {
        "No Active Pipelines".to_string()
    };
    let pipelines = MenuItem::with_id(
        app,
        "pipelines",
        &pipeline_label,
        state.active_pipelines > 0,
        None::<&str>,
    )?;

    let sep1 = PredefinedMenuItem::separator(app)?;

    // Agent status submenu
    let agent_submenu = if state.agents.is_empty() {
        let no_agents = MenuItem::with_id(app, "no_agents", "No agents online", false, None::<&str>)?;
        Submenu::with_items(app, "Agent Status", true, &[&no_agents])?
    } else {
        let items: Vec<MenuItem<tauri::Wry>> = state
            .agents
            .iter()
            .enumerate()
            .map(|(i, agent)| {
                let label = format!("{} {} — {}", agent.emoji, agent.name, agent.status);
                MenuItem::with_id(
                    app,
                    &format!("agent_{}", i),
                    &label,
                    false,
                    None::<&str>,
                )
                .unwrap()
            })
            .collect();

        let refs: Vec<&dyn tauri::menu::IsMenuItem<tauri::Wry>> =
            items.iter().map(|i| i as &dyn tauri::menu::IsMenuItem<tauri::Wry>).collect();
        Submenu::with_items(app, "Agent Status", true, &refs)?
    };

    let sep2 = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(app, "quit", "Quit Forge", true, None::<&str>)?;

    let menu = Menu::with_items(
        app,
        &[&show, &pipelines, &sep1, &agent_submenu, &sep2, &quit],
    )?;

    Ok(menu)
}

// ─── Update tray from frontend ───────────────────────

#[tauri::command]
pub fn update_tray_state(
    app: AppHandle,
    active_pipelines: u32,
    has_unread: bool,
    has_pending_approval: bool,
    agents: Vec<AgentTrayInfo>,
) -> Result<(), String> {
    // Update stored state
    let wrapper = app.state::<TrayStateWrapper>();
    let mut state = wrapper.0.lock().map_err(|e| e.to_string())?;
    state.active_pipelines = active_pipelines;
    state.has_unread = has_unread;
    state.has_pending_approval = has_pending_approval;
    state.agents = agents;

    let state_clone = state.clone();
    drop(state);

    // Rebuild menu with updated state
    let menu = build_tray_menu(&app, &state_clone).map_err(|e| e.to_string())?;

    // Update the tray menu
    if let Some(tray) = app.tray_by_id("main") {
        let _ = tray.set_menu(Some(menu));

        // Update tooltip based on state
        let tooltip = if state_clone.has_pending_approval {
            "Forge — Approval pending"
        } else if state_clone.active_pipelines > 0 {
            "Forge — Pipelines running"
        } else if state_clone.has_unread {
            "Forge — New messages"
        } else {
            "Forge"
        };
        let _ = tray.set_tooltip(Some(tooltip));
    }

    Ok(())
}
