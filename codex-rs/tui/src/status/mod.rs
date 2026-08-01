//! Status output formatting and display adapters for the TUI.
//!
//! This module turns protocol-level snapshots into stable display structures used by `/status`
//! output and footer/status-line helpers, while keeping rendering concerns out of transport-facing
//! code.
//!
//! `rate_limits` is the main integration point for status-line usage-limit items: it converts raw
//! window snapshots into local-time labels and classifies data as available, stale, or missing.
mod account;
mod card;
mod cortex_relay;
mod format;
mod helpers;
mod rate_limits;
pub(crate) mod remote_connection;

pub(crate) use account::StatusAccountDisplay;
pub(crate) use card::StatusHistoryHandle;
#[cfg(test)]
pub(crate) use card::new_status_output;
#[cfg(test)]
pub(crate) use card::new_status_output_with_rate_limits;
pub(crate) use card::new_status_output_with_rate_limits_handle;
pub(crate) use cortex_relay::CortexRelayUpdate;
pub(crate) use cortex_relay::clear_cortex_relay_token;
pub(crate) use cortex_relay::cortex_relay_token;
pub(crate) use cortex_relay::parse_cortex_relay_message;
pub(crate) use cortex_relay::set_cortex_relay_token;
pub(crate) use helpers::compose_agents_summary;
pub(crate) use helpers::format_directory_display;
pub(crate) use helpers::format_tokens_compact;
pub(crate) use helpers::plan_type_display_name;
pub(crate) use rate_limits::RateLimitSnapshotDisplay;
pub(crate) use rate_limits::RateLimitWindowDisplay;
#[cfg(test)]
pub(crate) use rate_limits::rate_limit_snapshot_display;
pub(crate) use rate_limits::rate_limit_snapshot_display_for_limit;

#[cfg(test)]
mod tests;
