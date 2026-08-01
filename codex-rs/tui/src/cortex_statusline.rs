//! Read-only projection of Task Manager-owned status-line state.
//!
//! Cortex hooks materialize a small, atomic cache file after Task Manager has
//! accepted a delegation prompt. The TUI only renders that accepted state; it
//! does not parse prompts, own relay sequencing, or require launch arguments.

use serde::Deserialize;
use std::env;
use std::fs;
use std::path::Path;
use std::path::PathBuf;

const CACHE_VERSION: u8 = 1;
const MAX_CACHE_BYTES: u64 = 4_096;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RelayStatuslineCache {
    version: u8,
    session_id: String,
    relay_token: Option<String>,
}

pub(crate) fn relay_token_for_session(session_id: &str) -> Option<String> {
    if !is_safe_session_id(session_id) {
        return None;
    }
    let path = relay_statusline_cache_dir()?.join(format!("{session_id}.json"));
    read_relay_token(&path, session_id)
}

fn relay_statusline_cache_dir() -> Option<PathBuf> {
    if let Some(configured) = env::var_os("CORTEX_STATUSLINE_CACHE_DIR")
        && !configured.is_empty()
    {
        return Some(PathBuf::from(configured));
    }
    if let Some(cache_home) = env::var_os("XDG_CACHE_HOME")
        && !cache_home.is_empty()
    {
        return Some(
            PathBuf::from(cache_home)
                .join("cortexive")
                .join("statusline")
                .join("relay"),
        );
    }
    let home = env::var_os("HOME")?;
    Some(
        PathBuf::from(home)
            .join(".cache")
            .join("cortexive")
            .join("statusline")
            .join("relay"),
    )
}

fn read_relay_token(path: &Path, expected_session_id: &str) -> Option<String> {
    let metadata = fs::metadata(path).ok()?;
    if !metadata.is_file() || metadata.len() > MAX_CACHE_BYTES {
        return None;
    }
    let raw = fs::read_to_string(path).ok()?;
    let cache: RelayStatuslineCache = serde_json::from_str(&raw).ok()?;
    if cache.version != CACHE_VERSION || cache.session_id != expected_session_id {
        return None;
    }
    cache
        .relay_token
        .filter(|token| is_valid_relay_token(token))
}

fn is_safe_session_id(value: &str) -> bool {
    (8..=128).contains(&value.len())
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
}

fn is_valid_relay_token(value: &str) -> bool {
    let Some((root, sequence)) = value.split_once('-') else {
        return false;
    };
    (4..=16).contains(&root.len())
        && root.bytes().all(|byte| byte.is_ascii_uppercase())
        && sequence.len() == 4
        && sequence.bytes().all(|byte| byte.is_ascii_digit())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;
    use std::fs::write;
    use tempfile::tempdir;

    #[test]
    fn reads_a_matching_task_manager_projection() {
        let temp = tempdir().expect("tempdir");
        let session_id = "01987d20-1abc-7000-8000-000000000001";
        let path = temp.path().join("relay.json");
        write(
            &path,
            format!(
                r#"{{"version":1,"sessionId":"{session_id}","relayRoot":"ANVIL","relayToken":"ANVIL-0002","updatedAt":42}}"#
            ),
        )
        .expect("write cache");

        assert_eq!(
            read_relay_token(&path, session_id),
            Some("ANVIL-0002".to_string())
        );
    }

    #[test]
    fn rejects_wrong_session_malformed_token_and_oversized_cache() {
        let temp = tempdir().expect("tempdir");
        let path = temp.path().join("relay.json");
        write(
            &path,
            r#"{"version":1,"sessionId":"session-1","relayToken":"ANVIL-00H2"}"#,
        )
        .expect("write cache");
        assert_eq!(read_relay_token(&path, "session-1"), None);
        assert_eq!(read_relay_token(&path, "session-2"), None);

        write(&path, "x".repeat((MAX_CACHE_BYTES + 1) as usize)).expect("write large");
        assert_eq!(read_relay_token(&path, "session-1"), None);
    }

    #[test]
    fn validates_cache_key_and_token_shapes() {
        assert!(is_safe_session_id("01987d20-1abc-7000-8000-000000000001"));
        assert!(!is_safe_session_id("../escape"));
        assert!(is_valid_relay_token("HELIOS-0009"));
        assert!(!is_valid_relay_token("HELIOS-00H9"));
    }
}
