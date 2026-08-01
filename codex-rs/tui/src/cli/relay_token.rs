use std::sync::OnceLock;

const RELAY_TOKEN_FORMAT: &str = "^[A-Z]{4,16}-[0-9]{4}$";
const THREAD_TITLE_STATUS_ITEM: &str = "thread-title";

static RELAY_TOKEN: OnceLock<String> = OnceLock::new();

pub(super) fn parse_and_bind(value: &str) -> Result<String, String> {
    if !is_valid(value) {
        return Err(format!(
            "invalid Cortex relay token; expected {RELAY_TOKEN_FORMAT}"
        ));
    }

    if let Some(bound) = RELAY_TOKEN.get() {
        return if bound == value {
            Ok(value.to_string())
        } else {
            Err("a different Cortex relay token is already bound to this process".to_string())
        };
    }

    RELAY_TOKEN
        .set(value.to_string())
        .map_err(|_| "failed to bind the Cortex relay token".to_string())?;
    Ok(value.to_string())
}

pub(crate) fn current() -> Option<&'static str> {
    RELAY_TOKEN.get().map(String::as_str)
}

pub(crate) fn initial_thread_title_seed() -> Option<String> {
    current().map(str::to_string)
}

pub(crate) fn status_line_items(
    configured: Option<Vec<String>>,
    default_items: &[&str],
) -> Option<Vec<String>> {
    if current().is_none() {
        return configured;
    }

    Some(prepend_thread_title(configured, default_items))
}

fn prepend_thread_title(configured: Option<Vec<String>>, default_items: &[&str]) -> Vec<String> {
    let mut items = configured.unwrap_or_else(|| {
        default_items
            .iter()
            .map(ToString::to_string)
            .collect::<Vec<_>>()
    });
    items.retain(|item| item != THREAD_TITLE_STATUS_ITEM);
    items.insert(0, THREAD_TITLE_STATUS_ITEM.to_string());
    items
}

fn is_valid(value: &str) -> bool {
    if value.trim() != value {
        return false;
    }

    let Some((root, sequence)) = value.split_once('-') else {
        return false;
    };

    (4..=16).contains(&root.len())
        && root.bytes().all(|byte| byte.is_ascii_uppercase())
        && sequence.len() == 4
        && sequence.bytes().all(|byte| byte.is_ascii_digit())
}

#[cfg(test)]
#[path = "relay_token_tests.rs"]
mod tests;
