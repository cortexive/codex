use std::collections::BTreeMap;
use std::env;

#[derive(Clone, Debug, Default)]
struct Session {
    thread: String,
    relay: Option<String>,
    native_title: Option<String>,
    model_context: Vec<String>,
    persisted: Vec<String>,
    remote_control: Vec<String>,
}

trait ExternalStatusSegment {
    fn accept(&mut self, thread: &str, relay: &str) -> bool;
    fn clear_successor(&mut self, old_thread: &str, new_thread: &str);
    fn render(&self, thread: &str, native: &[String]) -> Vec<String>;
    fn session(&self, thread: &str) -> Option<&Session>;
}

#[derive(Default)]
struct FixtureAdapter {
    sessions: BTreeMap<String, Session>,
    refresh_before_model: bool,
    preserve_native: bool,
    leak_to_model: bool,
}

impl FixtureAdapter {
    fn qualified() -> Self {
        Self {
            refresh_before_model: true,
            preserve_native: true,
            ..Self::default()
        }
    }

    fn unqualified() -> Self {
        Self {
            refresh_before_model: false,
            preserve_native: false,
            leak_to_model: true,
            ..Self::default()
        }
    }
}

impl ExternalStatusSegment for FixtureAdapter {
    fn accept(&mut self, thread: &str, relay: &str) -> bool {
        if !valid_thread(thread) || !valid_relay(relay) {
            return false;
        }
        let session = self.sessions.entry(thread.to_string()).or_default();
        session.thread = thread.to_string();
        session.relay = Some(relay.to_string());
        session.native_title = Some(format!("thread:{thread}"));
        if self.leak_to_model {
            session.model_context.push(relay.to_string());
        }
        true
    }

    fn clear_successor(&mut self, _old_thread: &str, new_thread: &str) {
        self.sessions.insert(
            new_thread.to_string(),
            Session {
                thread: new_thread.to_string(),
                ..Session::default()
            },
        );
    }

    fn render(&self, thread: &str, native: &[String]) -> Vec<String> {
        let mut rendered = Vec::new();
        if self.refresh_before_model {
            if let Some(relay) = self.sessions.get(thread).and_then(|value| value.relay.clone()) {
                rendered.push(relay);
            }
        }
        if self.preserve_native {
            rendered.extend(native.iter().cloned());
        }
        rendered
    }

    fn session(&self, thread: &str) -> Option<&Session> {
        self.sessions.get(thread)
    }
}

fn valid_thread(value: &str) -> bool {
    (8..=128).contains(&value.len())
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
}

fn valid_relay(value: &str) -> bool {
    let Some((root, ordinal)) = value.split_once('-') else {
        return false;
    };
    (4..=16).contains(&root.len())
        && root.bytes().all(|byte| byte.is_ascii_uppercase())
        && ordinal.len() == 4
        && ordinal.bytes().all(|byte| byte.is_ascii_digit())
}

fn prove(mut adapter: FixtureAdapter) -> Result<(), &'static str> {
    let alpha = "01987d20-1abc-7000-8000-000000000001";
    let successor = "01987d20-1abc-7000-8000-000000000002";
    let beta = "01987d20-1abc-7000-8000-000000000003";
    if !adapter.accept(alpha, "FORGE-0002") {
        return Err("external-dynamic-content");
    }
    let native = vec!["thread-title".to_string(), "context-window".to_string()];
    if adapter.render(alpha, &native) != ["FORGE-0002", "thread-title", "context-window"] {
        return Err("independent-prefix-preserves-native-fields");
    }
    if adapter.render(alpha, &[] as &[String]) != ["FORGE-0002"] {
        return Err("visible-with-empty-native-selection");
    }
    if !adapter.accept(alpha, "FORGE-0003") || adapter.render(alpha, &[] as &[String]) != ["FORGE-0003"] {
        return Err("valid-relay-hot-swap");
    }
    if adapter.accept(alpha, "FORGE-00X4") || adapter.render(alpha, &[] as &[String]) != ["FORGE-0003"] {
        return Err("malformed-correlation-preserves-prior-token");
    }
    adapter.clear_successor(alpha, successor);
    if !adapter.render(successor, &[] as &[String]).is_empty() {
        return Err("clear-successor-isolation");
    }
    if !adapter.accept(beta, "ANVIL-0001")
        || adapter.render(alpha, &[] as &[String]) != ["FORGE-0003"]
        || adapter.render(beta, &[] as &[String]) != ["ANVIL-0001"]
    {
        return Err("concurrent-session-isolation");
    }
    let session = adapter.session(alpha).ok_or("active-thread-identity")?;
    if session.thread != alpha || session.native_title.as_deref() != Some(&format!("thread:{alpha}")) {
        return Err("active-thread-identity");
    }
    if !adapter.refresh_before_model {
        return Err("post-prompt-pre-model-refresh");
    }
    if session.model_context.iter().chain(&session.persisted).chain(&session.remote_control).any(|v| v.contains("FORGE")) {
        return Err("no-relay-leakage");
    }
    if adapter.render(alpha, &native).first().map(String::as_str) != Some("FORGE-0003") {
        return Err("ordinary-prompt-continuity");
    }
    Ok(())
}

fn main() {
    let fixture = env::args().nth(1).unwrap_or_else(|| "native-pass".to_string());
    let adapter = match fixture.as_str() {
        "native-pass" | "overlay" => FixtureAdapter::qualified(),
        "native-fail" => FixtureAdapter::unqualified(),
        _ => {
            eprintln!("unknown fixture: {fixture}");
            std::process::exit(2);
        }
    };
    match prove(adapter) {
        Ok(()) => println!("PARITY: PASS fixture={fixture} rows=11"),
        Err(row) => {
            println!("PARITY: FAIL fixture={fixture} row={row}");
            std::process::exit(1);
        }
    }
}
