use tauri::AppHandle;

// ─── Push notification state ────────────────────────

/// Stores the latest push device token received from the native layer.
/// On iOS this comes from APNs via the Swift bridge; on Android from FCM.
pub struct PushTokenState(pub std::sync::Mutex<Option<String>>);

impl PushTokenState {
    pub fn get(&self) -> Option<String> {
        self.0.lock().unwrap_or_else(|e| e.into_inner()).clone()
    }

    pub fn set(&self, token: String) {
        *self.0.lock().unwrap_or_else(|e| e.into_inner()) = Some(token);
    }
}

// ─── Cross-platform commands ────────────────────────

#[tauri::command]
pub fn get_forge_api_url() -> String {
    std::env::var("FORGE_API_URL").unwrap_or_else(|_| "http://localhost:8000".to_string())
}

#[tauri::command]
pub fn get_app_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

#[tauri::command]
pub async fn get_connection_status() -> Result<String, String> {
    let url =
        std::env::var("FORGE_API_URL").unwrap_or_else(|_| "http://localhost:8000".to_string());

    let addr = url
        .trim_start_matches("http://")
        .trim_start_matches("https://")
        .to_string();

    let result = std::thread::spawn(move || {
        use std::net::TcpStream;
        use std::time::Duration;

        match TcpStream::connect_timeout(
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

// ─── Mobile push commands ───────────────────────────

/// Store a push device token from the native layer (Swift/Kotlin → JS → Rust).
/// The frontend calls this after receiving the token via the JS bridge, then
/// sends it to the backend API for registration.
#[tauri::command]
pub fn set_push_token(app: AppHandle, token: String) -> Result<(), String> {
    use tauri::Manager;
    if let Some(state) = app.try_state::<PushTokenState>() {
        state.set(token);
        Ok(())
    } else {
        Err("Push token state not initialised".to_string())
    }
}

/// Retrieve the current push device token (if available).
#[tauri::command]
pub fn get_push_token(app: AppHandle) -> Option<String> {
    use tauri::Manager;
    app.try_state::<PushTokenState>()
        .and_then(|state| state.get())
}

// ─── Secure storage (keyring) ───────────────────────

const KEYRING_SERVICE: &str = "com.forge.desktop";

#[tauri::command]
pub fn save_secure_data(key: String, value: String) -> Result<(), String> {
    let entry = keyring::Entry::new(KEYRING_SERVICE, &key)
        .map_err(|e| format!("Keyring entry error: {}", e))?;
    entry
        .set_password(&value)
        .map_err(|e| format!("Failed to save to keyring: {}", e))
}

#[tauri::command]
pub fn get_secure_data(key: String) -> Result<Option<String>, String> {
    let entry = keyring::Entry::new(KEYRING_SERVICE, &key)
        .map_err(|e| format!("Keyring entry error: {}", e))?;
    match entry.get_password() {
        Ok(val) => Ok(Some(val)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(e) => Err(format!("Failed to read from keyring: {}", e)),
    }
}

#[tauri::command]
pub fn delete_secure_data(key: String) -> Result<(), String> {
    let entry = keyring::Entry::new(KEYRING_SERVICE, &key)
        .map_err(|e| format!("Keyring entry error: {}", e))?;
    match entry.delete_credential() {
        Ok(()) => Ok(()),
        Err(keyring::Error::NoEntry) => Ok(()), // Already deleted
        Err(e) => Err(format!("Failed to delete from keyring: {}", e)),
    }
}

// ─── HTTP proxy command ─────────────────────────────
// Proxies HTTP requests through Rust to avoid CORS / WebKit restrictions.

#[derive(serde::Serialize)]
pub struct ProxyResponse {
    pub status: u16,
    pub body: String,
    pub headers: std::collections::HashMap<String, String>,
}

#[tauri::command]
pub async fn proxy_fetch(
    url: String,
    method: Option<String>,
    body: Option<String>,
    auth_token: Option<String>,
) -> Result<ProxyResponse, String> {
    let client = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|e| format!("Failed to build client: {}", e))?;
    let method = method.unwrap_or_else(|| "GET".to_string());

    let mut req = match method.to_uppercase().as_str() {
        "POST" => client.post(&url),
        "PUT" => client.put(&url),
        "PATCH" => client.patch(&url),
        "DELETE" => client.delete(&url),
        _ => client.get(&url),
    };

    req = req.header("Content-Type", "application/json");

    if let Some(token) = auth_token {
        req = req.header("Authorization", format!("Bearer {}", token));
    }

    if let Some(b) = body {
        req = req.body(b);
    }

    let res = req.send().await.map_err(|e| format!("Request failed: {}", e))?;
    let status = res.status().as_u16();

    let mut headers = std::collections::HashMap::new();
    for (key, value) in res.headers().iter() {
        if let Ok(v) = value.to_str() {
            // Collect all Set-Cookie values joined by "; "
            if key.as_str() == "set-cookie" {
                headers
                    .entry(key.to_string())
                    .and_modify(|existing: &mut String| {
                        existing.push_str("; ");
                        existing.push_str(v);
                    })
                    .or_insert_with(|| v.to_string());
            } else {
                headers.insert(key.to_string(), v.to_string());
            }
        }
    }

    let text = res.text().await.map_err(|e| format!("Failed to read response: {}", e))?;

    Ok(ProxyResponse { status, body: text, headers })
}

// ─── Desktop-only commands ──────────────────────────

#[cfg(desktop)]
use std::process::Command;

#[cfg(desktop)]
use tauri::Manager;

#[cfg(desktop)]
#[tauri::command]
pub async fn open_in_vscode(path: String) -> Result<(), String> {
    Command::new("code")
        .arg(&path)
        .spawn()
        .map_err(|e| format!("Failed to open VS Code: {}. Is 'code' in your PATH?", e))?;
    Ok(())
}

#[cfg(desktop)]
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

#[cfg(desktop)]
#[tauri::command]
pub fn set_close_to_tray(app: AppHandle, enabled: bool) -> Result<(), String> {
    app.manage(CloseToTrayState(std::sync::Mutex::new(enabled)));
    Ok(())
}

#[cfg(desktop)]
pub struct CloseToTrayState(pub std::sync::Mutex<bool>);

#[cfg(desktop)]
impl CloseToTrayState {
    pub fn is_enabled(&self) -> bool {
        *self.0.lock().unwrap_or_else(|e| e.into_inner())
    }
}
