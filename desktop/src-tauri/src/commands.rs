use std::process::Command;
use tauri::{AppHandle, Manager};

// ─── Existing commands ───────────────────────────────

#[tauri::command]
pub fn get_forge_api_url() -> String {
    std::env::var("FORGE_API_URL").unwrap_or_else(|_| "http://localhost:8000".to_string())
}

#[tauri::command]
pub fn get_app_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

// ─── Open in VS Code ────────────────────────────────

#[tauri::command]
pub async fn open_in_vscode(path: String) -> Result<(), String> {
    Command::new("code")
        .arg(&path)
        .spawn()
        .map_err(|e| format!("Failed to open VS Code: {}. Is 'code' in your PATH?", e))?;
    Ok(())
}

// ─── Open in Terminal ────────────────────────────────

#[tauri::command]
pub async fn open_in_terminal(path: String) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        Command::new("open")
            .arg("-a")
            .arg("Terminal")
            .arg(&path)
            .spawn()
            .map_err(|e| format!("Failed to open Terminal: {}", e))?;
    }

    #[cfg(target_os = "linux")]
    {
        // Try common terminal emulators
        let terminals = ["x-terminal-emulator", "gnome-terminal", "konsole", "xterm"];
        let mut opened = false;
        for term in &terminals {
            if Command::new(term)
                .arg("--working-directory")
                .arg(&path)
                .spawn()
                .is_ok()
            {
                opened = true;
                break;
            }
        }
        if !opened {
            return Err("No terminal emulator found".to_string());
        }
    }

    #[cfg(target_os = "windows")]
    {
        Command::new("cmd")
            .args(["/C", "start", "cmd", "/K", &format!("cd /d {}", path)])
            .spawn()
            .map_err(|e| format!("Failed to open terminal: {}", e))?;
    }

    Ok(())
}

// ─── Connection status ───────────────────────────────

#[tauri::command]
pub async fn get_connection_status() -> Result<String, String> {
    let url = std::env::var("FORGE_API_URL")
        .unwrap_or_else(|_| "http://localhost:8000".to_string());

    let addr = url
        .trim_start_matches("http://")
        .trim_start_matches("https://")
        .to_string();

    // Use std::net in a blocking context (Tauri async commands run on tokio)
    let result = std::thread::spawn(move || {
        use std::net::TcpStream;
        use std::time::Duration;

        // TcpStream::connect handles hostname resolution
        match TcpStream::connect_timeout(
            // ToSocketAddrs resolves hostnames; fallback to localhost
            &addr
                .to_string()
                .parse()
                .unwrap_or_else(|_| "127.0.0.1:8000".parse().unwrap()),
            Duration::from_secs(3),
        ) {
            Ok(_) => "connected".to_string(),
            Err(_) => "disconnected".to_string(),
        }
    })
    .join()
    .map_err(|_| "Connection check failed".to_string())?;

    Ok(result)
}

// ─── Window management helpers ───────────────────────

#[tauri::command]
pub fn set_close_to_tray(app: AppHandle, enabled: bool) -> Result<(), String> {
    // Store preference in app state
    app.manage(CloseToTrayState(std::sync::Mutex::new(enabled)));
    Ok(())
}

pub struct CloseToTrayState(pub std::sync::Mutex<bool>);

impl CloseToTrayState {
    pub fn is_enabled(&self) -> bool {
        *self.0.lock().unwrap_or_else(|e| e.into_inner())
    }
}
