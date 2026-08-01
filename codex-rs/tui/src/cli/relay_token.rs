use std::collections::BTreeSet;
use std::sync::OnceLock;
use std::sync::RwLock;

const RELAY_ROOT_MARKER: &str = "RELAY_ROOT:";
const RELAY_TOKEN_MARKER: &str = "RELAY_TOKEN:";
const RELAY_TOKEN_FORMAT: &str = "^[A-Z]{4,16}-[0-9]{4}$";
const THREAD_TITLE_STATUS_ITEM: &str = "thread-title";

static RELAY_TOKEN: OnceLock<RwLock<Option<String>>> = OnceLock::new();

fn relay_token_state() -> &'static RwLock<Option<String>> {
    RELAY_TOKEN.get_or_init(|| RwLock::new(None))
}

pub(crate) fn current() -> Option<String> {
    relay_token_state().read().ok()?.clone()
}

pub(crate) fn initial_thread_title_seed() -> Option<String> {
    None
}

pub(crate) fn update_from_prompt(prompt: &str) -> Result<bool, String> {
    let Some(token) = extract_prompt_token(prompt)? else {
        return Ok(false);
    };
    let mut current = relay_token_state()
        .write()
        .map_err(|_| "Cortex relay-token state is unavailable".to_string())?;
    if current.as_deref() == Some(token.as_str()) {
        return Ok(false);
    }
    *current = Some(token);
    Ok(true)
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

fn extract_prompt_token(prompt: &str) -> Result<Option<String>, String> {
    let tokens = marker_values(prompt, RELAY_TOKEN_MARKER, is_valid_token)?;
    let roots = marker_values(prompt, RELAY_ROOT_MARKER, is_valid_root)?;

    if tokens.is_empty() {
        return if roots.is_empty() {
            Ok(None)
        } else {
            Err("RELAY_ROOT is present but RELAY_TOKEN is missing".to_string())
        };
    }

    let unique_tokens = tokens.into_iter().collect::<BTreeSet<_>>();
    if unique_tokens.len() != 1 {
        return Err("prompt contains conflicting RELAY_TOKEN values".to_string());
    }
    let token = unique_tokens
        .into_iter()
        .next()
        .expect("one unique relay token");
    let token_root = token
        .split_once('-')
        .map(|(root, _)| root)
        .expect("validated relay token has a root");

    let unique_roots = roots.into_iter().collect::<BTreeSet<_>>();
    if unique_roots.len() > 1 {
        return Err("prompt contains conflicting RELAY_ROOT values".to_string());
    }
    if let Some(root) = unique_roots.into_iter().next()
        && root != token_root
    {
        return Err(format!(
            "RELAY_ROOT {root} does not match RELAY_TOKEN {token}"
        ));
    }

    Ok(Some(token))
}

fn marker_values(
    prompt: &str,
    marker: &str,
    validator: fn(&str) -> bool,
) -> Result<Vec<String>, String> {
    let mut values = Vec::new();
    let mut search_start = 0;

    while let Some(relative_start) = prompt[search_start..].find(marker) {
        let marker_start = search_start + relative_start;
        search_start = marker_start + marker.len();

        if marker_start > 0
            && prompt[..marker_start]
                .chars()
                .next_back()
                .is_some_and(|ch| ch.is_ascii_alphanumeric() || ch == '_')
        {
            continue;
        }

        let after_marker = &prompt[search_start..];
        let value_start = after_marker
            .find(|ch: char| !ch.is_ascii_whitespace())
            .unwrap_or(after_marker.len());
        let candidate_source = &after_marker[value_start..];
        let candidate_len = candidate_source
            .char_indices()
            .take_while(|(_, ch)| ch.is_ascii_alphanumeric() || *ch == '-' || *ch == '_')
            .last()
            .map_or(0, |(index, ch)| index + ch.len_utf8());
        if candidate_len == 0 {
            return Err(format!("{marker} must be followed by a literal value"));
        }
        let candidate = &candidate_source[..candidate_len];
        if !validator(candidate) {
            let expected = if marker == RELAY_TOKEN_MARKER {
                RELAY_TOKEN_FORMAT
            } else {
                "^[A-Z]{4,16}$"
            };
            return Err(format!("invalid {marker} value; expected {expected}"));
        }
        values.push(candidate.to_string());
        search_start += value_start + candidate_len;
    }

    Ok(values)
}

fn is_valid_root(value: &str) -> bool {
    (4..=16).contains(&value.len())
        && value.bytes().all(|byte| byte.is_ascii_uppercase())
}

fn is_valid_token(value: &str) -> bool {
    let Some((root, sequence)) = value.split_once('-') else {
        return false;
    };

    is_valid_root(root)
        && sequence.len() == 4
        && sequence.bytes().all(|byte| byte.is_ascii_digit())
}

#[cfg(test)]
#[path = "relay_token_tests.rs"]
mod tests;
