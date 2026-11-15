use serde::{Deserialize, Serialize};
use std::fmt;
use ts_rs::TS;

/// Why a command or a request was refused: `{"error": {"message", "place"}}`,
/// where `place` names the input, file or folder at fault. Commands check
/// their inputs once, at the start.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, TS)]
#[ts(export, rename = "ApiError")] // TypeScript's own `Error` keeps its name.
pub struct Error {
    /// What went wrong and, where the user can act, what to do.
    pub message: String,
    /// The input (such as `market`), file or folder the message is about.
    pub place: String,
}

impl Error {
    pub fn new(message: impl Into<String>, place: impl fmt::Display) -> Error {
        Error { message: message.into(), place: place.to_string() }
    }

    /// The same error with `prefix` in front of its place, as a caller that
    /// knows the wider place adds it: `PREFIX, PLACE`, or `PREFIX` when the
    /// place is empty.
    pub fn within(self, prefix: impl fmt::Display) -> Error {
        let place = if self.place.is_empty() { prefix.to_string() } else { format!("{prefix}, {}", self.place) };
        Error { place, ..self }
    }

    /// The same error with the file it is about in front of its place:
    /// `FILE: PLACE`, or `FILE` when the place is empty.
    pub fn in_file(self, file: impl fmt::Display) -> Error {
        let place = if self.place.is_empty() { file.to_string() } else { format!("{file}: {}", self.place) };
        Error { place, ..self }
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.place, self.message)
    }
}
