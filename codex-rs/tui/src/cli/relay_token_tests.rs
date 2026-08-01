use super::*;
use insta::assert_snapshot;
use pretty_assertions::assert_eq;

#[test]
fn accepts_sequential_decimal_tokens() {
    for token in ["ANVL-0001", "ANVIL-0042", "ABCDEFGHIJKLMNOP-9999"] {
        assert!(is_valid(token), "expected valid token: {token}");
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
        assert!(!is_valid(token), "expected invalid token: {token}");
    }
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
