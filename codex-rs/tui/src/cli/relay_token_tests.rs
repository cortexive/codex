use super::*;
use insta::assert_snapshot;
use pretty_assertions::assert_eq;

#[test]
fn accepts_sequential_decimal_tokens() {
    for token in ["ANVL-0001", "ANVIL-0042", "ABCDEFGHIJKLMNOP-9999"] {
        assert!(is_valid_token(token), "expected valid token: {token}");
    }
}

#[test]
fn rejects_noncanonical_tokens() {
    for token in [
        "ANV-0001",
        "ABCDEFGHIJKLMNOPQ-0001",
        "anvil-0001",
        "ANVIL-001",
        "ANVIL-00001",
        "ANVIL-00A1",
        "ANVIL-00H1",
        "ANVIL_0001",
        "ANVIL--0001",
        " ANVIL-0001",
        "ANVIL-0001 ",
    ] {
        assert!(!is_valid_token(token), "expected invalid token: {token}");
    }
}

#[test]
fn extracts_token_from_the_actual_compact_relay_prompt_shape() {
    let prompt = "Before review, verify `RELAY_ROOT: HELIOS`, `RELAY_TOKEN: HELIOS-0009`, and the frozen head.";

    assert_eq!(
        extract_prompt_token(prompt),
        Ok(Some("HELIOS-0009".to_string()))
    );
}

#[test]
fn accepts_repeated_identical_token_mentions() {
    let prompt = "RELAY_ROOT: HELIOS\nRELAY_TOKEN: HELIOS-0009\nFinal line: RELAY_TOKEN: HELIOS-0009";

    assert_eq!(
        extract_prompt_token(prompt),
        Ok(Some("HELIOS-0009".to_string()))
    );
}

#[test]
fn leaves_ordinary_prompts_unbound() {
    assert_eq!(extract_prompt_token("Review this pull request."), Ok(None));
}

#[test]
fn rejects_conflicting_tokens_or_roots() {
    assert_eq!(
        extract_prompt_token(
            "RELAY_TOKEN: HELIOS-0009\nRELAY_TOKEN: HELIOS-0010"
        ),
        Err("prompt contains conflicting RELAY_TOKEN values".to_string())
    );
    assert_eq!(
        extract_prompt_token("RELAY_ROOT: ORCHID\nRELAY_TOKEN: HELIOS-0009"),
        Err("RELAY_ROOT ORCHID does not match RELAY_TOKEN HELIOS-0009".to_string())
    );
}

#[test]
fn rejects_missing_placeholder_or_malformed_literal_values() {
    for prompt in [
        "RELAY_ROOT: HELIOS",
        "RELAY_TOKEN: {{issuedRelayToken}}",
        "RELAY_TOKEN: HELIOS-00H9",
        "RELAY_TOKEN: helios-0009",
    ] {
        assert!(extract_prompt_token(prompt).is_err(), "expected error: {prompt}");
    }
}

#[test]
fn marker_text_inside_a_larger_identifier_is_ignored() {
    assert_eq!(
        extract_prompt_token("NOT_RELAY_TOKEN: HELIOS-0009"),
        Ok(None)
    );
}

#[test]
fn relay_status_line_keeps_the_token_slot_first_and_deduplicated() {
    let items = prepend_thread_title(
        Some(vec![
            "current-dir".to_string(),
            "thread-title".to_string(),
            "model-with-reasoning".to_string(),
        ]),
        &["model-with-reasoning", "current-dir"],
    );

    assert_eq!(
        items,
        vec![
            "thread-title".to_string(),
            "current-dir".to_string(),
            "model-with-reasoning".to_string(),
        ]
    );
    assert_snapshot!(
        items.join(" · "),
        @"thread-title · current-dir · model-with-reasoning"
    );
}

#[test]
fn relay_status_line_preserves_defaults_when_unconfigured() {
    assert_eq!(
        prepend_thread_title(None, &["model-with-reasoning", "current-dir"]),
        vec![
            "thread-title".to_string(),
            "model-with-reasoning".to_string(),
            "current-dir".to_string(),
        ]
    );
}

#[test]
fn relay_status_line_overrides_an_explicitly_empty_selection() {
    assert_eq!(
        prepend_thread_title(Some(Vec::new()), &["model-with-reasoning", "current-dir"]),
        vec!["thread-title".to_string()]
    );
}
