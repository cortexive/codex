use std::sync::OnceLock;
use std::sync::RwLock;

pub(crate) const CORTEX_STATUSLINE_RELAY_PREFIX: &str = "CORTEX_STATUSLINE_RELAY:";
const CLEAR_VALUE: &str = "CLEAR";

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum CortexRelayUpdate {
    Clear,
    Set(String),
}

#[derive(Default)]
struct CortexRelayProjection {
    token: Option<String>,
    restore_explicit_empty_status_line: bool,
}

static CORTEX_RELAY_PROJECTION: OnceLock<RwLock<CortexRelayProjection>> = OnceLock::new();

fn projection() -> &'static RwLock<CortexRelayProjection> {
    CORTEX_RELAY_PROJECTION.get_or_init(|| RwLock::new(CortexRelayProjection::default()))
}

pub(crate) fn parse_cortex_relay_message(text: &str) -> Option<CortexRelayUpdate> {
    let value = text.strip_prefix(CORTEX_STATUSLINE_RELAY_PREFIX)?;
    if value == CLEAR_VALUE {
        return Some(CortexRelayUpdate::Clear);
    }
    is_valid_token(value).then(|| CortexRelayUpdate::Set(value.to_string()))
}

pub(crate) fn set_cortex_relay_token(
    token: String,
    restore_explicit_empty_status_line: bool,
) {
    if !is_valid_token(&token) {
        return;
    }
    let Ok(mut state) = projection().write() else {
        return;
    };
    state.token = Some(token);
    state.restore_explicit_empty_status_line |= restore_explicit_empty_status_line;
}

pub(crate) fn clear_cortex_relay_token() -> bool {
    let Ok(mut state) = projection().write() else {
        return false;
    };
    let restore = state.restore_explicit_empty_status_line;
    *state = CortexRelayProjection::default();
    restore
}

pub(crate) fn cortex_relay_token() -> Option<String> {
    projection().read().ok()?.token.clone()
}

fn is_valid_token(value: &str) -> bool {
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

    #[test]
    fn parses_only_the_reserved_clear_or_canonical_token_messages() {
        assert_eq!(
            parse_cortex_relay_message("CORTEX_STATUSLINE_RELAY:ANVIL-0002"),
            Some(CortexRelayUpdate::Set("ANVIL-0002".to_string()))
        );
        assert_eq!(
            parse_cortex_relay_message("CORTEX_STATUSLINE_RELAY:CLEAR"),
            Some(CortexRelayUpdate::Clear)
        );
        assert_eq!(
            parse_cortex_relay_message("CORTEX_STATUSLINE_RELAY:ANVIL-00H2"),
            None
        );
        assert_eq!(parse_cortex_relay_message("ordinary hook warning"), None);
    }

    #[test]
    fn clear_returns_whether_an_explicit_empty_status_line_must_be_restored() {
        clear_cortex_relay_token();
        set_cortex_relay_token("ANVIL-0002".to_string(), true);
        assert_eq!(cortex_relay_token().as_deref(), Some("ANVIL-0002"));
        assert!(clear_cortex_relay_token());
        assert_eq!(cortex_relay_token(), None);
    }

    #[test]
    fn later_tokens_replace_the_projection_without_losing_restore_state() {
        clear_cortex_relay_token();
        set_cortex_relay_token("ANVIL-0002".to_string(), true);
        set_cortex_relay_token("ANVIL-0003".to_string(), false);
        assert_eq!(cortex_relay_token().as_deref(), Some("ANVIL-0003"));
        assert!(clear_cortex_relay_token());
    }
}
